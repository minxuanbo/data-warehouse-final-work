"""PostgreSQL warehouse CLI: init, run, verify, export and benchmark.

The only permitted source error is the documented missing-payment metric gate.
All structural/count/amount mismatches roll back the warehouse transaction.
"""
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from audit_olist import SCHEMAS, sha256

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('OLIST_REPORT_DIR',str(ROOT/'reports/system')))
ODS={'orders':'orders','items':'order_items','payments':'order_payments','reviews':'order_reviews',
     'customers':'customers','products':'products','sellers':'sellers','geolocation':'geolocation','translation':'category_translation'}
EXPORTS={
 'kpi_overview':'SELECT * FROM ads.kpi_overview',
 'trade_month':'SELECT * FROM ads.trade_month ORDER BY year_no,month_no',
 'fulfillment_state':'SELECT * FROM ads.fulfillment_state ORDER BY state_code',
 'category_ranking':'SELECT * FROM ads.category_ranking ORDER BY item_amount DESC,category_name',
 'seller_ranking':'SELECT * FROM ads.seller_ranking ORDER BY item_amount DESC,seller_id',
 'delivery_review_comparison':'SELECT * FROM ads.delivery_review_comparison ORDER BY is_late',
 'review_distribution':'SELECT * FROM ads.review_distribution ORDER BY review_score',
}
LOCK=734198521

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def connect():
    path=ROOT/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                k,v=line.split('=',1)
                os.environ.setdefault(k.strip(),v.strip())
    conn=psycopg.connect(autocommit=True,row_factory=dict_row,connect_timeout=10)
    conn.add_notice_handler(lambda notice: print('SQL: '+notice.message_primary,flush=True))
    return conn

def code_version():
    try:
        result=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True)
        return result.stdout.strip() or 'uncommitted-initial-build'
    except OSError:
        return 'unavailable'

def ddl_digest():
    return hashlib.sha256(b''.join((ROOT/'sql'/name).read_bytes() for name in
        ['01_warehouse_schema.sql','02_runtime_and_marts.sql'])).hexdigest()

def initialize(conn):
    if conn.execute("SELECT to_regclass('audit.schema_version') AS name").fetchone()['name']:
        row=conn.execute('SELECT * FROM audit.schema_version WHERE version=1').fetchone()
        if row is None or row['ddl_sha256']!=ddl_digest():
            raise RuntimeError('DDL version differs; use a new development database or a reviewed migration')
        print('Schema version 1 already installed; no change')
        return
    if conn.execute("SELECT to_regclass('dwd.fact_order') AS name").fetchone()['name']:
        raise RuntimeError('Unversioned existing schema: use a separate empty database; no automatic reset')
    first=(ROOT/'sql/01_warehouse_schema.sql').read_text(encoding='utf-8').replace('BEGIN;\n','',1).replace('\nCOMMIT;','')
    with conn.transaction():
        conn.execute(first)
        conn.execute((ROOT/'sql/02_runtime_and_marts.sql').read_text(encoding='utf-8'))
        conn.execute('INSERT INTO audit.schema_version(version,ddl_sha256) VALUES(1,%s)',(ddl_digest(),))
    print('Installed warehouse schema version 1')

def preflight():
    summary=read_json(ROOT/'reports/data_acceptance/summary.json')
    source=read_json(ROOT/'data/source.json')
    if summary['source_archive_sha256']!=source['archive_sha256']:
        raise RuntimeError('Source/audit mismatch; rerun data audit')
    if summary['script_sha256']!=sha256(ROOT/'scripts/audit_olist.py'):
        raise RuntimeError('Source audit script changed; rerun data audit')
    with (ROOT/'data/manifest.csv').open(encoding='utf-8-sig',newline='') as f:
        manifest=list(csv.DictReader(f))
    if {x['file_name'] for x in manifest}!={s[0] for s in SCHEMAS.values()} or len(manifest)!=9:
        raise RuntimeError('Manifest must contain exactly the nine source files')
    for entry in manifest:
        if sha256(ROOT/'data/raw'/entry['file_name'])!=entry['sha256']:
            raise RuntimeError('Raw file hash changed: '+entry['file_name'])
    with (ROOT/'reports/data_acceptance/checks.csv').open(encoding='utf-8-sig',newline='') as f:
        checks=list(csv.DictReader(f))
    blocked=[x for x in checks if x['status']=='FAIL' and x['rule']!='delivered_without_payments']
    if blocked:
        raise RuntimeError('Blocking source checks: '+','.join(x['rule'] for x in blocked))
    fingerprint=hashlib.sha256(json.dumps(sorted((m['file_name'],m['sha256']) for m in manifest)).encode()).hexdigest()
    return source,summary,manifest,checks,fingerprint

def load_raw(conn,source,manifest,fingerprint):
    existing=conn.execute('SELECT batch_id FROM audit.load_batch WHERE source_fingerprint=%s AND status=%s',
        (fingerprint,'passed')).fetchone()
    if existing:
        print(f"Reusing immutable ODS batch {existing['batch_id']}",flush=True)
        return existing['batch_id'],True
    with conn.transaction():
        batch=conn.execute("INSERT INTO audit.load_batch(status,code_version,source_fingerprint) VALUES('running',%s,%s) RETURNING batch_id",
            (code_version(),fingerprint)).fetchone()['batch_id']
        manifest_by_name={x['file_name']:x for x in manifest}
        for table,(filename,columns,_) in SCHEMAS.items():
            entry=manifest_by_name[filename]
            conn.execute('INSERT INTO audit.source_file(batch_id,file_name,source_url,sha256,row_count,downloaded_at,license_note) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                (batch,filename,source['source_url'],entry['sha256'],int(entry['rows']),source['retrieved_at'],source['license']))
            statement=sql.SQL('COPY ods.{} ({}) FROM STDIN').format(sql.Identifier(ODS[table]),
                sql.SQL(',').join(map(sql.Identifier,['batch_id','source_row_no']+columns.split())))
            count=0
            with (ROOT/'data/raw'/filename).open(encoding='utf-8-sig',newline='') as f:
                reader=csv.reader(f)
                if next(reader)!=columns.split():
                    raise RuntimeError('Unexpected source header: '+filename)
                with conn.cursor().copy(statement) as copy:
                    for count,row in enumerate(reader,1):
                        copy.write_row([batch,count]+row)
            if count!=int(entry['rows']):
                raise RuntimeError('COPY row count differs from manifest: '+filename)
            print(f'ODS {ODS[table]}: {count:,} rows',flush=True)
        conn.execute("UPDATE audit.load_batch SET status='passed',finished_at=CURRENT_TIMESTAMP WHERE batch_id=%s",(batch,))
    return batch,False

def validate(conn,summary,manifest,batch,strict_payment=False):
    results=[]
    m=summary['metrics']
    def equal(name,actual,expected,severity='error',tolerance=Decimal('0')):
        passed=(actual==expected if actual is None or expected is None else
                abs(Decimal(str(actual))-Decimal(str(expected)))<=tolerance)
        results.append({'name':name,'actual':actual,'expected':expected,'passed':passed,'severity':severity})
    def scalar(statement,args=()):
        return next(iter(conn.execute(statement,args).fetchone().values()))
    for entry in manifest:
        table=ODS[entry['table']]
        equal('ods_count_'+table,scalar(sql.SQL('SELECT COUNT(*) FROM ods.{} WHERE batch_id=%s').format(sql.Identifier(table)),(batch,)),int(entry['rows']))
    for table,expected in [('fact_order',m['all_orders']),('fact_order_item',next(int(x['rows']) for x in manifest if x['table']=='items')),
                           ('fact_payment',next(int(x['rows']) for x in manifest if x['table']=='payments')),('fact_review',m['selected_reviews'])]:
        equal('dwd_count_'+table,scalar(sql.SQL('SELECT COUNT(*) FROM dwd.{}').format(sql.Identifier(table))),expected)
    equal('order_wide_grain',scalar('SELECT COUNT(*) FROM dws.order_wide'),m['all_orders'])
    for scope,where in [('all',''),('delivered'," WHERE o.order_status='delivered'")]:
        for label,table,column in [('item','fact_order_item','price'),('freight','fact_order_item','freight_value'),('payment','fact_payment','payment_value')]:
            actual=scalar(sql.SQL('SELECT SUM(f.{})*100 FROM dwd.{} f JOIN dwd.fact_order o USING(order_id)'+where).format(sql.Identifier(column),sql.Identifier(table)))
            equal('amount_'+scope+'_'+label,actual,m[scope+'_'+label+'_cents'])
    for table in ['fact_order_item','fact_payment','fact_review']:
        actual=scalar(sql.SQL('SELECT COUNT(*) FROM dwd.{} f JOIN dwd.fact_order o USING(order_id) WHERE (f.purchase_date_key,f.customer_key,f.customer_geo_key) IS DISTINCT FROM (o.purchase_date_key,o.customer_key,o.customer_geo_key)').format(sql.Identifier(table)))
        equal('inherited_keys_'+table,actual,0)
    equal('purchase_date_key',scalar("SELECT COUNT(*) FROM dwd.fact_order o JOIN dim.dim_date d ON o.purchase_date_key=d.date_key WHERE o.purchase_ts::DATE IS DISTINCT FROM d.calendar_date"),0)
    kpi=conn.execute('SELECT * FROM ads.kpi_overview').fetchone()
    mappings={'all_orders':'all_orders','delivered_orders':'delivered_orders','delivered_buyers':'delivered_distinct_buyers',
        'valid_delivery_orders':'delivery_valid_orders','late_eligible_orders':'late_eligible_orders','late_orders':'late_orders',
        'reviewed_orders':'delivered_reviewed_orders','low_score_orders':'delivered_low_score_orders'}
    for actual,expected in mappings.items():
        equal('kpi_'+actual,kpi[actual],m[expected])
    for actual,expected in [('average_delivery_days','average_delivery_days'),('late_rate','late_rate'),
                            ('average_review_score','delivered_average_score'),('low_score_rate','delivered_low_score_rate')]:
        equal('kpi_'+actual,kpi[actual],m[expected],tolerance=Decimal('0.0000000001'))
    for actual,key in [('item_amount','delivered_item_cents'),('freight_amount','delivered_freight_cents'),('recorded_payment_amount','delivered_payment_cents')]:
        equal('kpi_'+actual,kpi[actual]*100,m[key])
    equal('payment_completeness',kpi['missing_payment_orders'],0,'error' if strict_payment else 'warning')
    if kpi['missing_payment_orders']:
        equal('incomplete_payment_is_null',kpi['complete_payment_amount'],None)
    for field in ['item_amount','freight_amount','recorded_payment_amount','delivered_orders']:
        equal('monthly_rollup_'+field,scalar(sql.SQL('SELECT SUM({}) FROM ads.trade_month').format(sql.Identifier(field))),kpi[field])
    for mart in ['ads.category_ranking','ads.seller_ranking']:
        equal('amount_rollup_'+mart,scalar('SELECT SUM(item_amount) FROM '+mart),kpi['item_amount'])
    for row in conn.execute('SELECT * FROM ads.delivery_review_comparison').fetchall():
        prefix='late' if row['is_late'] else 'on_time'
        equal(prefix+'_review_sample',row['reviewed_orders'],m[prefix+'_review_sample'])
        equal(prefix+'_review_low_rate',row['low_score_rate'],m[prefix+'_low_score_rate'],tolerance=Decimal('0.0000000001'))
    return results,kpi

def persist_checks(conn,run_id,batch,results):
    with conn.cursor() as cur:
        cur.executemany('INSERT INTO audit.quality_result(batch_id,model_name,check_name,severity,passed,failed_count,details,run_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
            [(batch,'warehouse',r['name'],r['severity'],r['passed'],0 if r['passed'] else 1,
              json.dumps({'actual':r['actual'],'expected':r['expected']},default=str),run_id) for r in results])

def export(conn):
    OUT.mkdir(parents=True,exist_ok=True)
    digests={}
    for name,query in EXPORTS.items():
        rows=conn.execute(query).fetchall()
        target=OUT/(name+'.csv')
        # DictCursor keys are available even for empty result sets via description.
        if rows:
            with target.open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        else:
            raise RuntimeError('Expected a nonempty analytical export: '+name)
        digests[name]=sha256(target)
    write_json(OUT/'export_hashes.json',digests)
    return digests

def run_pipeline(conn,args):
    source,summary,manifest,source_checks,fingerprint=preflight()
    initialize(conn)
    started=time.perf_counter()
    run_id=conn.execute("INSERT INTO audit.pipeline_run(status,code_version) VALUES('running',%s) RETURNING run_id",(code_version(),)).fetchone()['run_id']
    results=[]
    batch=None
    try:
        batch,reused=load_raw(conn,source,manifest,fingerprint)
        conn.execute('UPDATE audit.pipeline_run SET batch_id=%s WHERE run_id=%s',(batch,run_id))
        with conn.transaction():
            conn.execute("SELECT set_config('olist.batch_id',%s,true)",(str(batch),))
            for table in ODS.values():
                conn.execute(sql.SQL('ANALYZE ods.{}').format(sql.Identifier(table)))
            conn.execute((ROOT/'sql/03_transform.sql').read_text(encoding='utf-8'))
            results,kpi=validate(conn,summary,manifest,batch,args.strict_payment)
            if args.inject_failure:
                raise RuntimeError('Intentional rollback test after transform; no warehouse changes committed')
            errors=[r['name'] for r in results if not r['passed'] and r['severity']=='error']
            if errors:
                raise RuntimeError('Warehouse checks failed: '+','.join(errors))
            persist_checks(conn,run_id,batch,results)
            for r in source_checks:
                conn.execute('INSERT INTO audit.quality_result(batch_id,model_name,check_name,severity,passed,failed_count,details,run_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                    (batch,'source',r['rule'],r['severity'],r['status']=='PASS',int(r['affected_count']),r['note'],run_id))
            elapsed=time.perf_counter()-started
            status='passed_with_warnings' if any(not r['passed'] for r in results) or any(r['status']!='PASS' for r in source_checks) else 'passed'
            conn.execute('UPDATE audit.pipeline_run SET status=%s,finished_at=CURRENT_TIMESTAMP,elapsed_seconds=%s WHERE run_id=%s',(status,elapsed,run_id))
    except Exception as exc:
        # The model transaction has rolled back; preserve diagnostics in a fresh transaction.
        with conn.transaction():
            if batch:
                persist_checks(conn,run_id,batch,results)
            conn.execute("UPDATE audit.pipeline_run SET status='failed',finished_at=CURRENT_TIMESTAMP,elapsed_seconds=%s,error_message=%s WHERE run_id=%s",
                (time.perf_counter()-started,str(exc)[:2000],run_id))
        raise
    hashes=export(conn)
    evidence={'run_id':run_id,'batch_id':batch,'status':status,'ods_reused':reused,
        'elapsed_seconds':round(elapsed,3),'source_fingerprint':fingerprint,
        'executed_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'database_version':conn.execute('SELECT version() AS version').fetchone()['version'],
        'database_name':conn.execute('SELECT current_database() AS name').fetchone()['name'],
        'python_version':platform.python_version(),'platform':platform.platform(),
        'checks':results,'kpi':kpi,'exports_sha256':hashes,
        'transform_sha256':sha256(ROOT/'sql/03_transform.sql'),'ddl_sha256':ddl_digest(),
        'limitation':'complete_payment_amount is NULL until missing-payment source issue is resolved; recorded payment remains available with coverage'}
    write_json(OUT/'last_run.json',evidence)
    write_json(OUT/f'run_{run_id}.json',evidence)
    print(json.dumps({k:evidence[k] for k in ['run_id','batch_id','status','ods_reused','elapsed_seconds']},indent=2))

def benchmark(conn):
    rows=[]
    for name,query in EXPORTS.items():
        conn.execute(query).fetchall()
        times=[]
        for _ in range(3):
            start=time.perf_counter()
            conn.execute(query).fetchall()
            times.append(round((time.perf_counter()-start)*1000,3))
        rows.append({'query':name,'milliseconds':times,'max_ms':max(times)})
    plans={name:conn.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query).fetchone()['QUERY PLAN'] for name,query in EXPORTS.items()}
    write_json(OUT/'query_plans.json',plans)
    write_json(OUT/'benchmark.json',{'method':'one warmup and three measured executions including fetch; no concurrent workload',
        'python':platform.python_version(),'platform':platform.platform(),'cpu':platform.processor(),'logical_cpus':os.cpu_count(),
        'database':conn.execute('SELECT version() AS version').fetchone()['version'],'queries':rows})
    print(json.dumps(rows,indent=2))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['init','run','verify','export','benchmark'])
    parser.add_argument('--strict-payment',action='store_true',help='Treat missing payment as a whole-run blocker')
    parser.add_argument('--inject-failure',action='store_true',help='Rollback integration test; never changes raw files')
    args=parser.parse_args()
    with connect() as conn:
        if not conn.execute('SELECT pg_try_advisory_lock(%s) AS acquired',(LOCK,)).fetchone()['acquired']:
            raise RuntimeError('Another warehouse operation is running')
        if args.command=='init': initialize(conn)
        elif args.command=='run': run_pipeline(conn,args)
        elif args.command=='export': export(conn)
        elif args.command=='benchmark': benchmark(conn)
        else:
            _,summary,manifest,_,fingerprint=preflight()
            row=conn.execute('SELECT batch_id FROM audit.load_batch WHERE source_fingerprint=%s',(fingerprint,)).fetchone()
            if not row: raise RuntimeError('No matching loaded batch')
            results,_=validate(conn,summary,manifest,row['batch_id'],args.strict_payment)
            write_json(OUT/'verification.json',results)
            print(f"{sum(r['passed'] for r in results)}/{len(results)} checks passed; missing-payment gate remains explicit")
            if any(not r['passed'] and r['severity']=='error' for r in results): return 2
    return 0

if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        sys.exit(1)
