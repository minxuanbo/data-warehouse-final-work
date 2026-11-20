"""Synthetic unit fixtures only; no generated data enters the warehouse."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collectors.enterprise import identity,map_job
from collectors.enterprise_coverage import assess
from collectors.tencent.client import Client,StopCollection
from warehouse.normalization import city,employment_type
from warehouse.qualifications import resolve
from warehouse.source_catalog import raw_identity,raw_posts
from warehouse.validate import FIELDS


class ExpansionSemanticsTests(unittest.TestCase):
    def test_province_is_never_invented_as_a_city(self):
        self.assertEqual(city('广东省'),{'code':'province:广东','name':'城市未披露','province':'广东','mapping_status':'province_only'})
        self.assertEqual(city('北京市')['name'],'北京')
        self.assertEqual(city('宿迁市')['province'],'江苏')

    def test_distinct_source_codebooks(self):
        self.assertEqual(employment_type('netease','1'),'实习')
        self.assertEqual(employment_type('xiaomi','1'),'社招渠道')
        self.assertEqual(employment_type('jd','社会招聘'),'社招渠道')
        self.assertEqual(employment_type('tencent','1'),'来源代码未释义')

    def test_raw_identity_and_bodies_preserve_source_semantics(self):
        post={'id':2,'jobPostId':'7700000000000000001','title':'软件开发工程师','url':'https://hr.xiaomi.com/job',
              'description':'职责原文','requirement':'本科，三年以上软件开发经验','cityZhNames':['北京'],'type':1}
        row=map_job('xiaomi',post,'unit-fixture','2026-11-21T00:00:00Z',{'path':'raw/unit.json','sha256':'0'*64})
        self.assertEqual(set(row),FIELDS)
        self.assertEqual(row['source_job_id'],'7700000000000000001')
        self.assertIsNone(row['experience_raw'])
        self.assertEqual(raw_identity('xiaomi',raw_posts('xiaomi',{'data':{'list':[post]}})[0]),row['source_job_id'])
        self.assertEqual(resolve(row)['experience']['value'],'3年以上')

    def test_body_experience_keeps_preferences_and_conditions(self):
        for body,expected in [('3年以上Java开发经验','3年以上'),('具有3-5年软件开发经验','3-5年'),
                               ('具有5年以上开发经验，其中3年以上管理经验','待确认'),
                               ('具有3年以上开发经验优先','未注明'),('产品计划在3年内上线','未注明'),
                               ('工作经验不限','不限')]:
            result=resolve({'requirements_raw':body})['experience']
            self.assertEqual(result['value'],expected,body)
            for e in result['evidence']:self.assertEqual(body[e['start']:e['end']],e['text'])

    def test_complete_requires_original_counts_and_terminal_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'raw').mkdir()
            for page,posts in [(1,[{'requirementId':'a'},{'requirementId':'b'}]),(2,[])]:
                (root/'raw'/f'list_{page:06d}.json').write_text(json.dumps(posts),encoding='utf-8')
            for name in ('count_start.json','count_end.json'):(root/'raw'/name).write_text('2')
            counts={'output_records':1,'excluded_unique_ids':1}
            self.assertEqual(assess(root,'jd','source_exhausted',counts,[])['coverage_status'],'complete')
            (root/'raw'/'count_end.json').write_text('3')
            self.assertEqual(assess(root,'jd','source_exhausted',counts,[])['coverage_status'],'partial')

    def test_valid_job_json_login_word_is_not_an_access_challenge(self):
        class Response:
            status=200
            class Headers:
                def get_content_charset(self):return 'utf-8'
            headers=Headers()
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'Code':200,'Data':{'Posts':[{'Responsibility':'负责账号登录体系'+'x'*3000}]}},ensure_ascii=False).encode()
        with patch('urllib.request.urlopen',return_value=Response()):
            self.assertEqual(Client().get('https://example.test',{}).status,200)
        class Challenge(Response):
            def read(self):return '请登录后验证验证码'.encode()
        with patch('urllib.request.urlopen',return_value=Challenge()):
            with self.assertRaises(StopCollection):Client().get('https://example.test',{})


if __name__=='__main__':unittest.main()
