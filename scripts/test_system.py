"""Integration tests against the actual source-loaded development warehouse.

Two intentional failing runs exercise rollback and strict payment policy.
Only the application's own snapshot is rebuilt; raw data is unchanged.
"""
import json
import subprocess
import sys
from pathlib import Path
from warehouse import connect, export, write_json, OUT

ROOT=Path(__file__).resolve().parents[1]

def invoke(*args,expected_success=True):
    result=subprocess.run([sys.executable,str(ROOT/'scripts/warehouse.py'),*args],cwd=ROOT,
                          capture_output=True,text=True,encoding='utf-8',errors='replace')
    if (result.returncode==0)!=expected_success:
        raise AssertionError(result.stdout+'\n'+result.stderr)
    print(result.stdout or result.stderr,flush=True)
    return result.returncode

def main():
    checks=[]
    def check(name,value):
        if not value:
            raise AssertionError(name)
        checks.append({'test':name,'passed':True})
    with connect() as conn:
        initial=export(conn)
        ods_before=conn.execute('SELECT COUNT(*) AS n FROM ods.geolocation').fetchone()['n']
        batch_before=conn.execute('SELECT COUNT(*) AS n FROM audit.load_batch').fetchone()['n']
        first=conn.execute('SELECT * FROM ads.kpi_overview').fetchone()
        check('known_missing_payment_preserved',first['missing_payment_orders']==1 and first['complete_payment_amount'] is None)
        check('recorded_payment_not_zero_filled',first['recorded_payment_amount'] is not None and first['payment_order_coverage']<1)
        check('raw_review_rows_preserved',conn.execute('SELECT COUNT(*) AS n FROM ods.order_reviews').fetchone()['n']==99224)
        check('one_review_per_order',conn.execute('SELECT COUNT(*)=COUNT(DISTINCT order_id) AS ok FROM dwd.fact_review').fetchone()['ok'])
        check('missing_delivery_excluded',first['delivered_orders']-first['valid_delivery_orders']==8)
        # Boundary values are transient SQL expressions, never inserted as project facts.
        check('same_day_arrival_not_late',not conn.execute("SELECT TIMESTAMP '2018-01-01 23:59:59'::DATE > DATE '2018-01-01' AS late").fetchone()['late'])
        check('zero_denominator_is_null',conn.execute('SELECT 1::NUMERIC/NULLIF(0,0) AS rate').fetchone()['rate'] is None)
    invoke('run')
    with connect() as conn:
        check('repeat_run_kpi_exports_identical',export(conn)==initial)
        check('repeat_run_ods_not_duplicated',conn.execute('SELECT COUNT(*) AS n FROM ods.geolocation').fetchone()['n']==ods_before)
        check('repeat_run_source_batch_reused',conn.execute('SELECT COUNT(*) AS n FROM audit.load_batch').fetchone()['n']==batch_before)
    invoke('run','--inject-failure',expected_success=False)
    with connect() as conn:
        check('rollback_keeps_published_metrics',export(conn)==initial)
        row=conn.execute('SELECT status,error_message FROM audit.pipeline_run ORDER BY run_id DESC LIMIT 1').fetchone()
        check('rollback_failure_audited',row['status']=='failed' and 'Intentional rollback test' in row['error_message'])
    invoke('run','--strict-payment',expected_success=False)
    with connect() as conn:
        check('strict_payment_failure_preserves_snapshot',export(conn)==initial)
        row=conn.execute('SELECT status,error_message FROM audit.pipeline_run ORDER BY run_id DESC LIMIT 1').fetchone()
        check('strict_payment_gate_enforced',row['status']=='failed' and 'payment_completeness' in row['error_message'])
        versions=conn.execute('SELECT version() AS version').fetchone()
    invoke('verify')
    write_json(OUT/'integration_tests.json',{'status':'PASS','checks':checks,'database':versions['version'],
        'note':'The two failed runs in audit.pipeline_run are intentional rollback/strict-payment tests, not successful publication runs.'})
    print(f'PASS: {len(checks)} integration assertions')

if __name__=='__main__':
    main()
