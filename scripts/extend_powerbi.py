"""Add verified release/KPI analysis to the existing PBIP without regenerating its four pages."""
import copy
import json
from pathlib import Path

from scripts.prepare_powerbi import PROJECT,ROOT,field,literal,textbox,visual,write_json
from warehouse.load import connect
from warehouse.release_build import records

PAGES=['quality_kpi','dimensional','snapshot_evidence']
EXTENSIONS=['QualityKpi','SnapshotSources','SnapshotJobs','SnapshotCityJobs','SnapshotSkillJobs','SnapshotSkills','SnapshotEvidence','Calendar','SnapshotDays','QualificationEvidence']


def make_table(name,query,columns,connection,description):
    q=lambda s:'"'+s.replace('"','""')+'"'
    table={'name':name,'description':description,'columns':[],
           'partitions':[{'name':name,'mode':'import','source':{'type':'m','expression':f'Odbc.Query({q(connection)}, {q(query)})'}}]}
    for col,dtype in columns:
        definition={'name':col,'dataType':dtype,'sourceColumn':col,'summarizeBy':'none'}
        if col in ('snapshot_key','job_key','date_key','build_id','release_id'):definition['isHidden']=True
        if dtype=='dateTime':definition['formatString']='yyyy-MM-dd'
        if col=='source_url':definition['dataCategory']='WebUrl'
        table['columns'].append(definition)
    return table


def add_model(release_id,build_ids,connection):
    path=PROJECT/'Recruitment.SemanticModel/model.bim'
    document=json.loads(path.read_text(encoding='utf-8'));m=document['model']
    ids=','.join(str(int(i)) for i in build_ids);rid=int(release_id)
    queries={
      'QualityKpi':f'SELECT * FROM ads.cd_quality_kpi WHERE build_id IN ({ids})',
      'SnapshotSources':f'SELECT DISTINCT source FROM ads.release_job_detail WHERE release_id={rid}',
      'SnapshotJobs':f"SELECT CONCAT(release_id,'|',date_key,'|',job_key) AS snapshot_key,* FROM ads.release_job_detail WHERE release_id={rid}",
      'SnapshotCityJobs':f'SELECT snapshot_key,city_name,province_name FROM ads.release_city_detail WHERE release_id={rid}',
      'SnapshotSkillJobs':f'SELECT snapshot_key,job_key,skill_name FROM ads.release_skill_detail WHERE release_id={rid}',
      'SnapshotSkills':f'SELECT DISTINCT skill_name FROM ads.release_skill_detail WHERE release_id={rid}',
      'SnapshotEvidence':f'SELECT * FROM ads.release_skill_evidence WHERE release_id={rid}',
      'Calendar':f'SELECT * FROM ads.release_calendar WHERE release_id={rid}',
      'SnapshotDays':f'SELECT * FROM ads.release_observed_change WHERE release_id={rid}',
      'QualificationEvidence':f'SELECT * FROM ads.release_qualification_evidence WHERE release_id={rid}'
    }
    columns={
      'QualityKpi':[(x,'string') for x in ('source','kpi_code','kpi_name','owner_role','trend_reason','target_version')]+
                   [(x,'int64') for x in ('build_id','numerator','denominator','status_value')]+[(x,'double') for x in ('kpi_value','goal_value')],
      'SnapshotSources':[('source','string')],
      'SnapshotJobs':[(x,'string') for x in ('snapshot_key','source','source_job_id','batch_id','title_raw','source_url','company_name',
          'category_group','education_group','education_basis_label','experience_group','employment_type_group','dataset_note')]+
          [(x,'int64') for x in ('release_id','date_key','job_key','build_id')]+[('analysis_date','dateTime'),('is_core','boolean'),('body_valid','boolean')],
      'SnapshotCityJobs':[(x,'string') for x in ('snapshot_key','city_name','province_name')],
      'SnapshotSkillJobs':[('snapshot_key','string'),('job_key','int64'),('skill_name','string')],
      'SnapshotSkills':[('skill_name','string')],
      'SnapshotEvidence':[(x,'string') for x in ('snapshot_key','skill_name','evidence_field','evidence','raw_ref','body_hash_version')]+
                         [('eligible_for_metric','boolean'),('evidence_start','int64'),('evidence_end','int64')],
      'Calendar':[(x,'int64') for x in ('date_key','calendar_year','calendar_quarter','calendar_month','calendar_day')]+[('calendar_date','dateTime')],
      'SnapshotDays':[(x,'int64') for x in ('release_id','date_key','source_posting_count','core_posting_count','skill_denominator',
          'expected_source_count','observed_source_count','complete_source_count','newly_observed_count','content_changed_count')]+
          [('is_complete','boolean'),('is_comparable','boolean'),('comparison_note','string')],
      'QualificationEvidence':[(x,'string') for x in ('snapshot_key','qualification_kind','qualification_value','resolution_status','evidence_field','evidence','strength','record_ref')]+
          [('evidence_start','int64'),('evidence_end','int64')],
    }
    descriptions={'QualityKpi':'每选定构建×质量KPI；构建级，不受岗位/城市切片影响。',
                  'SnapshotJobs':'每固定发布版本×批次结束日×来源身份；一致性维度分析切片，跨日总计按岗位去重。',
                  'Calendar':'连续北京时间分析日历；日期为批次结束日，不是岗位发布日期。'}
    tables=[make_table(n,queries[n],columns[n],connection,descriptions.get(n,'固定不可变发布版本的分析关联或属性表。')) for n in EXTENSIONS]
    for t in tables:
        if t['name'] in ('SnapshotCityJobs','SnapshotSkillJobs','SnapshotDays'):t['isHidden']=True
        if t['name']=='Calendar':
            t['dataCategory']='Time'
            next(c for c in t['columns'] if c['name']=='calendar_date')['isKey']=True
            t['hierarchies']=[{'name':'年季度月日','levels':[{'name':label,'ordinal':i,'column':col} for i,(label,col) in enumerate(
                [('年','calendar_year'),('季度','calendar_quarter'),('月','calendar_month'),('日','calendar_date')])]}]
        if t['name']=='SnapshotCityJobs':
            t['hierarchies']=[{'name':'省市','levels':[{'name':'省','ordinal':0,'column':'province_name'},{'name':'市','ordinal':1,'column':'city_name'}]}]
        if t['name']=='QualityKpi':
            expressions={
              'KPI分子':('IF(HASONEVALUE(QualityKpi[kpi_code]),SUM(QualityKpi[numerator]))','#,0'),
              'KPI分母':('IF(HASONEVALUE(QualityKpi[kpi_code]),SUM(QualityKpi[denominator]))','#,0'),
              'KPI实际值':('DIVIDE([KPI分子],[KPI分母])','0.0%'),
              'KPI目标值':('IF(HASONEVALUE(QualityKpi[kpi_code]),MAX(QualityKpi[goal_value]))','0.0%'),
              'KPI状态说明':('IF(NOT HASONEVALUE(QualityKpi[kpi_code]),BLANK(),IF(ISBLANK([KPI实际值]),"无分母",IF([KPI实际值]>=[KPI目标值],"达标","未达标")))',''),
              'KPI趋势说明':('IF(HASONEVALUE(QualityKpi[kpi_code]),"无可比日序列")',''),
            }
            t['measures']=[{'name':n,'expression':e,'formatString':fmt,'description':'项目运营验收条件；跨KPI不计算无意义总计。'} for n,(e,fmt) in expressions.items()]
        if t['name']=='SnapshotJobs':
            city='VAR K = VALUES(SnapshotCityJobs[snapshot_key]) RETURN '
            core='KEEPFILTERS(SnapshotJobs[is_core]=TRUE()), TREATAS(K,SnapshotJobs[snapshot_key])'
            body=core+', KEEPFILTERS(SnapshotJobs[body_valid]=TRUE())'
            expressions={
              '快照核心岗位数':(city+f'COALESCE(CALCULATE(DISTINCTCOUNT(SnapshotJobs[job_key]),{core}),0)','#,0'),
              '快照正文分母':(city+f'COALESCE(CALCULATE(DISTINCTCOUNT(SnapshotJobs[job_key]),{body}),0)','#,0'),
              '快照技能岗位数':(city+f'COALESCE(CALCULATE(DISTINCTCOUNT(SnapshotSkillJobs[job_key]),{body}),0)','#,0'),
              '快照技能占比':('DIVIDE([快照技能岗位数],[快照正文分母])','0.0%'),
              '可比新增观察数':('IF(HASONEVALUE(Calendar[date_key]),MAX(SnapshotDays[newly_observed_count]))','#,0'),
            }
            t['measures']=[{'name':n,'expression':e,'formatString':fmt,'description':'按当前筛选重算去重岗位集合；城市多值不可累加，技能选择保持正文分母。'} for n,(e,fmt) in expressions.items()]
    m['tables']=[t for t in m['tables'] if t['name'] not in EXTENSIONS]+tables
    m['relationships']=[r for r in m['relationships'] if not r['name'].startswith('Rectification_')]
    relations=[('QualityKpi','source','SnapshotSources','source'),('SnapshotJobs','source','SnapshotSources','source'),
               ('SnapshotJobs','date_key','Calendar','date_key'),('SnapshotDays','date_key','Calendar','date_key'),
               ('SnapshotCityJobs','snapshot_key','SnapshotJobs','snapshot_key'),('SnapshotSkillJobs','snapshot_key','SnapshotJobs','snapshot_key'),
               ('SnapshotEvidence','snapshot_key','SnapshotJobs','snapshot_key'),('SnapshotSkillJobs','skill_name','SnapshotSkills','skill_name')]
    for i,(ft,fc,tt,tc) in enumerate(relations):
        m['relationships'].append({'name':'Rectification_'+str(i),'fromTable':ft,'fromColumn':fc,'toTable':tt,'toColumn':tc,'crossFilteringBehavior':'oneDirection'})
    for a in m.get('annotations',[]):
        if a['name']=='PBI_QueryOrder':a['value']=json.dumps([t['name'] for t in m['tables']])
    from scripts.powerbi_contract import fix_model
    write_json(path,fix_model(document))
    return queries


def matrix(name,rows,columns,measures,x,y,w,h,title):
    roles={'Rows':rows,'Values':measures}
    if columns:roles['Columns']=columns
    v=visual(name,'pivotTable',x,y,w,h,roles,title)
    v['visual']['objects']={
      'columnHeaders':[{'properties':{'autoSizeColumnWidth':literal(True),'columnAdjustment':literal('growToFit'),'fontSize':literal(12),'wordWrap':literal(True)}}],
      'rowHeaders':[{'properties':{'fontSize':literal(12),'showExpandCollapseButtons':literal(True),'stepped':literal(True),'wordWrap':literal(True)}}],
      'values':[{'properties':{'fontSize':literal(12)}}],
      'grid':[{'properties':{'rowPadding':literal(5)}}]
    }
    if len(rows)>1:
        v['visual']['expansionStates']=[{'roles':['Rows'],'levels':[{'queryRefs':[f'{t}.{c}'],'isCollapsed':True,'identityKeys':[field(t,c)]} for t,c,_ in rows]}]
    return v


def slicer(name,table,col,x,y,w,title):
    v=copy.deepcopy(json.loads((PROJECT/'Recruitment.Report/definition/pages/overview/visuals/filter0/visual.json').read_text(encoding='utf-8')))
    v['name']=name;v['position'].update(x=x,y=y,width=w,height=94)
    v['visual']['query']['queryState']['Values']['projections']=[{'field':field(table,col),'queryRef':f'{table}.{col}','nativeQueryRef':col,'active':True,'displayName':title}]
    v['visual']['visualContainerObjects']['title'][0]['properties']['text']=literal(title)
    return v


def repair_skill_page(project=PROJECT):
    """Expose skill numerators beside their stable denominator without reverse filtering."""
    page=project/'Recruitment.Report/definition/pages/dimensional'
    metadata=json.loads((page/'page.json').read_text(encoding='utf-8'))
    metadata['height']=1160
    write_json(page/'page.json',metadata)
    rotated=page/'visuals/rotated/visual.json'
    existing=json.loads(rotated.read_text(encoding='utf-8'))
    existing['position'].update(y=850,height=220)
    write_json(rotated,existing)
    c=lambda t,n:(t,n,False)
    measures=[('SnapshotJobs',n,True) for n in ('快照核心岗位数','快照正文分母','快照技能岗位数','快照技能占比')]
    profile=matrix('skill_profile',[c('SnapshotJobs','category_group'),c('SnapshotCityJobs','province_name'),
                   c('SnapshotCityJobs','city_name')],[],measures,24,565,1382,260,
                   '技能训练线索｜按自动主方向→省→市展开；多选技能取任一命中岗位')
    profile['$schema']='https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json'
    write_json(page/'visuals/skill_profile/visual.json',profile)
    notes={
        'dim_note':('技能筛选作用于下方技能岗位数与占比；核心岗位数和正文分母保持当前人群。多选=任一命中，非同时具备；右键主方向可钻取07。',76,43),
        'dim_footer':('小批联调：两来源日期不同且均partial；自动主方向待业务复核。未选技能时计至少命中一项；多城市总计按岗位并集，不推导市场趋势。',1090,55),
    }
    for name,(text,y,height) in notes.items():
        path=page/f'visuals/{name}/visual.json'
        definition=json.loads(path.read_text(encoding='utf-8'))
        definition['position'].update(y=y,height=height)
        definition['visual']['objects']['general'][0]['properties']['paragraphs']=[{
            'textRuns':[{'value':text,'textStyle':{'fontSize':'14pt','fontFamily':'Segoe UI','color':'#123047'}}]}]
        write_json(path,definition)
    skill_path=page/'visuals/dim_skill/visual.json'
    skill=json.loads(skill_path.read_text(encoding='utf-8'))
    skill['visual']['visualContainerObjects']['title'][0]['properties']['text']=literal('技能（多选取并集）')
    write_json(skill_path,skill)
    for path in page.rglob('visual.json'):
        definition=json.loads(path.read_text(encoding='utf-8'))
        def label(value):
            if isinstance(value,dict):
                col=value.get('field',{}).get('Column',{})
                if col.get('Property')=='category_group':value['displayName']='自动主方向'
                for child in value.values():label(child)
            elif isinstance(value,list):
                for child in value:label(child)
        label(definition)
        write_json(path,definition)
    return {'page':'dimensional','skill_selection':'any_selected','measures':[m[1] for m in measures]}


def add_pages(release_id):
    report=PROJECT/'Recruitment.Report/definition/pages'
    page_meta=json.loads((report/'pages.json').read_text(encoding='utf-8'))
    page_meta['pageOrder']=[p for p in page_meta['pageOrder'] if p not in PAGES]+PAGES
    page_meta['activePageName']='quality_kpi';write_json(report/'pages.json',page_meta)
    c=lambda t,n:(t,n,False);mv=lambda t,n:(t,n,True)
    def save(name,label,visuals,extra=None):
        page={'$schema':'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json','name':name,'displayName':label,'displayOption':'FitToPage','height':900,'width':1440,**(extra or {})}
        write_json(report/name/'page.json',page)
        for v in visuals:
            # New files use the same current visual schema as the preserved report.
            v['$schema']='https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json'
            write_json(report/name/'visuals'/v['name']/'visual.json',v)
    save('quality_kpi','05 项目质量 KPI',[
      textbox('kpi_title','项目质量 KPI｜实际值、目标与状态',24,20,1100,54,24),
      textbox('kpi_note',f'固定样本发布 {release_id}；目标为项目验收条件。完整性未达标，允许看样本结构，不允许计算市场增减。',24,76,1382,50,15),
      slicer('kpi_source','SnapshotSources','source',24,134,300,'来源'),
      matrix('kpi_matrix',[c('QualityKpi','kpi_name')],[],[mv('QualityKpi',n) for n in ('KPI分子','KPI分母','KPI实际值','KPI目标值','KPI状态说明','KPI趋势说明')],24,255,1382,330,'构建集合级 KPI（不随岗位城市筛选改变）'),
      visual('kpi_owners','tableEx',24,620,1382,180,{'Values':[c('QualityKpi',n) for n in ('kpi_name','owner_role','target_version')]},'指标责任与验收条件版本'),
      textbox('kpi_footer','正文与溯源目标均为100%；批准范围遍历完成才达标。无同范围连续完整日序列，趋势留空，不画持平箭头。',24,823,1382,58,15)
    ])
    filters=[slicer('dim_source','SnapshotSources','source',24,123,214,'来源'),slicer('dim_date','Calendar','calendar_date',255,123,214,'批次结束日'),
      slicer('dim_education','SnapshotJobs','education_group',486,123,214,'统一学历'),slicer('dim_experience','SnapshotJobs','experience_group',717,123,214,'统一经验'),
      slicer('dim_employment','SnapshotJobs','employment_type_group',948,123,214,'招聘类型'),slicer('dim_skill','SnapshotSkills','skill_name',1179,123,227,'技能')]
    save('dimensional','06 岗位需求多维分析',[
      textbox('dim_title','岗位需求结构｜方向、地区与进入门槛',24,18,1150,55,24),
      textbox('dim_note','点击矩阵“+ / -”展开收起；右键岗位类别可钻取到07证据页。招聘类型原代码未核实，明确显示未释义。',24,76,1382,43,14),*filters,
      matrix('date_hierarchy',[c('Calendar',n) for n in ('calendar_year','calendar_quarter','calendar_month','calendar_date')],[c('SnapshotSources','source')],
        [mv('SnapshotJobs','快照核心岗位数')],24,244,652,290,'年 → 季度 → 月 → 日：各来源观察（不是趋势图）'),
      matrix('geo_hierarchy',[c('SnapshotCityJobs',n) for n in ('province_name','city_name')],[c('SnapshotJobs','category_group')],
        [mv('SnapshotJobs','快照核心岗位数')],700,244,706,290,'省 → 市：统一主类别岗位数'),
      matrix('rotated',[c('SnapshotJobs','category_group')],[c('SnapshotCityJobs',n) for n in ('province_name','city_name')],
        [mv('SnapshotJobs','快照核心岗位数')],24,565,1382,240,'旋转视图：与上表交换类别/地点的行列；总计按岗位去重'),
      textbox('dim_footer','当前两来源观察日不同且覆盖partial；日快照可查询，增长/关闭等市场趋势不可推断。多城市总计不是各行相加。',24,830,1382,55,15)
    ])
    filt='Filter5fe2b36f235e4c65acf21608'
    extra={'filterConfig':{'filters':[{'name':filt,'field':field('SnapshotJobs','category_group'),'type':'Categorical','howCreated':'Drillthrough'}]},
      'pageBinding':{'name':'Pod','type':'Drillthrough','parameters':[{'name':'Param_'+filt,'boundFilter':filt,'fieldExpr':field('SnapshotJobs','category_group')}]}}
    back=visual('snapshot_back','actionButton',1230,20,175,48,objects={
      'text':[{'properties':{'show':literal(True)}},{'properties':{'text':literal('返回分析页'),'fontSize':literal(14)},'selector':{'id':'default'}}]})
    back['visual']['visualContainerObjects']['visualLink']=[{'properties':{'show':literal(True),'type':literal('Back')}}]
    save('snapshot_evidence','07 快照岗位与证据',[
      textbox('snapshot_title','岗位证据｜从分析结果回到真实原文',24,18,1160,55,24),back,
      textbox('snapshot_note','从06右键岗位类别钻取，或直接按来源与岗位ID筛选。选择岗位行后，下面证据随之过滤；无效证据只作审计。',24,76,1382,45,14),
      slicer('snapshot_source','SnapshotSources','source',24,130,300,'来源'),slicer('snapshot_id','SnapshotJobs','source_job_id',345,130,400,'来源岗位 ID'),
      visual('snapshot_jobs','tableEx',24,250,1382,245,{'Values':[c('SnapshotJobs',n) for n in ('source','source_job_id','title_raw','category_group','education_group','experience_group','source_url')]},'固定快照的来源岗位（单击岗位行查看证据）'),
      visual('snapshot_evidence_rows','tableEx',24,530,1382,290,{'Values':[c('SnapshotEvidence',n) for n in ('skill_name','eligible_for_metric','evidence_field','evidence','evidence_start','evidence_end')]},'逐字证据与字符位置：保留否定/不确定项用于审计'),
      textbox('snapshot_footer',f'固定发布 {release_id}；原文由批次、相对文件路径、SHA-256与字符位置追溯；当前身份保守按来源区分，未声称跨源重复已全部归并。',24,833,1382,53,14)
    ],extra)
    repair_skill_page()


def main():
    for path,schema in [
      (PROJECT/'Recruitment.pbip','https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json'),
      (PROJECT/'Recruitment.Report/definition.pbir','https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json')]:
        definition=json.loads(path.read_text(encoding='utf-8'));definition['$schema']=schema;write_json(path,definition)
    for page in ('overview','skills','evidence'):
        path=PROJECT/f'Recruitment.Report/definition/pages/{page}/visuals/title/visual.json'
        title=json.loads(path.read_text(encoding='utf-8'))
        if title['position']['height']<54:title['position']['height']=54;write_json(path,title)
    selection=json.loads((PROJECT/'refresh_selection.json').read_text(encoding='utf-8'))
    c=connect(selection['database'])
    try:
        rid=c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()
        if rid is None:raise ValueError('Publish a validated sample release first')
        builds=[r[0] for r in c.execute('SELECT build_id FROM audit.release_input WHERE release_id=? ORDER BY build_id',rid)]
        assert c.execute('SELECT COUNT(*) FROM ads.release_validation WHERE release_id=?',rid).fetchval()==0
    finally:c.close()
    connection=f"driver={{ODBC Driver 18 for SQL Server}};server={selection['server']};database={selection['database']};encrypt=yes;trustservercertificate=yes;"
    queries=add_model(rid,builds,connection);add_pages(rid)
    write_json(PROJECT/'release_selection.json',{'release_id':rid,'build_ids':builds,'channel':'sample','queries':queries,'note':'All imports pinned; does not follow a moving pointer during refresh.'})
    print(json.dumps({'release_id':rid,'build_ids':builds,'added_tables':EXTENSIONS,'added_pages':PAGES},ensure_ascii=False))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair-skill-page',action='store_true',help='Patch the existing page only; no database connection or repinning')
    args=parser.parse_args()
    if args.repair_skill_page:print(json.dumps(repair_skill_page(),ensure_ascii=False))
    else:main()
