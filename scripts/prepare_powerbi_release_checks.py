"""Independent raw-file acceptance for the current release and its new DAX measures."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path

from scripts.analysis_inputs import input_paths
from scripts.prepare_powerbi import ROOT,write_json
from warehouse.integrate_analysis import prepare
from warehouse.normalization import classify,city


def main(output_path=None):
    original=json.loads((ROOT/'reports/analysis/powerbi_dax_cases.json').read_text(encoding='utf-8'))
    cases=json.loads(json.dumps(original['cases']));jobs=[];skills={}
    for case in cases:
        case['dax']=case['dax'].replace('Jobs[category_group]','Jobs[source_category_group]')
    for source,batch,analysis,dictionary in input_paths():
        checked,_,_,evidence,enriched,_=prepare(batch,analysis,dictionary)
        ended=datetime.fromisoformat(checked['manifest']['finished_at'].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8)))
        for j in enriched:
            places=[city(None,True)] if j['location_conflict'] else [city(x) for x in j['confirmed_locations'] or [None]]
            jobs.append({**j,**classify(j),'key':source+'|'+j['source_job_id'],'date_key':int(ended.strftime('%Y%m%d')),
                         'provinces':{x['province'] for x in places},'cities':{x['name'] for x in places}})
        for r in evidence:
            if r['is_core'] and r['eligible_for_metric']:skills.setdefault(source+'|'+r['source_job_id'],set()).add(r['skill_name'])
    def literal(v):return str(v) if isinstance(v,int) else '"'+v.replace('"','""')+'"'
    def add(name,source=None,day=None,province=None,category=None,skill=None,education=None,employment=None):
        selected=[j for j in jobs if j['is_core'] and (source is None or j['source']==source)
          and (day is None or j['date_key']==day) and (province is None or province in j['provinces'])
          and (category is None or j['category']==category) and (education is None or j['education']==education)
          and (employment is None or j['employment_type']==employment)]
        body=[j for j in selected if any((j.get(f) or '').strip() for f in ('description_raw','requirements_raw','additional_requirements_raw'))]
        selected_skills=None if skill is None else ({skill} if isinstance(skill,str) else set(skill))
        n=sum(bool(skills.get(j['key'],set()) if selected_skills is None else skills.get(j['key'],set())&selected_skills) for j in body)
        expected={'core':len({j['key'] for j in selected}),'denominator':len({j['key'] for j in body}),
                  'skilled':n,'share':n/len(body) if body else None,'newly_observed':None}
        filters=[]
        for t,c,v in [('SnapshotSources','source',source),('Calendar','date_key',day),('SnapshotCityJobs','province_name',province),
                      ('SnapshotJobs','category_group',category),('SnapshotSkills','skill_name',skill),('SnapshotJobs','education_group',education),
                      ('SnapshotJobs','employment_type_group',employment)]:
            if v is not None:
                values=[v] if isinstance(v,(str,int)) else v
                filters.append(f"TREATAS({{{','.join(literal(x) for x in values)}}},'{t}'[{c}])")
        expression='ROW("core",[快照核心岗位数],"denominator",[快照正文分母],"skilled",[快照技能岗位数],"share",[快照技能占比],"newly_observed",[可比新增观察数])'
        cases.append({'name':'release_'+name,'dax':'EVALUATE '+('CALCULATETABLE('+expression+','+','.join(filters)+')' if filters else expression),'expected':expected})
    add('all')
    for source in ('tencent','netease'):add(source,source=source)
    for day in sorted({j['date_key'] for j in jobs}):add('day_'+str(day),day=day)
    for group in sorted({j['category'] for j in jobs if j['is_core']}):add('category_'+group,category=group)
    for group in sorted(set.union(*(j['provinces'] for j in jobs))):add('province_'+group,province=group)
    for edu in sorted({j['education'] for j in jobs}):add('education_'+edu,education=edu)
    add('Python_denominator_kept',skill='Python');add('province_Python',province='广东',skill='Python');add('empty',province='不存在')
    add('Python_or_cpp_union',skill=['Python','C++'])
    add('development_Python',category='开发',skill='Python')
    add('bachelor_Python',education='本科',skill='Python')
    add('no_matching_skill',skill='不存在的技能')
    add('training_cohort',province='广东',category='开发',education='本科')
    add('training_cohort_cpp',province='广东',category='开发',education='本科',skill='C++')
    add('netease_fulltime',source='netease',employment='全职')
    add('netease_internship',source='netease',employment='实习')
    add('tencent_unverified_type',source='tencent',employment='来源代码未释义')
    for source in (None,'tencent','netease'):
        groups=[j for j in jobs if source is None or j['source']==source]
        for code,den,num in [('core_body_coverage',sum(j['is_core'] for j in groups),sum(j['is_core'] for j in groups)),
                             ('raw_traceability',len(groups),len(groups)),('collection_scope_complete',2 if source is None else 1,0)]:
            filters=[f'TREATAS({{"{code}"}},QualityKpi[kpi_code])']
            if source:filters.append(f'TREATAS({{"{source}"}},SnapshotSources[source])')
            cases.append({'name':'quality_'+str(source)+'_'+code,'dax':'EVALUATE CALCULATETABLE(ROW("numerator",[KPI分子],"denominator",[KPI分母],"value",[KPI实际值],"goal",[KPI目标值],"status",[KPI状态说明]),'+','.join(filters)+')',
                          'expected':{'numerator':num,'denominator':den,'value':num/den,'goal':1,'status':'达标' if num==den else '未达标'}})
    target=Path(output_path) if output_path else ROOT/'reports/verification/powerbi_release_cases_20261118.json'
    write_json(target,{'builds':original['builds'],'input':'fixed raw source + independent Python sets; current 200-posting acceptance; skill multi-select is union','cases':cases})
    print(json.dumps({'cases':len(cases),'new_cases':len(cases)-len(original['cases'])}))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path)
    main(p.parse_args().output)
