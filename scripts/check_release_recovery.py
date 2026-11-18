"""Exercise genuine SQL publication rollback and backup/restore in a new dev DB."""
import hashlib
import json
import os
import re
import time
from datetime import datetime,timezone
from pathlib import PureWindowsPath

from warehouse.load import ROOT,connect
from warehouse.release_build import build_release,publish,records


def snapshot(c):
    return {'batches':records(c,'SELECT batch_id,input_hash,source_revision,record_count FROM audit.collection_batch ORDER BY batch_id'),
            'analysis':records(c,'SELECT build_id,input_hash,status FROM audit.analysis_build ORDER BY build_id'),
            'publications':records(c,'SELECT channel,release_id FROM audit.publication_pointer ORDER BY channel'),
            'observations':c.execute('SELECT COUNT_BIG(*) FROM dwd.fact_posting_observation').fetchval(),
            'daily_rows':c.execute('SELECT COUNT_BIG(*) FROM dwd.fact_job_daily').fetchval(),
            'skills':records(c,'SELECT source,build_id,SUM(posting_count) AS skill_pairs FROM ads.cd_skill_demand GROUP BY source,build_id ORDER BY source,build_id')}


def main():
    database=os.getenv('DW_DATABASE','recruitment_dw_dev_cd_v1')
    if not re.fullmatch(r'recruitment_dw_dev(?:_[a-z0-9_]+)?',database):raise ValueError('Dedicated dev database required')
    os.environ['DW_DATABASE']=database
    c=connect()
    try:
        active=[r[0] for r in c.execute('SELECT build_id FROM ads.current_analysis_builds ORDER BY build_id')]
        complete=build_release(active)
        publish(complete['release_id'])
        repeated=build_release(active)
        assert repeated['status']=='unchanged' and repeated['release_id']==complete['release_id']
        before_pointer=c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()
        before_counts=records(c,'SELECT (SELECT COUNT(*) FROM audit.model_build) AS builds,(SELECT COUNT(*) FROM dwd.fact_job_daily) AS facts')[0]
        try:build_release([active[0]],fail_after=3)
        except RuntimeError as e:assert 'Injected snapshot failure' in str(e)
        else:raise AssertionError('Snapshot failure was not injected')
        assert before_counts==records(c,'SELECT (SELECT COUNT(*) FROM audit.model_build) AS builds,(SELECT COUNT(*) FROM dwd.fact_job_daily) AS facts')[0]
        candidate=build_release([active[0]])
        try:publish(candidate['release_id'],fail_before_pointer=True)
        except RuntimeError as e:assert 'Injected publication failure' in str(e)
        else:raise AssertionError('Publication failure was not injected')
        assert c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()==before_pointer
        try:build_release(active,channel='formal')
        except ValueError:pass
        else:raise AssertionError('Partial data was formally published')
        result={'database':database,'checked_at':datetime.now(timezone.utc).isoformat(),
                'idempotency':'passed','snapshot_transaction_rollback':'passed','publication_rollback':'passed',
                'partial_formal_publication_blocked':'passed','sample_release_id':before_pointer}
        timings={}
        for name,query in {
          'job_detail':f'SELECT COUNT_BIG(*) FROM ads.release_job_detail WHERE release_id={int(before_pointer)}',
          'daily_skill':f'SELECT TOP(20) * FROM ads.release_skill_demand WHERE release_id={int(before_pointer)} ORDER BY posting_count DESC',
          'quality_kpi':'SELECT * FROM ads.cd_quality_kpi WHERE build_id IN (SELECT build_id FROM ads.current_analysis_builds)'
        }.items():
            for run in range(4):
                started=time.perf_counter();cursor=c.execute(query);cursor.fetchall();cursor.close()
                if run:timings.setdefault(name,[]).append(round(time.perf_counter()-started,6))
        result['query_seconds_three_warm_runs']=timings
        result['performance_scope']='actual current 200-source-posting sample; not a 10,000/day capacity claim'
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
    output=ROOT/'reports/verification/发布与恢复实测_20261117.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
