import json
from pathlib import Path
import unittest
from warehouse.qualifications import resolve,normalize_experience


class QualificationTests(unittest.TestCase):
    def education(self,text,raw=None):
        return resolve({'requirements_raw':text,'education_raw':raw})['education']

    def test_chinese_work_years_are_not_unmapped(self):
        for raw,expected in [('三年以上工作经验','3年以上'),('两年以上工作经验','2年以上'),
                             ('一年以上工作经验','1年以上'),('八年以上工作经验','8年以上'),
                             ('十年以上工作经验','10年以上'),('三至五年相关工作经验','3-5年')]:
            self.assertEqual(normalize_experience(raw),expected)

    def test_keep_bounds_conflicts_and_invalid_values(self):
        self.assertEqual(normalize_experience('３～５年'),'3-5年')
        self.assertEqual(normalize_experience('三年以上工作经验',True),'冲突待确认')
        self.assertEqual(normalize_experience('经验丰富'),'待解析')
        self.assertEqual(normalize_experience(None),'未注明')

    def test_missing_is_not_unlimited(self):
        self.assertEqual(self.education('精通C++')['value'],'未注明')
        self.assertEqual(self.education('学历不限')['value'],'不限')

    def test_required_bachelor_with_preferred_master(self):
        r=self.education('本科及以上学历，硕士、博士优先；熟悉开发。')
        self.assertEqual(r['value'],'本科');self.assertEqual(r['preferred'],['硕士','博士'])

    def test_skill_preference_does_not_change_degree_strength(self):
        r=self.education('计算机本科及以上学历，熟悉Unity引擎优先。')
        self.assertEqual((r['value'],r['status']),('本科','body_required'))

    def test_preference_only_does_not_become_a_required_degree(self):
        r=self.education('硕士学历优先；有项目经验。')
        self.assertEqual((r['value'],r['status']),('未注明','preference_only'))
        self.assertEqual(r['preferred'],['硕士'])

    def test_relaxed_requirements_need_review(self):
        self.assertEqual(self.education('博士（优秀硕士可放宽）。')['value'],'待确认')

    def test_alternative_degrees_use_lowest_explicit_option(self):
        self.assertEqual(self.education('硕士或博士学位')['value'],'硕士')

    def test_structured_body_conflict_is_not_silently_overwritten(self):
        self.assertEqual(self.education('硕士及以上学历','本科')['status'],'conflict')

    def test_mentored_students_are_not_applicant_qualifications(self):
        self.assertEqual(self.education('具有指导本科生的经验。')['value'],'未注明')

    def test_enrolled_bachelor_is_not_mistaken_for_mentored_student(self):
        for text in ('计算机相关专业在读本科生/研究生，每周至少出勤4天','学历：大四 ~ 研究生在读'):
            result=self.education(text,'本科')
            self.assertEqual((result['value'],result['status']),('本科','structured'))
            for e in result['evidence']:
                original='本科' if e['field']=='education_raw' else text
                self.assertEqual(original[e['start']:e['end']],e['text'])

    def test_graduate_student_requirement_can_reveal_a_real_source_conflict(self):
        result=self.education('相关专业的硕士生或博士生','本科')
        self.assertEqual((result['value'],result['status']),('冲突待确认','conflict'))

    def test_verbatim_offsets_roundtrip(self):
        text='任职要求：\n1.计算机相关专业本科及以上学历，硕士优先。'
        for e in self.education(text)['evidence']:
            self.assertEqual(text[e['start']:e['end']],e['text'])

    def test_real_tencent_examples_without_recollecting(self):
        p=Path('data/tencent/tencent_20261031T093102Z_366ad0a4/jobs.jsonl')
        jobs={j['source_job_id']:j for j in map(json.loads,p.read_text(encoding='utf-8').splitlines())}
        expected={'2077312480664797184':'本科','1930438817001635840':'硕士',
                  '2110191895966826496':'本科','2082723395740549120':'待确认',
                  '2083011858134118400':'硕士'}
        for identity,label in expected.items():self.assertEqual(resolve(jobs[identity])['education']['value'],label)


if __name__=='__main__':unittest.main()
