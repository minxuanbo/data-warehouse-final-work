"""Pin the existing report to one published release, preserving its visual layouts."""
import argparse
import json
import os
import re
from scripts.prepare_powerbi import PROJECT,model,write_json,visual
from scripts.extend_powerbi import add_model
from scripts.powerbi_contract import fix_model,rename_visual_fields,validate_model
from warehouse.load import connect
from warehouse.release_build import records

LABELS={'calendar_year':'年','calendar_quarter':'季度','calendar_month':'月','calendar_date':'观察日',
 'province_name':'省份','city_name':'城市','category_group':'标准岗位类别','source_category_group':'来源原类别',
 'education_group':'学历分组','experience_group':'经验分组','employment_type_group':'招聘类型',
 'source_job_id':'来源岗位 ID','title_raw':'岗位名称','source_url':'来源链接','source':'来源',
 'education_basis_label':'学历依据','qualification_kind':'门槛类型','qualification_value':'规范结果',
 'resolution_status':'解析状态','evidence_field':'原文字段','evidence':'原文证据','strength':'要求强度'}


def polish_visuals(value,rid):
    if isinstance(value,str):return re.sub(r'固定(样本)?发布\s*\d+',lambda m:'固定'+(m[1] or '')+'发布 '+str(rid),value)
    if isinstance(value,list):return [polish_visuals(v,rid) for v in value]
    if not isinstance(value,dict):return value
    result={k:polish_visuals(v,rid) for k,v in value.items()}
    field=result.get('field',{}).get('Column',{})
    if field.get('Property') in LABELS:result['displayName']=LABELS[field['Property']]
    return result


def pin(database,server='lpc:localhost',release_id=None):
    os.environ['DW_DATABASE']=database;os.environ['DW_SERVER']=server
    c=connect()
    try:
        rid=release_id or c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()
        if not rid:raise ValueError('No published sample release')
        inputs=records(c,'''WITH chosen AS (
          SELECT i.*,s.source_code,ROW_NUMBER() OVER(PARTITION BY s.source_code ORDER BY date_key DESC,build_id DESC) n
          FROM audit.release_input i JOIN dim.source s ON s.source_key=i.source_key WHERE release_id=?)
          SELECT c.source_code as source,v.* FROM chosen c JOIN ads.cd_overview v ON v.build_id=c.build_id WHERE c.n=1 ORDER BY c.source_code''',rid)
        if len(inputs)!=2:raise ValueError('The pilot baseline requires both approved sources')
        if c.execute('SELECT COUNT(*) FROM ads.release_validation WHERE release_id=?',rid).fetchval():raise ValueError('Release not valid')
    finally:c.close()
    ids=[i['build_id'] for i in inputs]
    path=PROJECT/'Recruitment.SemanticModel/model.bim'
    document=json.loads(path.read_text(encoding='utf-8'))
    fresh={t['name']:t for t in model(ids,server,database,rid)['model']['tables']}
    for t in document['model']['tables']:
        if t['name'] in fresh:t['partitions']=fresh[t['name']]['partitions']
    write_json(path,fix_model(document))
    connection=f'driver={{ODBC Driver 18 for SQL Server}};server={server};database={database};encrypt=yes;trustservercertificate=yes;'
    queries=add_model(rid,ids,connection)
    for page in ('overview','skills','evidence'):
        for p in (PROJECT/f'Recruitment.Report/definition/pages/{page}').rglob('*.json'):
            old=json.loads(p.read_text(encoding='utf-8'));new=rename_visual_fields(old)
            if new!=old:write_json(p,new)
    page=PROJECT/'Recruitment.Report/definition/pages/dimensional/page.json'
    d=json.loads(page.read_text(encoding='utf-8'));d['displayName']='06 岗位需求多维分析';write_json(page,d)
    title=PROJECT/'Recruitment.Report/definition/pages/dimensional/visuals/dim_title/visual.json'
    # Only update literal text; preserve manually saved geometry and formatting.
    old=title.read_text(encoding='utf-8')
    title.write_text(old.replace('一致性维度｜层次钻取与旋转','岗位需求结构｜方向、地区与进入门槛'),encoding='utf-8')
    detail=PROJECT/'Recruitment.Report/definition/pages/snapshot_evidence/visuals'
    jobs_path=detail/'snapshot_jobs/visual.json'
    jobs=json.loads(jobs_path.read_text(encoding='utf-8'));jobs['position']['height']=170
    projections=jobs['visual']['query']['queryState']['Values']['projections']
    if not any(p.get('queryRef')=='SnapshotJobs.education_basis_label' for p in projections):
        projections.append({'field':{'Column':{'Expression':{'SourceRef':{'Entity':'SnapshotJobs'}},'Property':'education_basis_label'}},
            'queryRef':'SnapshotJobs.education_basis_label','nativeQueryRef':'education_basis_label','displayName':'学历依据'})
    write_json(jobs_path,jobs)
    audit=visual('qualification_evidence','tableEx',24,440,1382,140,{'Values':[
        ('QualificationEvidence',n,False) for n in ('qualification_kind','qualification_value','strength','evidence_field','evidence')]},
        '学历与经验依据：优先不等于必需；未注明不等于不限')
    audit['$schema']='https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json'
    write_json(detail/'qualification_evidence/visual.json',audit)
    skill_path=detail/'snapshot_evidence_rows/visual.json';skill=json.loads(skill_path.read_text(encoding='utf-8'))
    skill['position'].update(y=600,height=200);write_json(skill_path,skill)
    for p in (PROJECT/'Recruitment.Report/definition/pages').rglob('*.json'):
        old=json.loads(p.read_text(encoding='utf-8'));new=polish_visuals(old,rid)
        if new!=old:write_json(p,new)
    page_order=PROJECT/'Recruitment.Report/definition/pages/pages.json'
    order=json.loads(page_order.read_text(encoding='utf-8'));order['activePageName']='dimensional';write_json(page_order,order)
    write_json(PROJECT/'refresh_selection.json',{'database':database,'server':server,'builds':inputs,'qualification_release_id':rid})
    write_json(PROJECT/'release_selection.json',{'database':database,'release_id':rid,'build_ids':ids,'channel':'sample','queries':queries,
      'cd_scope':'latest selected input per source; historical pilot projection','note':'All queries pinned before refresh; no fact-to-fact/content relationship.'})
    return {'database':database,'release_id':rid,'build_ids':ids,**validate_model(json.loads(path.read_text(encoding='utf-8')))}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',default='recruitment_dw_dev_cd_v1');p.add_argument('--server',default='lpc:localhost');p.add_argument('--release-id',type=int)
    a=p.parse_args();print(json.dumps(pin(a.database,a.server,a.release_id),ensure_ascii=False,default=str))
