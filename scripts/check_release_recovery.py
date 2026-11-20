"""Exercise genuine SQL publication rollback and backup/restore in a new dev DB."""
import argparse
import json
import os
import re
import time
from datetime import datetime,timezone
from pathlib import PureWindowsPath
from pathlib import Path

from warehouse.load import ROOT,connect
from warehouse.release_build import build_release,publish,records


def snapshot(c):
    return {'batches':records(c,'SELECT batch_id,input_hash,source_revision,record_count FROM audit.collection_batch ORDER BY batch_id'),
            'analysis':records(c,'SELECT build_id,input_hash,status FROM audit.analysis_build ORDER BY build_id'),
            'publications':records(c,'SELECT channel,release_id FROM audit.publication_pointer ORDER BY channel'),
            'observations':c.execute('SELECT COUNT_BIG(*) FROM dwd.fact_posting_observation').fetchval(),
            'daily_rows':c.execute('SELECT COUNT_BIG(*) FROM dwd.fact_job_daily').fetchval(),
            'skills':records(c,'SELECT source,build_id,SUM(posting_count) AS skill_pairs FROM ads.cd_skill_demand GROUP BY source,build_id ORDER BY source,build_id'),
            'published_inputs':records(c,"SELECT i.release_id,i.build_id,i.batch_id FROM audit.release_input i JOIN audit.publication_pointer p ON p.release_id=i.release_id ORDER BY i.release_id,i.build_id"),
            'published_skills':records(c,"SELECT p.channel,f.release_id,COUNT_BIG(*) skill_pairs FROM audit.publication_pointer p JOIN dwd.bridge_daily_skill f ON f.release_id=p.release_id GROUP BY p.channel,f.release_id ORDER BY p.channel,f.release_id")}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default=os.getenv('DW_DATABASE','recruitment_dw_dev_cd_v1'))
    parser.add_argument('--output', type=Path, help='New evidence file; existing evidence is never overwritten')
    args=parser.parse_args()
    output=args.output or ROOT/('reports/verification/发布与恢复实测_'+datetime.now().strftime('%Y%m%dT%H%M%S')+'.json')
    if output.exists():raise FileExistsError(output)
    database=args.database
    if not re.fullmatch(r'recruitment_dw_dev(?:_[a-z0-9_]+)?',database):raise ValueError('Dedicated dev database required')
    os.environ['DW_DATABASE']=database
    c=connect()
    try:
        # The legacy CD selection may differ from the published snapshot input.
        # Validate the actual release under test, including in a fresh reconstruction.
        active=[r[0] for r in c.execute("SELECT i.build_id FROM audit.release_input i JOIN audit.publication_pointer p ON p.release_id=i.release_id WHERE p.channel='sample' ORDER BY i.build_id")]
        if not active:raise ValueError('A published sample release is required')
        approved=json.loads(c.execute("SELECT b.expected_sources_json FROM audit.model_build b JOIN audit.publication_pointer p ON p.release_id=b.release_id WHERE p.channel='sample'").fetchval())
        complete=build_release(active,expected_sources=approved)
        publish(complete['release_id'])
        repeated=build_release(active,expected_sources=approved)
        assert repeated['status']=='unchanged' and repeated['release_id']==complete['release_id']
        before_pointer=c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()
        before_counts=records(c,'SELECT (SELECT COUNT(*) FROM audit.model_build) AS builds,(SELECT COUNT(*) FROM dwd.fact_job_daily) AS facts')[0]
        try:build_release([active[0]],expected_sources=approved,fail_after=3)
        except RuntimeError as e:assert 'Injected snapshot failure' in str(e)
        else:raise AssertionError('Snapshot failure was not injected')
        assert before_counts==records(c,'SELECT (SELECT COUNT(*) FROM audit.model_build) AS builds,(SELECT COUNT(*) FROM dwd.fact_job_daily) AS facts')[0]
        candidate=build_release([active[0]],expected_sources=approved)
        try:publish(candidate['release_id'],fail_before_pointer=True)
        except RuntimeError as e:assert 'Injected publication failure' in str(e)
        else:raise AssertionError('Publication failure was not injected')
        assert c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()==before_pointer
        try:build_release(active,channel='formal',expected_sources=approved)
        except ValueError:pass
        else:raise AssertionError('Partial data was formally published')
        result={'database':database,'checked_at':datetime.now(timezone.utc).isoformat(),
                'idempotency':'passed','snapshot_transaction_rollback':'passed','publication_rollback':'passed',
                'partial_formal_publication_blocked':'passed','sample_release_id':before_pointer}
        timings={};result_rows={}
        for name,query in {
          'job_detail':f'SELECT COUNT_BIG(*) FROM ads.release_job_detail WHERE release_id={int(before_pointer)}',
          'daily_skill':f'SELECT TOP(20) * FROM ads.release_skill_demand WHERE release_id={int(before_pointer)} ORDER BY posting_count DESC',
          'quality_kpi':f'SELECT * FROM ads.cd_quality_kpi WHERE build_id IN ({",".join(str(x) for x in active)})'
        }.items():
            for run in range(4):
                started=time.perf_counter();cursor=c.execute(query);rows=cursor.fetchall();cursor.close()
                assert rows, f'Benchmark query returned no rows: {name}'
                result_rows[name]=len(rows)
                if run:timings.setdefault(name,[]).append(round(time.perf_counter()-started,6))
        result['query_seconds_three_warm_runs']=timings
        result['query_result_rows']=result_rows
        result['performance_scope']='actual published source sample; not a 10,000/day or concurrency claim'
        result['approved_sources']=approved
        original=snapshot(c)
    finally:c.close()
    master=connect('master')
    try:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f').lower()
        restored='recruitment_dw_dev_restore_'+stamp
        if master.execute('SELECT DB_ID(?)',restored).fetchval() is not None:raise ValueError('Restore target already exists')
        backup_dir=master.execute("SELECT CONVERT(nvarchar(4000),SERVERPROPERTY('InstanceDefaultBackupPath'))").fetchval()
        data_dir=master.execute("SELECT CONVERT(nvarchar(4000),SERVERPROPERTY('InstanceDefaultDataPath'))").fetchval()
        log_dir=master.execute("SELECT CONVERT(nvarchar(4000),SERVERPROPERTY('InstanceDefaultLogPath'))").fetchval()
        if not all((backup_dir,data_dir,log_dir)):raise ValueError('SQL Server service directories unavailable')
        backup=str(PureWindowsPath(backup_dir)/(database+'_'+stamp+'.bak'))
        cur=master.execute(f'BACKUP DATABASE [{database}] TO DISK=? WITH COPY_ONLY,CHECKSUM',backup)
        while cur.nextset():pass
        cur.close()
        cur=master.execute('RESTORE VERIFYONLY FROM DISK=? WITH CHECKSUM',backup)
        while cur.nextset():pass
        cur.close()
        files=records(master,'RESTORE FILELISTONLY FROM DISK=?',backup)
        literal=lambda s:"N'"+s.replace("'","''")+"'"
        moves=[]
        for i,f in enumerate(files):
            if f['Type'] not in ('D','L'):raise ValueError('Unexpected SQL backup file type')
            dest=str(PureWindowsPath(log_dir if f['Type']=='L' else data_dir)/(restored+'_'+str(i)+('.ldf' if f['Type']=='L' else '.mdf')))
            moves.append('MOVE '+literal(f['LogicalName'])+' TO '+literal(dest))
        cur=master.execute(f'RESTORE DATABASE [{restored}] FROM DISK={literal(backup)} WITH '+','.join(moves)+',RECOVERY,CHECKSUM')
        while cur.nextset():pass
        cur.close()
    finally:master.close()
    restored_connection=connect(restored)
    try:assert snapshot(restored_connection)==original,'Restored evidence or metrics differ'
    finally:restored_connection.close()
    result.update(backup_verify='passed',restored_database=restored,backup_file=backup,restored_input_hashes_counts_metrics='passed',status='passed')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
