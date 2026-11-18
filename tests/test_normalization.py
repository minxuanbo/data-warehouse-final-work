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


if __name__=='__main__':unittest.main()
