"""Build DAX acceptance cases independently from fixed source files and C policy."""
import json
from collections import defaultdict

from scripts.check_skills_v11 import input_paths
from scripts.prepare_powerbi import PROJECT, ROOT, write_json
from warehouse.integrate_analysis import prepare


def main():
    jobs=[]
    skills=defaultdict(set)
    evidence=[]
    for source,batch,analysis,dictionary in input_paths():
        _,_,_,rows,enriched,_=prepare(batch,analysis,dictionary)
        for j in enriched:
            j={**j,'job_key':source+'|'+j['source_job_id']}
            j['city']=set(['冲突待确认'] if j['location_conflict'] else [c.removesuffix('市') for c in j['confirmed_locations']] or ['未知'])
            j['experience_group']='冲突待确认' if j['experience_conflict'] else j['experience_raw'] or '未知'
            j['education_group']='冲突待确认' if j['education_conflict'] else j['education_raw'] or '未知'
            j['category_group']=j['category_raw'] or '未知'
            j['body_valid']=any(j.get(k) for k in ('description_raw','requirements_raw','additional_requirements_raw'))
            jobs.append(j)
        for r in rows:
            r={**r,'job_key':source+'|'+r['source_job_id']}
            evidence.append(r)
            if r['is_core'] and r['eligible_for_metric']: skills[r['job_key']].add(r['skill_name'])
    cases=[]
    def add(name,source=None,cities=None,experience=None,education=None,category=None,skill=None,job_id=None,pair=None):
        group=[j for j in jobs if (source is None or j['source']==source)
               and (cities is None or j['city'].intersection(cities))
               and (experience is None or j['experience_group']==experience)
               and (education is None or j['education_group']==education)
               and (category is None or j['category_group']==category)
               and (job_id is None or j['source_job_id']==job_id)]
        core=[j for j in group if j['is_core']]
        body=[j for j in core if j['body_valid']]
        bodykeys={j['job_key'] for j in body}
        counts=[len(skills[j['job_key']] if skill is None else skills[j['job_key']].intersection({skill})) for j in body]
        denom=len(body)
        expected={'core':len(core),'denominator':denom,'job_skill_pairs':sum(counts),
                  'skilled_jobs':sum(x>0 for x in counts),'skill_share':sum(x>0 for x in counts)/denom if denom else None,
                  'eligible_evidence':sum(r['job_key'] in bodykeys and r['eligible_for_metric'] and (skill is None or r['skill_name']==skill) for r in evidence),
                  'combination_jobs':sum(len(skills[j['job_key']])>=2 if pair is None else set(pair).issubset(skills[j['job_key']]) for j in body)}
        filters=[]
        def filt(table,col,values):
            literal=','.join('"'+v.replace('"','""')+'"' for v in values)
            filters.append(f'TREATAS({{{literal}}}, {table}[{col}])')
        for t,c,v in [('Builds','source',source),('Jobs','experience_group',experience),
                      ('Jobs','education_group',education),('Jobs','category_group',category),
                      ('Skills','skill_name',skill),('Jobs','source_job_id',job_id)]:
            if v is not None: filt(t,c,[v])
        if cities is not None: filt('CityJobs','city',cities)
        if pair is not None: filt('Pairs','pair_label',[' + '.join(sorted(pair))])
        expr='ROW("core",[核心岗位数],"denominator",[正文分母],"job_skill_pairs",[岗位技能对数],"skilled_jobs",[技能岗位数],"skill_share",[技能出现占比],"eligible_evidence",[有效证据数],"combination_jobs",[组合岗位数])'
        dax='EVALUATE '+('CALCULATETABLE('+expr+','+','.join(filters)+')' if filters else expr)
        cases.append({'name':name,'dax':dax,'expected':expected})
    add('all_sources')
    for source in ('tencent','netease'):
        add(source,source)
        source_jobs=[j for j in jobs if j['source']==source and j['is_core']]
        for city in sorted(set.union(*(j['city'] for j in source_jobs))):
            add(source+'_city_'+city,source,cities=[city])
        for exp in sorted({j['experience_group'] for j in source_jobs}):
            add(source+'_experience_'+exp,source,experience=exp)
        for edu in sorted({j['education_group'] for j in source_jobs}):
            add(source+'_education_'+edu,source,education=edu)
        add(source+'_Python_denominator',source,skill='Python')
        add(source+'_city_Python',source,cities=['深圳' if source=='tencent' else '杭州'],skill='Python')
        add(source+'_Python_SQL_pair',source,pair=['Python','SQL'])
        add(source+'_city_pair',source,cities=['深圳' if source=='tencent' else '杭州'],pair=['Python','SQL'])
        add(source+'_city_experience_category',source,cities=list(source_jobs[0]['city']),
            experience=source_jobs[0]['experience_group'],category=source_jobs[0]['category_group'])
        no_match=next(j for j in source_jobs if not skills[j['job_key']])
        add(source+'_no_match_body_kept',source,job_id=no_match['source_job_id'])
        extension=next(j for j in jobs if j['source']==source and not j['is_core'])
        add(source+'_extension_excluded',source,job_id=extension['source_job_id'])
    add('tencent_multi_city_union','tencent',cities=['北京','深圳'])
    add('netease_hint_not_conflict','netease',experience='不限',job_id='78729')
    add('empty_selection',cities=['不存在的城市'])
    selection=json.loads((PROJECT/'refresh_selection.json').read_text(encoding='utf-8'))
    output=ROOT/'reports/analysis/powerbi_dax_cases.json'
    write_json(output,{'input':'fixed source + C scope policy; no SQL aggregates used',
                       'builds':selection['builds'],'cases':cases})
    print(json.dumps({'cases':len(cases),'output':str(output)},ensure_ascii=False))


if __name__=='__main__': main()
