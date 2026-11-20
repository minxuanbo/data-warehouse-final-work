"""Business subjects and a reproducible training decision from a four-source release."""
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from itertools import combinations
import json
from pathlib import Path

from warehouse.load import ROOT,connect
from warehouse.release_build import records


def write(record,jobs,skills,output_dir=None):
    out=Path(output_dir or ROOT/'reports/verification/expansion_current');out.mkdir(parents=True,exist_ok=True)
    core=[j for j in jobs if j['is_core']]
    body=[j for j in core if j['body_valid']]
    key=lambda j:(j['date_key'],j['job_key'])
    c=connect(record['database'])
    try:
        cities=records(c,'SELECT date_key,job_key,province_name,city_name,mapping_status FROM ads.release_city_detail WHERE release_id=?',record['release_id'])
        changes=records(c,'SELECT date_key,is_complete,is_comparable,newly_observed_count,content_changed_count FROM ads.release_observed_change WHERE release_id=?',record['release_id'])
    finally:c.close()
    assert all(not r['is_comparable'] and r['newly_observed_count'] is None and r['content_changed_count'] is None for r in changes)
    provinces=defaultdict(set)
    for row in cities:provinces[key(row)].add(row['province_name'])
    by_source_direction={s:dict(Counter(j['category_group'] for j in core if j['source']==s)) for s in record['sources']}
    experience=Counter((j['source'],j['experience_group']) for j in core)
    cohorts=defaultdict(list)
    for j in body:
        if j['category_group']=='开发' and j['education_group']=='本科':
            for province in provinces[key(j)]-{'未知','冲突待确认'}:cohorts[province].append(j)
    if not cohorts:raise ValueError('No disclosed bachelor/development cohort for the scenario')
    province,cohort=max(cohorts.items(),key=lambda x:(len(x[1]),x[0]))
    skill_counts=Counter();pair_counts=Counter()
    for j in cohort:
        labels=sorted(skills[key(j)]);skill_counts.update(labels);pair_counts.update(combinations(labels,2))
    scenario={'population_definition':{'province':province,'category':'开发','education':'本科'},
              'selection_method':'Among bachelor/development provincial groups, select largest observed body population for a clear demonstration, not a market ranking',
              'denominator':len(cohort),'source_counts':dict(Counter(j['source'] for j in cohort)),
              'zero_skill_jobs':sum(not skills[key(j)] for j in cohort),
              'skills':skill_counts.most_common(12),'pairs':[[list(pair),n] for pair,n in pair_counts.most_common(10)],
              'experience_groups':dict(Counter(j['experience_group'] for j in cohort)),
              'jobs':[{'source':j['source'],'source_job_id':j['source_job_id'],'title':j['title_raw'],
                       'date_key':j['date_key'],'job_key':j['job_key']} for j in cohort]}
    record.update(source_direction_counts=by_source_direction,experience=[[list(k),v] for k,v in sorted(experience.items())],
                  skilled_jobs=sum(bool(skills[key(j)]) for j in body),combination_jobs=sum(len(skills[key(j)])>=2 for j in body),
                  zero_skill_jobs=len(body)-sum(bool(skills[key(j)]) for j in body),
                  coverage={s:sorted({j['coverage_status'] for j in jobs if j['source']==s}) for s in record['sources']},
                  province_only_job_count=len({key(r) for r in cities if r['mapping_status']=='province_only'}),
                  scenario=scenario,change_rows=changes)
    (out/'subject_analysis.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    lines=['# 四企业官网数字技术岗位需求分析','',f"固定sample发布{record['release_id']}；核查库`{record['database']}`。",
           '', '用途：为人才培训与就业指导提供岗位方向、技能模块及门槛适配线索。来源为腾讯、网易、小米、京东官方公开职位；这是选定官网和采样范围的观察，不能外推全国市场或企业实际招聘人数。',
           '', '## 范围与可比性','','| 来源 | 观察日期 | 来源岗位 | 核心岗位 | 有效正文 | 岗位技能对 | 覆盖 |','| --- | --- | --- | --- | --- | --- | --- |']
    for source,r in record['sources'].items():lines.append(f"| {source} | {', '.join(r['dates'])} | {r['source_postings']} | {r['core_postings']} | {r['body_denominator']} | {r['posting_skill_pairs']} | {', '.join(record['coverage'][source])} |")
    lines+=['','来源选择具有目的性：互联网/游戏、电商物流科技、智能终端企业均有涉及，但不是概率抽样。各来源公开列表和筛选方式不同，采集量上限及网络中断影响覆盖；优先比较来源内部结构与原文要求，不按来源岗位条数给企业需求规模排名。续采重放缓存沿用原观察时刻，不形成新的真实日期。',
            '', '## B01 岗位方向与来源结构','','| 来源 | 自动主方向 | 核心岗位 | 来源内占比 |','| --- | --- | --- | --- |']
    for source,groups in by_source_direction.items():
        den=record['sources'][source]['core_postings']
        for label,n in sorted(groups.items(),key=lambda r:-r[1]):lines.append(f'| {source} | {label} | {n} | {n/den:.1%} |')
    lines+=['','主方向按标题规则优先级互斥归属；大模型后端等可进入算法/AI，方向不能当作纯职业职能。核心范围为软件、数据、算法、软件测试与运维安全；纯硬件设计、制造、运营或项目管理不因所属企业而自动纳入。',
            '', '## B02 技能与组合训练','',f'全部有效正文分母{len(body)}岗，其中{record["zero_skill_jobs"]}岗零技能命中仍保留。至少命中一项技能{record["skilled_jobs"]}岗；至少含一项组合{record["combination_jobs"]}岗。覆盖衡量正文提及，不是录用概率，也不表示每项都是硬性门槛。',
            '', '| 技能 | 覆盖岗位 | 正文占比 |','| --- | --- | --- |']
    for label,n in record['top_skills']:lines.append(f'| {label} | {n} | {n/len(body):.1%} |')
    lines+=['','| 同时出现的技能组合 | 覆盖岗位 | 正文占比 |','| --- | --- | --- |']
    for pair,n in record['top_pairs']:lines.append(f"| {' + '.join(pair)} | {n} | {n/len(body):.1%} |")
    lines+=['','技能单选对应单项覆盖，多选对应任一命中的岗位并集；组合指标对应同时命中的交集，不能混用。城市和技能都是多值，合计按岗位集合去重，不能累计桥表展开行。',
            '', '## B03 学历经验与来源语义','','| 来源 | 学历组 | 核心岗位 |','| --- | --- | --- |']
    for (source,label),n in record['education']:lines.append(f'| {source} | {label} | {n} |')
    lines+=['','| 来源 | 经验组 | 核心岗位 |','| --- | --- | --- |']
    for (source,label),n in record['experience']:lines.append(f'| {source} | {label} | {n} |')
    lines+=['','有结构化门槛时保留来源并核对正文；缺失时仅从任职/补充字段明确表述派生。多个经验条件不同列待确认，偏好不提升硬性门槛；未知、不限与冲突独立保留。网易workType是全职/实习/派遣，小米type是社招/校招/实习/顶尖人才项目，京东本次是社会招聘入口，腾讯数字代码未释义；就业形式与渠道不作同义横比。',
            '',f'当前有{record["province_only_job_count"]}个岗位仅披露省级地点，归入相应省份且城市显示“城市未披露”；不制造城市，也不混成市级岗位规模。',
            '', '## 从分析到训练安排','',f'情境：为已有开发基础的本科背景学员选择训练模块。以“开发×本科”为预设筛选，选正文样本最多的{province}作为演示组；这用于展示方法，不表示该地区市场需求排名。分母{len(cohort)}岗，来源组成{scenario["source_counts"]}，零技能命中{scenario["zero_skill_jobs"]}岗仍在分母。',
            '', '| 技能或组合 | 覆盖 / 正文分母 | 占比 |','| --- | --- | --- |']
    for name,n in scenario['skills'][:5]:lines.append(f'| {name} | {n}/{len(cohort)} | {n/len(cohort):.1%} |')
    for pair,n in scenario['pairs'][:3]:lines.append(f"| {' + '.join(pair)} 同时命中 | {n}/{len(cohort)} | {n/len(cohort):.1%} |")
    first=skill_counts.most_common(1)[0]
    lines+=['',f'可先将{first[0]}列为训练候选（{first[1]}/{len(cohort)}），再结合已有基础和组合共现设计练习。实施前须逐岗核对经验、要求强度和原文，未注明或不限不能简单认定适配；不承诺课程就业效果。',
            '', '## B04 变化与验证','', '当前没有相邻完整四来源日基线，新增观察及内容变化为NULL。没有把旧100岗样本、网络续采或网页更新时间补成趋势。B01—B03的样本分析可以演示，B04只有真实数据条件成立才解释。',
            '', '结构人口、门槛人口、技能分子和分母已与日状态明细及去重技能集合独立对账。查询固定release_id；更改规则形成新发布，旧原始观察和历史发布保留。AI辅助审计和程序回放不冒充人工盲审准确率。']
    (ROOT/'reports/analysis/岗位需求主题分析.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return record
