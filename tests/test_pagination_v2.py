"""Boundary fixtures are synthetic and never enter collection or warehouse data."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collectors.pagination_v2 import page_data, assess, VERSION
from collectors.daily import Daily


class PaginationV2Tests(unittest.TestCase):
    def test_department_prefix_does_not_hide_explicit_software_roles(self):
        from scripts.accept_expansion import SOFTWARE_ROLE
        for title in ('营销与交易产品部-云mallJava后端开发工程师','微信开放平台-后台开发工程师-运营治理方向','腾讯营销-资深全栈开发工程师'):
            self.assertIsNotNone(SOFTWARE_ROLE.search(title))
        for title in ('营销产品经理','腾讯云通信技术运营','软件开发项目经理'):
            self.assertIsNone(SOFTWARE_ROLE.search(title))

    def test_netease_stops_on_last_data_page_not_out_of_range_zero(self):
        p={'code':200,'data':{'total':12,'pages':2,'lastPage':True,'list':[{'id':11},{'id':12}]}}
        self.assertTrue(page_data('netease',p,2,10)[2])
        p['data']['lastPage']=False
        with self.assertRaises(ValueError):page_data('netease',p,2,10)

    def test_jd_last_page_is_count_bounded_not_empty_page_bounded(self):
        self.assertTrue(page_data('jd',[{'requirementId':'last'}],2,10,11)[2])
        self.assertFalse(page_data('jd',[{'requirementId':'last'}],3,10,11)[2])

    def proof(self,source='jd',duplicate=False,end_count=12,gap=False):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'raw').mkdir()
            (p/'pagination.json').write_text(json.dumps({'version':VERSION,'page_size':10}))
            for page,ids in [(1,list(range(10))),(3 if gap else 2,[9 if duplicate else 10,11])]:
                posts=[{'requirementId':str(i),'id':str(i)} for i in ids]
                payload=posts if source=='jd' else {'code':200,'data':{'total':12,'pages':2,'lastPage':page==2,'list':posts}}
                (p/'raw'/f'list_{page:06d}.json').write_text(json.dumps(payload))
            for name,total in [('count_start.json',12),('count_end.json',end_count)]:
                (p/'raw'/name).write_text(str(total))
            return assess(p,source,'source_exhausted',{'output_records':12,'excluded_unique_ids':0},[])

    def test_exact_last_page_can_prove_coverage_without_empty_request(self):
        for source in ('netease','jd'):
            self.assertEqual(self.proof(source)['coverage_status'],'complete')

    def test_count_change_duplicate_or_gap_stays_partial(self):
        for kwargs in ({'duplicate':True},{'end_count':13},{'gap':True}):
            self.assertEqual(self.proof(**kwargs)['coverage_status'],'partial')

    def test_jd_final_count_is_attempted_after_a_network_stop(self):
        c=Daily.__new__(Daily)
        c.source='jd';c.max_pages=2;c.reason='max_pages';c.restricted=False;c.errors=[];c.requests=[]
        calls=[]
        def request(url,params,name,*args):
            calls.append(name)
            if name.startswith('list_'):raise ConnectionError('fixture connection stop')
            return 12,None,None
        # Stop after the independent final-count block, before disk finalization.
        with patch.object(c,'request',side_effect=request), patch('collectors.daily.assess',side_effect=RuntimeError('fixture end')):
            with tempfile.TemporaryDirectory() as tmp:
                c.path=Path(tmp);(c.path/'raw').mkdir();c.seen=set();c.jobs=[];c.excluded=set()
                with self.assertRaisesRegex(RuntimeError,'fixture end'):c.run()
        self.assertEqual(calls,['count_start.json','list_000001.json','count_end.json'])


if __name__=='__main__':unittest.main()
