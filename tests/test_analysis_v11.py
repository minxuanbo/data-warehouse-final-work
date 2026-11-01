import copy
import unittest
from pathlib import Path
from warehouse.integrate_analysis import prepare,check_evidence


@unittest.skipUnless(Path('.local/skills_v11').exists(),'Run prepare_skills_v11 first')
class ThreeFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path('.local/skills_v11')
        cls.tencent=prepare('.local/cd_input/data/tencent/tencent_20261031T093102Z_366ad0a4',root/'reports/analysis/tencent_20261031T093102Z_366ad0a4/v1.1',root/'etl/skills/dictionary.json')
        cls.netease=prepare('.local/netease_input/data/netease/netease_20261101T044527Z_157cf969',root/'reports/analysis/netease_20261101T044527Z_157cf969/v1.1',root/'etl/skills/dictionary.json')

    def test_two_denominators_and_pairs(self):
        for prepared,expected in [(self.tencent,333),(self.netease,334)]:
            rows,enriched=prepared[3:5]
            self.assertEqual(sum(row['is_core'] for row in enriched),98)
            self.assertEqual(len({(r['source_job_id'],r['skill_name']) for r in rows if r['is_core'] and r['eligible_for_metric']}),expected)

    def test_additional_body_hash_is_enforced(self):
        row=next(row for row in self.tencent[3] if row['evidence_field']=='additional_requirements_raw')
        jobs={job['source_job_id']:copy.deepcopy(job) for job in self.tencent[4]}
        jobs[row['source_job_id']]['additional_requirements_raw']+=' changed'
        with self.assertRaisesRegex(ValueError,'hash'):
            check_evidence(row,jobs,{row['skill_name']},self.tencent[1])

    def test_netease_suggestion_separate_from_conflict(self):
        jobs={job['source_job_id']:job for job in self.netease[4]}
        self.assertTrue(jobs['78729']['experience_hint'])
        self.assertFalse(jobs['78729']['experience_conflict'])
        self.assertEqual(sum(job['experience_conflict'] for job in jobs.values()),12)
        self.assertTrue(jobs['71196']['education_conflict'])
        self.assertTrue(jobs['78590']['location_conflict'])
        self.assertFalse(jobs['78482']['is_core'])
        self.assertFalse(jobs['79489']['is_core'])
