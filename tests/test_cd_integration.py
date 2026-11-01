import copy
import unittest
from warehouse.export_cd import inputs
from warehouse.integrate_analysis import check_evidence, prepare


class CDInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        checked, cls.provenance, cls.policy, cls.evidence, cls.enriched, _ = prepare(*inputs())
        cls.jobs = {row['source_job_id']: row for row in checked['jobs']}
        cls.skills = {row['skill_name'] for row in cls.evidence}

    def test_core_scope_and_extra_fields(self):
        self.assertEqual(sum(row['is_core'] for row in self.enriched), 98)
        self.assertEqual(sum(bool(row['additional_requirements_raw']) for row in self.enriched), 28)
        self.assertEqual(sum(row['location_conflict'] for row in self.enriched), 9)
        self.assertEqual(sum(row['experience_conflict'] for row in self.enriched), 3)
        row = next(row for row in self.enriched if row['source_job_id'] == '2059160518509379584')
        self.assertEqual(set(row['confirmed_locations']), {'北京', '深圳'})

    def test_evidence_hash_tamper_rejected(self):
        row = copy.deepcopy(self.evidence[0])
        row['body_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'hash'):
            check_evidence(row, self.jobs, self.skills, self.provenance)

    def test_ineligible_evidence_cannot_be_promoted(self):
        row = copy.deepcopy(next(row for row in self.evidence if not row['eligible_for_metric']))
        row['eligible_for_metric'] = True
        with self.assertRaisesRegex(ValueError, 'eligibility'):
            check_evidence(row, self.jobs, self.skills, self.provenance)

    def test_invalid_span_rejected(self):
        row = copy.deepcopy(self.evidence[0])
        row['match_start'] = -1
        with self.assertRaisesRegex(ValueError, 'offsets'):
            check_evidence(row, self.jobs, self.skills, self.provenance)


if __name__ == '__main__':
    unittest.main()
