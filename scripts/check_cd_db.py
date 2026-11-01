"""Independently reconcile C/D SQL metrics with evidence and exercise rollback."""
import json
from collections import Counter, defaultdict
from itertools import combinations
from unittest.mock import patch

from warehouse.export_cd import inputs
from warehouse.integrate_analysis import integrate, prepare
from warehouse.load import connect


if __name__ == '__main__':
    prepared = prepare(*inputs())
    checked, provenance, policy, evidence, enriched, input_hash = prepared
    first = integrate(*inputs())
    assert first['status'] == 'unchanged'
    build_id = first['build_id']
    core = {row['source_job_id'] for row in enriched if row['is_core']}
    per_job = defaultdict(set)
    for row in evidence:
        if row['source_job_id'] in core and row['eligible_for_metric']:
            per_job[row['source_job_id']].add(row['skill_name'])
    expected_skills = Counter(skill for skills in per_job.values() for skill in skills)
    expected_pairs = Counter(pair for skills in per_job.values() for pair in combinations(sorted(skills), 2))
    expected_cities = Counter()
    for row in enriched:
        if row['is_core']:
            groups = ['冲突待确认'] if row['location_conflict'] else (row['confirmed_locations'] or ['未知'])
            expected_cities.update(set(groups))
    connection = connect()
    try:
        actual = {row[0]: row[1] for row in connection.execute('SELECT skill_name,posting_count FROM ads.cd_skill_demand WHERE build_id=?', build_id)}
        assert actual == expected_skills
        actual_pairs = {tuple(sorted((row[0], row[1]))): row[2] for row in connection.execute('SELECT skill_a,skill_b,posting_count FROM ads.cd_skill_pair WHERE build_id=?', build_id)}
        assert actual_pairs == expected_pairs
        actual_cities = {row[0]: row[1] for row in connection.execute('SELECT city_group,posting_count FROM ads.cd_city WHERE build_id=?', build_id)}
        assert actual_cities == expected_cities
        assert connection.execute('SELECT SUM(evidence_count) FROM dwd.bridge_version_skill WHERE build_id=?', build_id).fetchval() == len(evidence)
        assert connection.execute('SELECT skill_denominator FROM dws.cd_scope_summary WHERE build_id=?', build_id).fetchval() == 98
        tables = ('audit.analysis_build', 'dwd.observation_enrichment', 'dwd.bridge_version_skill', 'dim.skill')
        before = [connection.execute(f'SELECT COUNT(*) FROM {table}').fetchval() for table in tables]
        fake_hash = '0' * 64
        assert connection.execute('SELECT COUNT(*) FROM audit.analysis_build WHERE input_hash=?', fake_hash).fetchval() == 0
        with patch('warehouse.integrate_analysis.prepare', return_value=(*prepared[:-1], fake_hash)):
            try:
                integrate(*inputs(), fail_after=10)
            except RuntimeError as exc:
                assert 'Injected' in str(exc)
            else:
                raise AssertionError('Rollback injection was not triggered')
        after = [connection.execute(f'SELECT COUNT(*) FROM {table}').fetchval() for table in tables]
        assert before == after
        connection.execute("IF DATABASE_PRINCIPAL_ID('dw_cd_read_test') IS NULL CREATE USER dw_cd_read_test WITHOUT LOGIN;")
        connection.execute('ALTER ROLE dw_cd_reader ADD MEMBER dw_cd_read_test;')
        connection.execute("EXECUTE AS USER='dw_cd_read_test';")
        try:
            assert connection.execute('SELECT COUNT(*) FROM ads.cd_job_detail WHERE build_id=?', build_id).fetchval() == 100
            assert connection.execute("SELECT HAS_PERMS_BY_NAME('ods.posting_record','OBJECT','SELECT')").fetchval() == 0
            assert connection.execute("SELECT HAS_PERMS_BY_NAME('dwd.observation_enrichment','OBJECT','UPDATE')").fetchval() == 0
        finally:
            connection.execute('REVERT;')
        print(json.dumps({'build_id': build_id, 'core_jobs': len(core), 'eligible_job_skill_pairs': sum(expected_skills.values()),
                          'eligible_jobs': len(per_job), 'skill_pair_types': len(expected_pairs), 'cities': actual_cities,
                          'reconciliation': 'passed', 'rerun': 'unchanged', 'rollback_after_10': 'passed',
                          'ads_read_only_role': 'passed'}, ensure_ascii=False))
    finally:
        connection.close()
