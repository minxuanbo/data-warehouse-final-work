"""Run bounded real SQL checks; rollback test uses a separate empty dev database."""
import json
import os
from warehouse.load import connect, initialize, load

INPUT='.local/pr1_input/data/tencent/tencent_20261031T093102Z_366ad0a4'
REV='f6eccadec28a4a1132c5953bbd92470c1d794348'
TABLES=['audit.collection_batch','ods.raw_response','ods.posting_record','audit.quality_issue','dim.posting_identity','dim.posting_version','dwd.fact_posting_observation','dwd.bridge_version_location']


def counts():
    c=connect()
    try:return {t:c.execute(f'SELECT COUNT(*) FROM {t}').fetchval() for t in TABLES}
    finally:c.close()


if __name__=='__main__':
    before=counts()
    result=load(INPUT,REV)
    assert result['status']=='unchanged' and before==counts(), 'Non-idempotent load'
    current=os.environ.get('DW_DATABASE')
    os.environ['DW_DATABASE']='recruitment_dw_dev_rollbackcheck'
    try:
        initialize()
        assert not any(counts().values()), 'Rollback check database must be empty'
        try:load(INPUT,REV,_fail_after=10)
        except RuntimeError as e:assert 'Injected' in str(e)
        else:raise AssertionError('Failure injection did not occur')
        assert not any(counts().values()), 'Transaction left partial data'
    finally:
        if current is None:os.environ.pop('DW_DATABASE',None)
        else:os.environ['DW_DATABASE']=current
    c=connect()
    try:
        city=[list(r) for r in c.execute('SELECT location_raw,source_posting_count FROM ads.trial_city ORDER BY source_posting_count DESC,location_raw')]
        assert c.execute('SELECT COUNT(*) FROM ads.trial_job_detail').fetchval()==100
        assert c.execute("SELECT COUNT(*) FROM audit.collection_batch WHERE acceptance_status='pending' AND load_mode='trial'").fetchval()==1
        print(json.dumps({'counts':before,'idempotent':True,'rollback_after_10':True,'city':city,'status':'trial_only'},ensure_ascii=False))
    finally:c.close()
