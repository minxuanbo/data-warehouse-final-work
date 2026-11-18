"""Read-only page fixtures; these are not recruitment records or production batches."""
import json
import tempfile
import unittest
from pathlib import Path
from collectors.coverage import assess_coverage


class CoverageTests(unittest.TestCase):
    def proof(self,source='tencent',total=2,last_total=None,stop='source_exhausted',gap=False,unprocessed=0):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'raw').mkdir()
            for page,items in [(1,[{'PostId':'a','id':'a'},{'PostId':'b','id':'b'}]),(3 if gap else 2,[])]:
                count=last_total if not items and last_total is not None else total
                data={'Code':200,'Data':{'Posts':items,'Count':count}} if source=='tencent' else {'code':200,'data':{'list':items,'total':count}}
                (root/'raw'/f'list_{page:06d}.json').write_text(json.dumps(data),encoding='utf-8')
            return assess_coverage(root,source,stop,{'output_records':1,'excluded_unique_ids':1,'unprocessed_unique_ids':unprocessed,'unidentified_records':0},[])

    def test_exact_exhausted_traversal_can_be_complete(self):
        for source in ('tencent','netease'):self.assertEqual(self.proof(source)['coverage_status'],'complete')

    def test_reaching_target_is_not_full_coverage(self):self.assertEqual(self.proof(stop='pilot_limit')['coverage_status'],'partial')
    def test_empty_terminal_page_does_not_hide_unseen_ids(self):self.assertEqual(self.proof(total=3)['coverage_status'],'partial')
    def test_changing_total_is_conservatively_partial(self):self.assertEqual(self.proof(last_total=3)['coverage_status'],'partial')
    def test_missing_page_or_unprocessed_record_blocks_complete(self):
        self.assertEqual(self.proof(gap=True)['coverage_status'],'partial')
        self.assertEqual(self.proof(unprocessed=1)['coverage_status'],'partial')


if __name__=='__main__':unittest.main()
