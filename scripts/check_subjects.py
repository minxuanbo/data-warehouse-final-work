"""Read-only population reconciliation and business analysis from a fixed real release."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
from itertools import combinations
import json
import os
from pathlib import Path

from warehouse.load import ROOT,connect
from warehouse.release_build import records


def check(database='recruitment_dw_dev_cd_v1',release_id=None,write_report=True,output_dir=None):
    c=connect(database);c.timeout=30
    try:
        rid=release_id or c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()
        jobs=records(c,'''SELECT source,source_job_id,job_key,date_key,category_group,education_group,
          experience_group,employment_type_group,is_core,body_valid,coverage_status,analysis_date,
          title_raw,category_raw FROM ads.release_job_detail WHERE release_id=?''',rid)
        rows=records(c,'''SELECT d.source,d.date_key,d.job_key,k.skill_name FROM ads.release_job_detail d
          JOIN dwd.bridge_daily_skill b ON b.release_id=d.release_id AND b.date_key=d.date_key AND b.job_key=d.job_key
          JOIN dim.skill k ON k.skill_key=b.skill_key WHERE d.release_id=?''',rid)
        actual_structure=records(c,'SELECT * FROM ads.release_job_structure WHERE release_id=?',rid)
        actual_skills=records(c,'SELECT * FROM ads.release_skill_profile WHERE release_id=?',rid)
        actual_entry=records(c,'SELECT * FROM ads.release_entry_profile WHERE release_id=?',rid)
        changes=records(c,'SELECT is_comparable,newly_observed_count,content_changed_count FROM ads.release_observed_change WHERE release_id=?',rid)
        assert c.execute('SELECT COUNT(*) FROM ads.release_validation WHERE release_id=?',rid).fetchval()==0
    finally:c.close()
    assert jobs,'No real published jobs'
    assert len({(j['date_key'],j['job_key']) for j in jobs})==len(jobs),'Snapshot grain repeated'
    skills=defaultdict(set)
    for r in rows:skills[(r['date_key'],r['job_key'])].add(r['skill_name'])
    structure=defaultdict(lambda:[0,0,0]);profile=Counter();entry=defaultdict(lambda:[0,0])
    sources=defaultdict(lambda:[0,0,0,0]);dates=defaultdict(set)
    core=[j for j in jobs if j['is_core']]
    for j in jobs:
        a=sources[j['source']];a[0]+=1;a[1]+=j['is_core'];a[2]+=j['is_core'] and j['body_valid']
        a[3]+=len(skills[(j['date_key'],j['job_key'])]);dates[j['source']].add(str(j['analysis_date']))
        if not j['is_core']:continue
        k=(j['date_key'],j['source'],j['category_group']);s=structure[k]
        s[0]+=1;s[1]+=j['body_valid'];s[2]+=bool(skills[(j['date_key'],j['job_key'])])
        e=entry[k+(j['education_group'],j['experience_group'],j['employment_type_group'])];e[0]+=1;e[1]+=j['body_valid']
        if j['body_valid']:
            for name in skills[(j['date_key'],j['job_key'])]:profile[k+(name,)]+=1
    assert { (r['date_key'],r['source'],r['category_group']):[r['core_posting_count'],r['skill_denominator'],r['skilled_posting_count']] for r in actual_structure}==dict(structure)
    assert {(r['date_key'],r['source'],r['category_group'],r['skill_name']):r['posting_count'] for r in actual_skills}==dict(profile)
    for r in actual_skills:assert r['skill_denominator']==structure[(r['date_key'],r['source'],r['category_group'])][1]
    assert {(r['date_key'],r['source'],r['category_group'],r['education_group'],r['experience_group'],r['employment_type_group']):[r['core_posting_count'],r['skill_denominator']] for r in actual_entry}==dict(entry)
    if all(j['coverage_status']=='partial' for j in jobs):
        assert all(not x['is_comparable'] and x['newly_observed_count'] is None and x['content_changed_count'] is None for x in changes)
    by_category=Counter(j['category_group'] for j in core)
    skill_counts=Counter();pair_counts=Counter();education=Counter();experience=Counter()
    for j in core:
        education[(j['source'],j['education_group'])]+=1;experience[(j['source'],j['experience_group'])]+=1
        if j['body_valid']:
            labels=sorted(skills[(j['date_key'],j['job_key'])]);skill_counts.update(labels);pair_counts.update(combinations(labels,2))
    # Current result is a union of the two pilots, not a common-day market snapshot.
    single_per_identity=len({j['job_key'] for j in jobs})==len(jobs)
    assert single_per_identity,'This pilot narrative must not silently accumulate repeated days'
    record={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'status':'passed','database':database,'release_id':rid,
      'checks':['snapshot_grain','structure_population','entry_population','skill_numerator','skill_denominator','partial_change_gate'],
      'sources':{k:{'source_postings':v[0],'core_postings':v[1],'body_denominator':v[2],'posting_skill_pairs':v[3],'dates':sorted(dates[k])} for k,v in sources.items()},
      'standard_category_counts':dict(by_category),'top_skills':skill_counts.most_common(10),
      'top_pairs':[[list(k),v] for k,v in pair_counts.most_common(10)],
      'education':[[list(k),v] for k,v in sorted(education.items())],
      'note':'Category mapping is automatic initial classification; no human-review accuracy claim.'}
    if write_report and len(sources)>2:
        from scripts.analyze_expansion import write
        return write(record,jobs,skills,output_dir)
    if write_report:
        stamp=datetime.now(timezone(timedelta(hours=8)));day=stamp.strftime('%Y%m%d')
        folder=Path(output_dir) if output_dir else ROOT/'reports/verification'
        folder.mkdir(parents=True,exist_ok=True)
        out=folder/f'主题分析对账_{day}.json';out.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
        denominator=sum(j['body_valid'] for j in core)
        lines=['# 公开数字技术岗位需求主题分析','',f'核查日期：{stamp:%Y-%m-%d}；数据库 `{database}`，固定发布 `{rid}`。',
          '', '**用途：支持人才培训与就业指导的岗位方向、技能训练和门槛适配规划。以下为两来源不同观察日的 partial 小批描述，不是同日全量比较或市场调查。**',
          '', '## 数据范围','', '| 来源 | 观察日期 | 来源岗位 | 核心岗位 | 正文分母 | 岗位×技能 |', '| --- | --- | --- | --- | --- | --- |']
        for source,s in record['sources'].items():lines.append(f"| {source} | {', '.join(s['dates'])} | {s['source_postings']} | {s['core_postings']} | {s['body_denominator']} | {s['posting_skill_pairs']} |")
        lines+=['','## B01 岗位方向结构','','| 标准方向 | 核心样本岗位 | 占核心样本 |','| --- | --- | --- |']
        for name,count in by_category.most_common():lines.append(f'| {name} | {count} | {count/len(core):.1%} |')
        name,count=by_category.most_common(1)[0]
        lines += ['',f'在本批 {len(core)} 个核心来源岗位中，“{name}”为最大的自动分类方向（{count} 岗）。规划人员可据此优先查看该方向的技能和门槛，再按学员适配程度选择训练；不能把企业样本组成推成全国需求排名。',
          '', '分类按标题职业特征和源宽类别回退，保留源类别与规范化版本；该分布不代表人工分类准确率。',
          '', '## B02 技能与组合需求','',f'统一正文分母为 {denominator} 岗；未命中技能的有效正文仍在分母。技能占比反映文本覆盖，不是录用概率。',
          '', '| 技能 | 覆盖岗位 | 占正文分母 |','| --- | --- | --- |']
        for skill,count in skill_counts.most_common(8):lines.append(f'| {skill} | {count} | {count/denominator:.1%} |')
        lines+=['','| 技能组合 | 同时覆盖岗位 | 占正文分母 |','| --- | --- | --- |']
        for pair,count in pair_counts.most_common(5):lines.append(f"| {' + '.join(pair)} | {count} | {count/denominator:.1%} |")
        lines+=['','训练决策应先限定岗位方向和门槛，再看技能组合；不能只凭总体高频技能要求全部学员学习同一套内容。技能“优先”和“必需”保留不同语义，指标含明确提及，不等于每项都是招聘硬性要求。',
          '', '### 标准方向内的训练线索','','| 标准方向 | 正文岗位 | 该方向最常见技能 | 覆盖 / 分母 |','| --- | --- | --- | --- |']
        for cat in by_category:
            selected=[j for j in core if j['category_group']==cat and j['body_valid']];cnt=Counter()
            for j in selected:cnt.update(skills[(j['date_key'],j['job_key'])])
            skill,n=cnt.most_common(1)[0] if cnt else ('无有效技能',0)
            lines.append(f'| {cat} | {len(selected)} | {skill} | {n}/{len(selected)} |')
        lines+=['','## B03 岗位门槛与数据可用性','','| 来源 | 学历组 | 核心岗位 |','| --- | --- | --- |']
        for (source,label),count in sorted(education.items()):lines.append(f'| {source} | {label} | {count} |')
        lines+=['','学历优先保留结构化来源语义，来源缺失时从任职/补充要求提取明确的最低学历，并保存证据。未注明不等于不限；仅有“硕士优先”不提升硬性门槛；来源与正文不一致时单列冲突。两来源的采样与字段披露方式不同，不据此推导市场整体学历高低。经验将“三年以上工作经验”等忠实规范为“3年以上”，原区间不伪装成更细区间。',
          '', '网易workType已由官网公开前端核实为0全职、1实习、2派遣；腾讯数字代码保留未释义。就业形式不等于社招/校招渠道，不据此形成两来源招录渠道对比。',
          '', '## B04 观察变化','','当前两日各缺一个来源且均为 partial，因此新增观察、持续未观察与内容变化不发布比较结论。日期层次展开只用于定位观察，不代表已有市场趋势。',
          '', '## 指标与证据追踪','','B01：`ads.release_job_structure`；B02：`ads.release_skill_profile`、技能/原文证据；B03：`ads.release_entry_profile`。查询均须固定 release_id。上述三个主题接口已与日明细及去重技能集合独立聚合对账，原始输入、提取规则和版本可回查。',
          '', f'[对账记录]({Path(os.path.relpath(out,ROOT/"reports/analysis")).as_posix()}) · [分析设计](../../docs/design/07_多维分析与可视化.md)',
          '', '本报告由真实发布数据生成。无虚构薪资、录用、招聘人数或历史观察；自动分类和技能规则存在误差，额外人工复核未完成时不声称已满足最终人工精确率/召回率验收。']
        (ROOT/'reports/analysis/岗位需求主题分析.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    return record


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',default='recruitment_dw_dev_cd_v1');p.add_argument('--release-id',type=int);p.add_argument('--output-dir',type=Path);a=p.parse_args()
    r=check(a.database,a.release_id,output_dir=a.output_dir);print(json.dumps({k:r[k] for k in ('status','database','release_id','sources','standard_category_counts')},ensure_ascii=False))
