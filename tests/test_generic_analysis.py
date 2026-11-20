import json
import tempfile
import unittest
from pathlib import Path

from warehouse.prepare_analysis import generate
from warehouse.integrate_analysis import prepare


class ReviewedFieldPreservationTests(unittest.TestCase):
    def test_skill_rebuild_preserves_verified_field_findings_and_rejects_other_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            dictionary=Path('etl/skills/dictionary.json')
            for source,batch_id in [('tencent','tencent_20261031T093102Z_366ad0a4'),('netease','netease_20261101T044527Z_157cf969')]:
                batch=Path('data')/source/batch_id
                prior=Path('reports/analysis')/batch_id/'v1.1'
                output=Path(tmp)/source
                before=prepare(batch,prior,dictionary)
                generate(batch,output,dictionary,reviewed_analysis_path=prior)
                after=prepare(batch,output,dictionary)
                flags=lambda result:{j['source_job_id']:(j['location_conflict'],j['experience_conflict'],j['experience_hint']) for j in result[4]}
                self.assertEqual(flags(before),flags(after))
                self.assertEqual(generate(batch,output,dictionary,reviewed_analysis_path=prior)['status'],'unchanged')
                self.assertIn('data_issues_sha256',after[1]['field_review_source'])
                other='netease_20261101T044527Z_157cf969' if source=='tencent' else 'tencent_20261031T093102Z_366ad0a4'
                with self.assertRaisesRegex(ValueError,'source/batch mismatch'):
                    generate(batch,Path(tmp)/(source+'-wrong'),dictionary,reviewed_analysis_path=Path('reports/analysis')/other/'v1.1')


@unittest.skipUnless(Path('.local/skills_v11/etl/skills/dictionary.json').exists(),'Prepare source inputs first')
class GenericAnalysisTests(unittest.TestCase):
    def test_both_real_sources_recompute_without_frozen_analysis_outputs(self):
        with tempfile.TemporaryDirectory(dir='.local/tests') as tmp:
            dictionary=Path('.local/skills_v11/etl/skills/dictionary.json')
            for source,batch,expected in [
              ('tencent',Path('.local/cd_input/data/tencent/tencent_20261031T093102Z_366ad0a4'),334),
              ('netease',Path('.local/netease_input/data/netease/netease_20261101T044527Z_157cf969'),337)]:
                output=Path(tmp)/source
                result=generate(batch,output,dictionary)
                self.assertEqual((result['source_postings'],result['core_postings'],result['posting_skill_pairs']),(100,98,expected))
                self.assertEqual(generate(batch,output,dictionary)['status'],'unchanged')
                policy=json.loads((output/'scope_policy.json').read_text(encoding='utf-8'))
                policy['scope_version']='tampered'
                (output/'scope_policy.json').write_text(json.dumps(policy),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'policy hash'):prepare(batch,output,dictionary)


if __name__=='__main__':unittest.main()
