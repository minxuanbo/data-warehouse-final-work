import unittest
from warehouse.normalization import city,education,experience,category,employment_type


class ConformedDimensionTests(unittest.TestCase):
    def test_city_alias_and_province(self):
        self.assertEqual(city('杭州市'),city('杭州'))
        self.assertEqual(city('深圳')['province'],'广东')

    def test_unmapped_city_does_not_invent_geography(self):
        self.assertEqual(city('新地点')['province'],'未知')
        self.assertEqual(city('新地点')['mapping_status'],'unmapped')

    def test_missing_unlimited_and_conflict_are_distinct(self):
        self.assertEqual([education(None),education('不限'),education('本科',True)],['未知','不限','冲突待确认'])

    def test_source_experience_interval_is_not_falsely_refined(self):
        self.assertEqual(experience('3至5年'),'3-5年')
        self.assertNotEqual(experience('3-5年'),experience('3-4年'))

    def test_title_priority_for_broad_source_category(self):
        self.assertEqual(category('数据仓库开发工程师','技术'),'数据开发/分析')
        self.assertEqual(category('测试开发工程师','技术'),'测试')
        self.assertEqual(category('安全开发工程师','技术'),'运维/安全')

    def test_unknown_employment_code_is_not_social_recruitment(self):
        self.assertEqual(employment_type('tencent','1'),'来源代码未释义')

    def test_official_netease_work_types_do_not_imply_social_recruitment(self):
        self.assertEqual([employment_type('netease',v) for v in ('0','1','2')],['全职','实习','派遣'])
        self.assertEqual(employment_type('netease','99'),'来源代码未释义')

    def test_explicit_ai_domain_is_consistent_across_spacing_and_application_titles(self):
        for title in ('AI 平台研发工程师','资深AI应用工程师','AI Infra研发工程师','客户端开发（BOSS AI）'):
            self.assertEqual(category(title,'技术'),'算法/AI')
        self.assertEqual(category('Shader维护开发工程师','技术'),'开发')


if __name__=='__main__':unittest.main()
