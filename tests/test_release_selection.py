"""Selection-policy fixtures. These are never loaded into recruitment business data."""
import json
import unittest
from warehouse.release_build import choose_inputs


def batch(source,build,end,coverage='complete',rule='r1'):
    return {'source':source,'build_id':build,'manifest_json':json.dumps({'finished_at':end}),
            'coverage_status':coverage,'acceptance_status':'accepted','scope_version':'scope1',
            'dictionary_version':'dict1','rule_version':rule,'body_hash_version':'body1','skill_text_scope':'fields1'}


class ReleaseSelectionTests(unittest.TestCase):
    def test_latest_complete_survives_later_partial(self):
        b=[batch('tencent',1,'2026-01-01T01:00:00Z'),batch('tencent',3,'2026-01-01T03:00:00Z','partial'),
           batch('netease',2,'2026-01-01T02:00:00Z')]
        self.assertEqual([x['build_id'] for x in choose_inputs(b,['tencent','netease'],'formal')],[2,1])

    def test_no_formal_release_for_partial_day(self):
        b=[batch('tencent',1,'2026-01-01T01:00:00Z','partial'),batch('netease',2,'2026-01-01T02:00:00Z')]
        with self.assertRaisesRegex(ValueError,'Missing source'):choose_inputs(b,['tencent','netease'],'formal')

    def test_cannot_silently_drop_incomplete_requested_date(self):
        b=[batch('tencent',1,'2026-01-01T01:00:00Z'),batch('netease',2,'2026-01-01T02:00:00Z'),
           batch('tencent',3,'2026-01-02T01:00:00Z','partial')]
        with self.assertRaisesRegex(ValueError,'requested dates'):choose_inputs(b,['tencent','netease'],'formal')

    def test_different_rules_cannot_produce_comparable_release(self):
        b=[batch('tencent',1,'2026-01-01T01:00:00Z'),batch('netease',2,'2026-01-01T01:00:00Z',rule='r2')]
        with self.assertRaisesRegex(ValueError,'Mixed'):choose_inputs(b,['tencent','netease'],'sample')

    def test_beijing_batch_end_day(self):
        b=[batch('tencent',1,'2026-01-01T17:00:00Z','partial')]
        self.assertEqual(str(choose_inputs(b,['tencent','netease'],'sample')[0]['snapshot_date']),'2026-01-02')

    def test_query_filter_change_blocks_comparison_even_if_version_string_is_reused(self):
        b=[batch('tencent',1,'2026-01-01T01:00:00Z'),batch('tencent',2,'2026-01-02T01:00:00Z')]
        b[1]['manifest_json']=json.dumps({'finished_at':'2026-01-02T01:00:00Z','query_spec':{'selection_rule':'keyword=SQL'}})
        with self.assertRaisesRegex(ValueError,'Changed collection query'):choose_inputs(b,['tencent','netease'],'sample')


if __name__=='__main__':unittest.main()
