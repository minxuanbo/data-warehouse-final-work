"""Reconcile the two accepted pilot batches against the warehouse."""
import json
from pathlib import Path
from warehouse.load import connect, load
from warehouse.validate import validate

INPUTS = [
    (Path('.local/cd_input/data/tencent/tencent_20261031T093102Z_366ad0a4'),
     '25b397bf846a8e7c39bbc249e0700428e89bc0c3'),
    (Path('.local/netease_input/data/netease/netease_20261101T044527Z_157cf969'),
     '0f862031ba07e5f46c3929818873dee7b9e05608'),
]

if __name__ == '__main__':
    checked = [validate(path) for path, _ in INPUTS]
    expected = {(row['source'], row['source_job_id'], row['batch_id']): row
                for batch in checked for row in batch['jobs']}
    for path, revision in INPUTS:
        assert load(path, revision)['status'] == 'unchanged'
    connection = connect()
    try:
        rows = connection.execute('SELECT b.source,p.source_job_id,p.batch_id,p.payload FROM ods.posting_record p JOIN audit.collection_batch b ON b.batch_id=p.batch_id').fetchall()
        actual = {(row[0], row[1], row[2]): json.loads(row[3]) for row in rows}
        assert actual == expected and len(rows) == 200
        overview = {row[0]: row[1] for row in connection.execute('SELECT source,source_posting_count FROM ads.trial_overview')}
        assert overview == {'tencent': 100, 'netease': 100}
        assert connection.execute('SELECT COUNT(*) FROM ads.dual_job_detail').fetchval() == 200
        assert connection.execute("SELECT COUNT(*) FROM audit.collection_batch WHERE acceptance_status='accepted' AND coverage_status='partial'").fetchval() == 2
        assert connection.execute("SELECT COUNT(*) FROM ads.dual_job_detail WHERE source='netease' AND education_conflict=1 AND source_job_id='71196'").fetchval() == 1
        cities = {row[0]: row[1] for row in connection.execute("SELECT city_group,source_posting_count FROM ads.dual_city WHERE source='netease'")}
        assert cities == {'杭州': 47, '广州': 35, '上海': 16, '北京': 2}
        education = {row[0]: row[1] for row in connection.execute("SELECT education_group,source_posting_count FROM ads.dual_education WHERE source='netease'")}
        assert education == {'本科': 61, '不限': 36, '硕士': 2, '冲突待确认': 1}
        assert connection.execute('SELECT skill_denominator FROM ads.cd_overview WHERE build_id=1').fetchval() == 98
        print(json.dumps({'sources': overview, 'ods_equals_input': True, 'observations': 200,
                          'rerun': 'unchanged', 'netease_city': cities, 'netease_education': education,
                          'tencent_skill_denominator': 98, 'netease_skill_status': 'awaiting_D'}, ensure_ascii=False))
    finally:
        connection.close()
