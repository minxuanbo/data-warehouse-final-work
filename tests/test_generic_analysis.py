import json
import tempfile
import unittest
from pathlib import Path

from warehouse.prepare_analysis import generate
from warehouse.integrate_analysis import prepare


@unittest.skipUnless(Path('.local/skills_v11/etl/skills/dictionary.json').exists(),'Prepare source inputs first')
class GenericAnalysisTests(unittest.TestCase):
    def test_both_real_sources_recompute_without_frozen_analysis_outputs(self):
        with tempfile.TemporaryDirectory(dir='.local/tests') as tmp:
            dictionary=Path('.local/skills_v11/etl/skills/dictionary.json')
            for source,batch,expected in [
              ('tencent',Path('.local/cd_input/data/tencent/tencent_20261031T093102Z_366ad0a4'),333),
              ('netease',Path('.local/netease_input/data/netease/netease_20261101T044527Z_157cf969'),334)]:
                output=Path(tmp)/source
                result=generate(batch,output,dictionary)
                self.assertEqual((result['source_postings'],result['core_postings'],result['posting_skill_pairs']),(100,98,expected))
                self.assertEqual(generate(batch,output,dictionary)['status'],'unchanged')
                policy=json.loads((output/'scope_policy.json').read_text(encoding='utf-8'))
                policy['scope_version']='tampered'
                (output/'scope_policy.json').write_text(json.dumps(policy),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'policy hash'):prepare(batch,output,dictionary)


if __name__=='__main__':unittest.main()
