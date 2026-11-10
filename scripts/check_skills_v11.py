"""Reconcile both v1.1 skill builds and optionally select them atomically."""
import argparse
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from warehouse.integrate_analysis import integrate, prepare
from warehouse.load import connect


def input_paths():
    root = Path('.local/skills_v11')
    for source, batch in [('tencent',Path('.local/cd_input/data/tencent/tencent_20261031T093102Z_366ad0a4')),
                          ('netease',Path('.local/netease_input/data/netease/netease_20261101T044527Z_157cf969'))]:
        yield source, batch, root/'reports/analysis'/batch.name/'v1.1', root/'etl/skills/dictionary.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activate',action='store_true')
    args = parser.parse_args()
    connection = connect()
    summaries = []
    try:
        for source, batch, analysis, dictionary in input_paths():
            checked, provenance, policy, evidence, enriched, input_hash = prepare(batch,analysis,dictionary)
            result = integrate(batch,analysis,dictionary)
            assert result['status']=='unchanged'
            build_id = result['build_id']
            per_job = defaultdict(set)
            for row in evidence:
                if row['is_core'] and row['eligible_for_metric']:
                    per_job[row['source_job_id']].add(row['skill_name'])
            expected = Counter(skill for values in per_job.values() for skill in values)
            expected_pairs = Counter(pair for values in per_job.values() for pair in combinations(sorted(values),2))
            actual = {row[0]:row[1] for row in connection.execute('SELECT skill_name,posting_count FROM ads.cd_skill_demand WHERE build_id=?',build_id)}
            actual_pairs = {tuple(sorted((row[0],row[1]))):row[2] for row in connection.execute('SELECT skill_a,skill_b,posting_count FROM ads.cd_skill_pair WHERE build_id=?',build_id)}
            assert expected==actual and expected_pairs==actual_pairs
            columns = 'skill_denominator,body_hash_version,skill_text_scope,rule_version,dictionary_version,experience_conflict_count,experience_hint_count,education_conflict_count'
            summary = connection.execute(f'SELECT {columns} FROM ads.cd_overview WHERE build_id=?',build_id).fetchone()
            assert summary[0]==98 and summary[1]=='skills-body-1.1'
            assert summary[2]=='description_raw+requirements_raw+additional_requirements_raw'
            assert summary[3:5]==('skills-rules-0.3.0','skills-dict-0.2.0')
            assert connection.execute('SELECT SUM(evidence_count) FROM dwd.bridge_version_skill WHERE build_id=?',build_id).fetchval()==len(evidence)
            assert sum(expected.values())=={'tencent':333,'netease':334}[source]
            if source=='netease':
                assert tuple(summary[5:])==(12,13,1)
                assert connection.execute("SELECT COUNT(*) FROM ads.cd_job_detail WHERE build_id=? AND source_job_id='78590' AND location_conflict=1",build_id).fetchval()==1
            summaries.append({'source':source,'batch_id':batch.name,'build_id':build_id,'denominator':98,
                              'eligible_posting_skill_pairs':sum(expected.values()),'evidence_rows':len(evidence),
                              'body_hash_version':summary[1],'skill_text_scope':summary[2],
                              'rule_version':summary[3],'dictionary_version':summary[4],
                              'experience_conflicts':summary[5],'experience_hints':summary[6],
                              'education_conflicts':summary[7]})
        if args.activate:
            connection.execute('SET XACT_ABORT ON; BEGIN TRANSACTION;')
            connection.execute("DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource='analysis_selection',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000; IF @r<0 THROW 50003,'selection lock timeout',1;")
            for result in summaries:
                if connection.execute("SELECT COUNT(*) FROM audit.analysis_build WHERE batch_id=? AND build_id=? AND status='ready'",result['batch_id'],result['build_id']).fetchval()!=1:
                    raise ValueError('Selected build is not ready')
                connection.execute('DELETE FROM audit.analysis_selection WHERE batch_id=?',result['batch_id'])
                connection.execute('INSERT INTO audit.analysis_selection VALUES(?,?)',result['batch_id'],result['build_id'])
            connection.execute('COMMIT TRANSACTION;')
            selected = {row[0]:row[1] for row in connection.execute('SELECT source,build_id FROM ads.current_analysis_builds')}
            assert selected=={row['source']:row['build_id'] for row in summaries}
        output = Path('.local/skills_v11/verification.json')
        output.write_text(json.dumps(summaries,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(summaries,ensure_ascii=False))
    except Exception:
        connection.execute('IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;')
        raise
    finally:
        connection.close()
