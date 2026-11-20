"""Read a pinned pilot release; export a decision case and pending category review evidence."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from itertools import combinations
import json
from pathlib import Path
import re
import os

from warehouse.load import ROOT,connect
from warehouse.release_build import records


def read_verified_files():
    from warehouse.integrate_analysis import prepare as verify_input
    from warehouse.normalization import VERSION,city,classify
    config=json.loads((ROOT/'warehouse/pipeline.json').read_text(encoding='utf-8'))
    jobs=[];places=[];labels=[]
    for item in config['inputs']:
        checked,_,_,evidence,enriched,_=verify_input(ROOT/item['batch_path'],ROOT/item['analysis_path'],ROOT/item['dictionary_path'])
        day=datetime.fromisoformat(checked['manifest']['finished_at'].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8)))
        assert len(enriched)==100 and sum(j['is_core'] for j in enriched)==98,'Fixed 100/98 pilot required'
        for j in enriched:
            conformed=classify(j);identity=j['source']+'|'+j['source_job_id'];dk=int(day.strftime('%Y%m%d'))
            jobs.append({**j,'job_key':identity,'date_key':dk,'category_group':conformed['category'],
                'education_group':conformed['education'],'experience_group':conformed['experience'],
                'body_valid':any((j.get(f) or '').strip() for f in ('description_raw','requirements_raw','additional_requirements_raw')),
                'content_json':j,'normalization_version':VERSION,'raw_ref':j.get('detail_ref')})
            locs=[None] if j['location_conflict'] else j['confirmed_locations'] or [None]
            for loc in locs:places.append({'date_key':dk,'job_key':identity,'province_name':city(loc,j['location_conflict'])['province']})
        skill_set={(r['source_job_id'],r['skill_name']) for r in evidence if r['is_core'] and r['eligible_for_metric']}
        assert len(skill_set)==config['pilot_expectations']['posting_skill_pairs'][checked['manifest']['source']]
        for identity,name in sorted(skill_set):labels.append({'date_key':int(day.strftime('%Y%m%d')),
            'job_key':checked['manifest']['source']+'|'+identity,'skill_name':name})
    return jobs,places,labels


def read_database(database,release_id):
    c=connect(database);c.timeout=30
    try:
        rid=release_id or c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()
        # Read the physical star and ODS separately: projecting large JSON through the
        # nested detail views can cause an unnecessarily expensive SQL Server plan.
        jobs=records(c,'''SELECT s.source_code source,p.source_job_id,f.job_key,f.date_key,
          cat.category_name category_group,ed.education_name education_group,ex.experience_name experience_group,
          f.is_core,f.body_valid,i.batch_id,b.normalization_version
          FROM dwd.fact_job_daily f JOIN dim.source s ON s.source_key=f.source_key
          JOIN dim.job j ON j.job_key=f.job_key JOIN dim.posting_identity p ON p.posting_key=j.posting_key
          JOIN dim.job_category cat ON cat.category_key=f.category_key
          JOIN dim.education ed ON ed.education_key=f.education_key
          JOIN dim.experience ex ON ex.experience_key=f.experience_key
          JOIN audit.release_input i ON i.release_id=f.release_id AND i.build_id=f.build_id
          JOIN audit.model_build b ON b.release_id=f.release_id AND b.status='ready'
          WHERE f.release_id=? AND EXISTS(SELECT 1 FROM audit.publication_history h WHERE h.release_id=f.release_id)''',rid)
        original=records(c,'''SELECT r.batch_id,r.source_job_id,r.payload FROM ods.posting_record r
          JOIN audit.release_input i ON i.batch_id=r.batch_id WHERE i.release_id=?''',rid)
        raw={(r['batch_id'],r['source_job_id']):json.loads(r['payload']) for r in original}
        enriched=records(c,'''SELECT o.batch_id,p.source_job_id,e.additional_requirements_raw
          FROM dwd.observation_enrichment e
          JOIN dwd.fact_posting_observation o ON o.observation_key=e.observation_key
          JOIN dim.posting_identity p ON p.posting_key=o.posting_key
          JOIN audit.release_input i ON i.build_id=e.build_id AND i.batch_id=o.batch_id
          WHERE i.release_id=?''',rid)
        additional={(r['batch_id'],r['source_job_id']):r['additional_requirements_raw'] for r in enriched}
        for job in jobs:
            identity=(job['batch_id'],job['source_job_id'])
            # Tencent ImportantItem belongs to the reviewed enrichment, not the collector payload.
            payload={**raw[identity],'additional_requirements_raw':additional[identity]}
            job.update(title_raw=payload['title_raw'],category_raw=payload.get('category_raw'),
                       source_url=payload['source_url'],raw_ref=payload.get('raw_refs'),content_json=payload)
        places=records(c,'''SELECT b.date_key,b.job_key,d.province_name FROM dwd.bridge_daily_city b
          JOIN dim.city d ON d.city_key=b.city_key WHERE b.release_id=?''',rid)
        labels=records(c,'''SELECT b.date_key,b.job_key,s.skill_name FROM dwd.bridge_daily_skill b
          JOIN dim.skill s ON s.skill_key=b.skill_key WHERE b.release_id=?''',rid)
    finally:c.close()
    return rid,jobs,places,labels


def prepare(database='recruitment_dw_dev_cd_v1',release_id=None,offline=False,output_dir=None):
    if offline:
        jobs,places,labels=read_verified_files();rid=release_id
    else:rid,jobs,places,labels=read_database(database,release_id)
    assert jobs and len({j['job_key'] for j in jobs})==len(jobs),'Pilot case requires one real observation per identity'
    provinces=defaultdict(set);skills=defaultdict(set)
    key=lambda row:(row['date_key'],row['job_key'])
    for row in places:provinces[key(row)].add(row['province_name'])
    for row in labels:skills[key(row)].add(row['skill_name'])
    regional=[j for j in jobs if j['is_core'] and j['category_group']=='开发' and '广东' in provinces[key(j)]]
    cohort=[j for j in regional if j['education_group']=='本科']
    body=[j for j in cohort if j['body_valid']]
    assert body,'No eligible body in the chosen training cohort'
    counts=Counter();pairs=Counter()
    for job in body:
        names=sorted(skills[key(job)]);counts.update(names);pairs.update(combinations(names,2))
    selected_ids={j['job_key'] for j in body}
    # Independently aggregate the same cohort from bridge rows, without joining both multi-value bridges.
    distinct_pairs={(r['job_key'],r['skill_name']) for r in labels if r['job_key'] in selected_ids}
    assert Counter(name for _,name in distinct_pairs)==counts
    stamp=datetime.now(timezone(timedelta(hours=8)));day=stamp.strftime('%Y%m%d')
    provenance='verified_repository_files' if offline else 'published_database_star'
    result={'checked_at':stamp.isoformat(),'database':None if offline else database,'reference_release_id':rid,
        'input_mode':provenance,'stage':'pilot_integration',
        'filters':{'province':'广东','category_group':'开发','education_group':'本科'},
        'regional_development_jobs':len(regional),'education_groups':dict(Counter(j['education_group'] for j in regional)),
        'cohort_jobs':len(cohort),'body_denominator':len(body),
        'top_skills':[[name,n,n/len(body)] for name,n in counts.most_common(8)],
        'top_pairs':[[list(names),n,n/len(body)] for names,n in pairs.most_common(5)],
        'experience_groups':dict(Counter(j['experience_group'] for j in cohort)),
        'zero_skill_jobs':sum(not skills[key(j)] for j in body),'checks':['one_observation_per_identity','independent_skill_set_count']}
    out=Path(output_dir) if output_dir else ROOT/'reports/verification';out.mkdir(parents=True,exist_ok=True)
    (out/f'小批决策案例对账_{day}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    lines=['# 广东开发方向的技能训练样本案例','',
        f'生成日期：{stamp:%Y-%m-%d}；参考 sample 发布 `{rid}`。当前为小批联调。',
        '本案例从仓库内固定批次、技能证据和当前规范化规则独立复算，输入哈希通过校验；本轮SQL新连接超时，未冒称重新查询数据库。' if offline else f'本案例只读查询数据库 `{database}` 的固定已发布星型。','',
        '规划情境：培训组织准备为已有开发基础的本科背景学员选择一个训练模块。先查看广东开发方向中明确标为“本科”的岗位线索，再比较技能与组合覆盖；这是设计使用情境，没有虚构企业访谈或培训效果。','',
        '## 先确定分析人群','',
        f'两个不同观察日的部分样本中，广东且自动主方向为“开发”的核心岗位共 {len(regional)} 个；学历分组为：'+
        '、'.join(f'{name}{n}岗' for name,n in result['education_groups'].items())+'。',
        f'其中明确“本科”组 {len(cohort)} 岗，有效正文分母 {len(body)}；零技能命中 {result["zero_skill_jobs"]} 岗仍保留分母。',
        '“本科”组仅用来限定披露一致的观察集合，不代表本科毕业生均符合岗位条件；不限、未注明、硕士及冲突组分别保留，也不能据此判断不适配。','',
        '## 技能与组合证据','','| 技能 | 覆盖岗位 / 正文分母 | 占比 |','| --- | --- | --- |']
    for name,n,share in result['top_skills']:lines.append(f'| {name} | {n}/{len(body)} | {share:.1%} |')
    lines+=['','| 同时具备的技能组合 | 覆盖岗位 / 正文分母 | 占比 |','| --- | --- | --- |']
    for names,n,share in result['top_pairs']:lines.append(f'| {" + ".join(names)} | {n}/{len(body)} | {share:.1%} |')
    top_skill,top_count,_=result['top_skills'][0]
    top_pair,pair_count,_=result['top_pairs'][0]
    lines+=['','## 据此选择训练内容','',
        f'本组可先把 {top_skill} 作为训练模块的候选，因其覆盖 {top_count}/{len(body)} 岗；再以 {" + ".join(top_pair)} 的共现任务设计组合练习，组合覆盖 {pair_count}/{len(body)} 岗。候选需结合讲师能力、学员基础和逐岗要求再决定，不将最高频直接等同于必须开设的课程。',
        '先让学员完成基础能力诊断，再选一项覆盖较多的技能进行小项目，组合练习用于已有相应基础的学员。必需、优先和明确提及均可能进入这里的覆盖指标，实施前应回查要求强度，不能把所有命中都解释成硬性门槛。',
        '经验组为：'+'、'.join(f'{name}{n}岗' for name,n in result['experience_groups'].items())+'。不把“1年以上”等开放区间当成“仅需1年”，也不据此自动判定应届生适配。','',
        '## 在 Power BI 中复核','',
        '第06页选择学历“本科”，在“技能训练线索”表展开“开发→广东”；查看技能岗位数、正文分母与占比。选单项技能看分子变化，多选取任一命中；本案例的技能组合取同时命中，不能拿多选并集代替。右键主方向钻取第07页，核对岗位与原文。',
        '第06页的其他地区和方向仍保留作对照，不把某个展开行误当成全页筛选。组合值由固定发布的岗位技能集合独立计算。','',
        '## 原文回查样例','','| 来源 | 岗位ID | 岗位名称 | 来源链接 |','| --- | --- | --- | --- |']
    for j in sorted(body,key=lambda j:(j['source'],j['source_job_id']))[:5]:
        lines.append(f'| {j["source"]} | {j["source_job_id"]} | {j["title_raw"].replace("|","/")} | [官网]({j["source_url"]}) |')
    lines+=['','本案例为两家企业不同观察日的partial小批描述；本轮以AI辅助规则和原文审计收口，未冒称独立人工金标。不能推断广东市场份额、岗位增长、录用概率或课程就业效果。',
        f'对账记录：[小批决策案例对账]({Path(os.path.relpath(out/f"小批决策案例对账_{day}.json",ROOT/"reports/analysis")).as_posix()})。']
    (ROOT/'reports/analysis/小批技能训练决策案例.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    candidates=[]
    for j in sorted(jobs,key=lambda j:(j['source'],j['source_job_id'])):
        title=j['title_raw']
        reason=None
        if j['category_group']=='算法/AI' and re.search(r'大模型|AI|AIGC',title,re.I) and re.search(r'开发|研发|存储|架构|infra|框架',title,re.I) and '算法' not in title:
            reason='AI领域与开发/基础设施职能交叉，需按主方向优先级复核'
        elif j['category_group']=='数据开发/分析' and '运维' in title:
            reason='数据领域与运维职能交叉，需按主方向优先级复核'
        if reason:
            payload=j['content_json']
            candidates.append({'source':j['source'],'source_job_id':j['source_job_id'],'batch_id':j['batch_id'],
                'release_id':rid,'title_raw':title,'category_raw':j['category_raw'],'automatic_primary_direction':j['category_group'],
                'normalization_version':j['normalization_version'],'reason':reason,'source_url':j['source_url'],'raw_ref':j['raw_ref'],
                'fields':{f:payload.get(f) for f in ('description_raw','requirements_raw','additional_requirements_raw')},
                'reviewer':None,'reviewed':False,'decision':None,'evidence':None})
    review=out/f'主方向边界待复核_{day}.jsonl'
    if review.exists():
        old=[json.loads(s) for s in review.read_text(encoding='utf-8').splitlines() if s]
        assert old==candidates,'Existing review packet differs; preserve any human work'
    else:review.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in candidates),encoding='utf-8',newline='\n')
    return {**result,'category_review_candidates':len(candidates)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',default='recruitment_dw_dev_cd_v1');p.add_argument('--release-id',type=int)
    p.add_argument('--offline',action='store_true',help='Recompute from hash-verified fixed repository inputs without SQL; release ID is a reference only')
    p.add_argument('--output-dir',type=Path)
    a=p.parse_args();r=prepare(a.database,a.release_id,a.offline,a.output_dir)
    print(json.dumps({k:r[k] for k in ('reference_release_id','input_mode','cohort_jobs','body_denominator','top_skills','category_review_candidates')},ensure_ascii=False))
