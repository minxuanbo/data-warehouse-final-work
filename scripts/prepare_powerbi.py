"""Generate the Git-friendly Power BI pilot project from reconciled ADS builds.

Run with DW_DATABASE=recruitment_dw_dev_cd_v1. Only SELECT is issued to SQL.
Close the project in Desktop before regenerating it; local cache is not versioned.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from warehouse.load import connect

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'dashboards/powerbi'
SCHEMA = 'https://developer.microsoft.com/json-schemas/fabric/item'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def sql_queries(ids):
    """Every query pins the same immutable build IDs, never a moving pointer."""
    selected = ','.join(str(int(x)) for x in ids)
    jobs = f"SELECT * FROM ads.cd_job_detail WHERE build_id IN ({selected})"
    key = "CONCAT(j.build_id,'|',j.source_job_id)"
    eligible = f"""SELECT DISTINCT CONCAT(build_id,'|',source_job_id) AS job_key, skill_name
      FROM ads.cd_skill_evidence
      WHERE build_id IN ({selected}) AND is_core=1 AND eligible_for_metric=1"""
    return {
        'Builds': f"SELECT * FROM ads.current_analysis_builds WHERE build_id IN ({selected})",
        'Jobs': f"""SELECT {key} AS job_key,j.build_id,j.source,j.batch_id,j.source_job_id,j.title_raw,
          CAST(j.analysis_date AS date) AS analysis_date,
          COALESCE(NULLIF(j.category_raw,N''),N'未知') AS category_group,
          CASE WHEN j.experience_conflict=1 THEN N'冲突待确认' ELSE COALESCE(NULLIF(j.experience_raw,N''),N'未知') END AS experience_group,
          CASE WHEN j.education_conflict=1 THEN N'冲突待确认' ELSE COALESCE(NULLIF(j.education_raw,N''),N'未知') END AS education_group,
          j.is_core,j.body_valid,j.location_conflict,j.experience_conflict,j.education_conflict,
          j.experience_hint,j.source_url,j.scope_reason,j.content_json,j.additional_requirements_raw,
          j.issues_json,j.raw_ref,j.raw_sha256,j.body_hash_version,j.skill_text_scope
          FROM ({jobs}) j""",
        'CityJobs': f"""SELECT DISTINCT {key} AS job_key,
          CASE WHEN j.location_conflict=1 THEN N'冲突待确认'
            WHEN RIGHT(loc.value,1)=N'市' THEN LEFT(loc.value,LEN(loc.value)-1)
            ELSE COALESCE(NULLIF(loc.value,N''),N'未知') END AS city
          FROM ({jobs}) j OUTER APPLY OPENJSON(j.confirmed_locations_json) loc""",
        'SkillJobs': eligible,
        'Skills': f"SELECT DISTINCT skill_name FROM ads.cd_skill_evidence WHERE build_id IN ({selected})",
        # Pair expansion runs locally in Power Query, avoiding a costly doubled
        # expansion of the layered ADS views in SQL Server's query optimizer.
        'Pairs': eligible,
        'Evidence': f"""SELECT CONCAT(e.build_id,'|',e.source_job_id) AS job_key,e.skill_name,
          e.requirement_level,e.eligible_for_metric,e.is_core,x.*
          FROM ads.cd_skill_evidence e CROSS APPLY OPENJSON(e.evidence_json)
          WITH(evidence_field nvarchar(100), evidence nvarchar(max), evidence_start int,evidence_end int,
            match_start int,match_end int,matched_text nvarchar(300),raw_ref nvarchar(1000),
            raw_sha256 nvarchar(64),raw_field_name nvarchar(100),body_sha256 nvarchar(64),
            body_hash_version nvarchar(100),dictionary_version nvarchar(100),rule_version nvarchar(100)) x
          WHERE e.build_id IN ({selected})""",
    }


# An explicit schema prevents numeric coercion of long source IDs in Power BI.
TABLE_COLUMNS = {
    'Builds': [('source','string'),('batch_id','string'),('build_id','int64'),('skill_denominator','int64'),
               ('body_hash_version','string'),('skill_text_scope','string'),('dictionary_version','string'),
               ('rule_version','string'),('scope_version','string')],
    'Jobs': [(x,'string') for x in ('job_key','source','batch_id','source_job_id','title_raw','category_group',
             'experience_group','education_group','source_url','scope_reason','content_json',
             'additional_requirements_raw','issues_json','raw_ref','raw_sha256','body_hash_version','skill_text_scope')]
             + [('build_id','int64'),('analysis_date','dateTime')]
             + [(x,'boolean') for x in ('is_core','body_valid','location_conflict','experience_conflict',
                                        'education_conflict','experience_hint')],
    'CityJobs': [('job_key','string'),('city','string')],
    'SkillJobs': [('job_key','string'),('skill_name','string')],
    'Skills': [('skill_name','string')],
    'Pairs': [(x,'string') for x in ('job_key','skill_a','skill_b','pair_label')],
    'Evidence': [(x,'string') for x in ('job_key','skill_name','requirement_level','evidence_field','evidence',
             'matched_text','raw_ref','raw_sha256','raw_field_name','body_sha256','body_hash_version',
             'dictionary_version','rule_version')]
             + [(x,'int64') for x in ('evidence_start','evidence_end','match_start','match_end')]
             + [('eligible_for_metric','boolean'),('is_core','boolean')],
}


def measures():
    # CityJobs only receives Jobs filters; city filters return to Jobs explicitly
    # through TREATAS. Skills never filters Jobs, preserving the denominator.
    city = 'VAR K = VALUES(CityJobs[job_key]) RETURN '
    core = 'KEEPFILTERS(Jobs[is_core] = TRUE()), TREATAS(K, Jobs[job_key])'
    body = core + ', KEEPFILTERS(Jobs[body_valid] = TRUE())'
    values = {
        '核心岗位数': city + f'COALESCE(CALCULATE(DISTINCTCOUNT(Jobs[job_key]), {core}),0)',
        '正文分母': city + f'COALESCE(CALCULATE(DISTINCTCOUNT(Jobs[job_key]), {body}),0)',
        '正文覆盖率': 'DIVIDE([正文分母],[核心岗位数])',
        '技能岗位数': city + f'COALESCE(CALCULATE(DISTINCTCOUNT(SkillJobs[job_key]), {body}),0)',
        '岗位技能对数': city + f'COALESCE(CALCULATE(COUNTROWS(SkillJobs), {body}),0)',
        '技能出现占比': 'DIVIDE([技能岗位数],[正文分母])',
        '组合岗位数': city + f'COALESCE(CALCULATE(DISTINCTCOUNT(Pairs[job_key]), {body}),0)',
        '组合出现占比': 'DIVIDE([组合岗位数],[正文分母])',
        '有效证据数': city + f'COALESCE(CALCULATE(COUNTROWS(Evidence), {body}, KEEPFILTERS(Evidence[eligible_for_metric]=TRUE())),0)',
        '审计证据数': city + 'COALESCE(CALCULATE(COUNTROWS(Evidence), TREATAS(K, Jobs[job_key])),0)',
        '本岗核心指标资格': 'IF(SELECTEDVALUE(Jobs[is_core],FALSE()),"核心","扩展")',
        '样本说明': '"两来源 partial 小批；观察日期不同；来源岗位计数；不用于全市场或趋势推断"',
    }
    return [{'name': name, 'expression': expr, 'formatString': '0.0%' if '率' in name or '占比' in name else '#,0'}
            if name not in ('样本说明','本岗核心指标资格') else {'name':name,'expression':expr}
            for name,expr in values.items()]


def model(ids, server, database):
    connection = (f'driver={{ODBC Driver 18 for SQL Server}};server={server};database={database};'
                  'encrypt=yes;trustservercertificate=yes;')
    tables = []
    for name, query in sql_queries(ids).items():
        # M literals escape quotes by doubling them, not by backslash.
        quote = lambda s: '"' + s.replace('"','""') + '"'
        expression = f'Odbc.Query({quote(connection)}, {quote(query)})'
        if name=='Pairs':
            expression = ('let S = '+expression+', '
                'A = Table.RenameColumns(S, {{"skill_name", "skill_a"}}), '
                'J = Table.NestedJoin(A, {"job_key"}, S, {"job_key"}, "B", JoinKind.Inner), '
                'E = Table.ExpandTableColumn(J, "B", {"skill_name"}, {"skill_b"}), '
                'F = Table.SelectRows(E, each Comparer.Ordinal([skill_a], [skill_b]) < 0), '
                'R = Table.AddColumn(F, "pair_label", each [skill_a] & " + " & [skill_b], type text) in R')
        cols = []
        for column, dtype in TABLE_COLUMNS[name]:
            col = {'name':column,'dataType':dtype,'sourceColumn':column,'summarizeBy':'none'}
            if column=='source_url': col['dataCategory']='WebUrl'
            if column=='analysis_date': col['formatString']='yyyy-MM-dd'
            cols.append(col)
        table = {'name':name,'columns':cols,'partitions':[{'name':name,'mode':'import',
                  'source':{'type':'m','expression':expression}}]}
        if name=='Jobs': table['measures']=measures()
        if name in ('SkillJobs','Pairs','CityJobs'): table['isHidden']=True
        tables.append(table)
    relationships = []
    for target in ('CityJobs','SkillJobs','Pairs','Evidence'):
        relationships.append({'name':f'{target}_Jobs','fromTable':target,'fromColumn':'job_key',
                              'toTable':'Jobs','toColumn':'job_key','crossFilteringBehavior':'oneDirection'})
    relationships.extend([
        {'name':'Jobs_Builds','fromTable':'Jobs','fromColumn':'build_id','toTable':'Builds','toColumn':'build_id',
         'crossFilteringBehavior':'oneDirection'},
        {'name':'SkillJobs_Skills','fromTable':'SkillJobs','fromColumn':'skill_name','toTable':'Skills','toColumn':'skill_name',
         'crossFilteringBehavior':'oneDirection'},
        {'name':'Evidence_Skills','fromTable':'Evidence','fromColumn':'skill_name','toTable':'Skills','toColumn':'skill_name',
         'crossFilteringBehavior':'oneDirection'},
    ])
    return {'name':'RecruitmentPilot','compatibilityLevel':1600,'model':{
        'culture':'zh-CN','defaultPowerBIDataSourceVersion':'powerBI_V3',
        'dataAccessOptions':{'legacyRedirects':True,'returnErrorValuesAsNull':True},
        'tables':tables,'relationships':relationships,
        'annotations':[{'name':'PBI_QueryOrder','value':json.dumps(list(TABLE_COLUMNS))},
                       {'name':'RecruitmentPilotScope','value':'partial; two sources; not daily market trends'}]}}


def field(table, column, measure=False):
    return {('Measure' if measure else 'Column'):{'Expression':{'SourceRef':{'Entity':table}},'Property':column}}


def literal(value):
    if isinstance(value,bool): value='true' if value else 'false'
    elif isinstance(value,str): value="'"+value.replace("'","''")+"'"
    else: value=str(value)+'D'
    return {'expr':{'Literal':{'Value':value}}}


def visual(name, typ, x, y, width, height, roles=None, title=None, objects=None):
    v = {'$schema':f'{SCHEMA}/report/definition/visualContainer/2.0.0/schema.json','name':name,
         'position':{'x':x,'y':y,'z':0,'height':height,'width':width,'tabOrder':0},
         'visual':{'visualType':typ,'drillFilterOtherVisuals':True}}
    if roles:
        labels={'source':'来源','batch_id':'采集批次','build_id':'构建编号','skill_denominator':'正文分母',
                'skill_name':'标准技能','pair_label':'技能组合','source_job_id':'岗位 ID','title_raw':'岗位名称',
                'is_core':'核心岗位','experience_group':'经验分组','education_group':'学历分组','source_url':'来源链接',
                'eligible_for_metric':'证据有效','evidence_field':'原文字段','evidence':'证据原文',
                'evidence_start':'起始位置','evidence_end':'结束位置','matched_text':'命中文本',
                'raw_field_name':'来源字段','body_hash_version':'正文哈希版本','raw_ref':'原始响应',
                'dictionary_version':'词典版本','rule_version':'规则版本','scope_version':'范围版本','skill_text_scope':'技能文本范围'}
        v['visual']['query']={'queryState':{role:{'projections':[
            {'field':field(t,c,m),'queryRef':f'{t}.{c}','nativeQueryRef':c,'displayName':labels.get(c,c)} for t,c,m in columns]}
            for role,columns in roles.items()}}
        if name in ('skills','pairs','cities','experience','education'):
            metric={'skills':'技能岗位数','pairs':'组合岗位数'}.get(name,'核心岗位数')
            v['visual']['query']['sortDefinition']={'sort':[{'field':field('Jobs',metric,True),'direction':'Descending'}],'isDefaultSort':False}
    container = {'background':[{'properties':{'color':{'solid':{'color':literal('#FFFFFF')}},'transparency':literal(0)}}]}
    if title:
        container['title']=[{'properties':{'show':literal(True),'text':literal(title),
                                          'fontSize':literal(12),'fontColor':{'solid':{'color':literal('#123047')}}}}]
    v['visual']['visualContainerObjects']=container
    if typ=='tableEx':
        v['visual']['objects']={
            'values':[{'properties':{'fontSize':literal(13)}}],
            'columnHeaders':[{'properties':{'fontSize':literal(13)}}],
            'grid':[{'properties':{'rowPadding':literal(5)}}],
        }
    if objects: v['visual']['objects']=objects
    return v


def textbox(name, text, x,y,w,h, size=16, color='#123047'):
    return visual(name,'textbox',x,y,w,h,objects={'general':[{'properties':{'paragraphs':[
        {'textRuns':[{'value':text,'textStyle':{'fontSize':f'{size}pt','fontFamily':'Segoe UI','color':color}}]}]}}]})


def report():
    report_dir = PROJECT/'Recruitment.Report'
    write_json(report_dir/'definition.pbir',{'$schema':f'{SCHEMA}/report/definitionProperties/2.0.0/schema.json',
        'version':'4.0','datasetReference':{'byPath':{'path':'../Recruitment.SemanticModel'}}})
    write_json(report_dir/'definition/report.json',{
        '$schema':f'{SCHEMA}/report/definition/report/2.0.0/schema.json','themeCollection':{},
        'settings':{'useStylableVisualContainerHeader':True,'exportDataMode':'AllowSummarized'}})
    write_json(report_dir/'definition/version.json',{
        '$schema':f'{SCHEMA}/report/definition/versionMetadata/1.0.0/schema.json','version':'2.0.0'})
    pages = ['overview','skills','evidence','quality']
    write_json(report_dir/'definition/pages/pages.json',{
        '$schema':f'{SCHEMA}/report/definition/pagesMetadata/1.0.0/schema.json',
        'pageOrder':pages,'activePageName':'overview'})
    def save_page(name,title,vs):
        page = report_dir/'definition/pages'/name
        write_json(page/'page.json',{'$schema':f'{SCHEMA}/report/definition/page/2.0.0/schema.json',
            'name':name,'displayName':title,'displayOption':'FitToPage','height':900,'width':1440})
        for v in vs: write_json(page/'visuals'/v['name']/'visual.json',v)
    def c(t,n): return (t,n,False)
    def m(n): return ('Jobs',n,True)
    def common(title, evidence=False):
        vs=[textbox('title',title,24,16,1380,52,24),
            textbox('note','PARTIAL 小批样本 · 来源岗位数 · 两源观察日不同 · 不代表招聘市场全量或每日趋势',24,72,1380,34,11)]
        for i,(t,col,label) in enumerate([('Builds','source','来源'),('CityJobs','city','城市（多工作地可重复归组）'),
              ('Jobs','experience_group','经验'),('Jobs','category_group','源类别'),('Jobs','education_group','学历')]):
            vs.append(visual('filter'+str(i),'slicer',24+i*280,114,268,104,{'Values':[c(t,col)]},label,
                     {'data':[{'properties':{'mode':literal('Dropdown')}}],
                      'selection':[{'properties':{'singleSelect':literal(False)}}]}))
        if not evidence:
            for i,metric in enumerate(['核心岗位数','正文分母','岗位技能对数','正文覆盖率']):
                vs.append(visual('kpi'+str(i),'card',24+i*350,234,338,106,{'Values':[m(metric)]},metric))
        return vs
    vs=common('招聘岗位与技能结构 | 小批概览')
    vs.extend([
        visual('cities','clusteredBarChart',24,360,450,450,{'Category':[c('CityJobs','city')],'Y':[m('核心岗位数')]},'城市分布（去重岗位）'),
        visual('experience','clusteredBarChart',490,360,450,450,{'Category':[c('Jobs','experience_group')],'Y':[m('核心岗位数')]},'经验分布（冲突单列）'),
        visual('education','clusteredBarChart',956,360,450,450,{'Category':[c('Jobs','education_group')],'Y':[m('核心岗位数')]},'学历分布（冲突单列）'),
        textbox('foot','技能分母包含无技能命中的核心有效正文岗位；腾讯 15 岗、网易 18 岗。城市合计可能超过岗位数。',24,830,1380,42,12),
    ])
    save_page('overview','01 小批概览',vs)
    vs=common('技能出现与组合 | 筛选后重算分母')
    vs.extend([
        visual('skills','tableEx',24,360,660,460,{'Values':[c('Skills','skill_name'),m('技能岗位数'),m('正文分母'),m('技能出现占比')]},'技能需求（点选技能不缩小正文分母）'),
        visual('pairs','tableEx',708,360,698,460,{'Values':[c('Pairs','pair_label'),m('组合岗位数'),m('组合出现占比')]},'无序技能组合（同岗每组合一次）'),
        textbox('foot','城市、经验、学历、类别按同一核心正文集合筛选；空分母占比显示空白。版本差异不解释为市场增长。',24,838,1380,42,12),
    ])
    save_page('skills','02 技能与组合',vs)
    vs=common('岗位与证据 | 字段、位置、原文和版本回查',True)
    vs.extend([
        visual('jobfilter','slicer',24,234,680,100,{'Values':[c('Jobs','source_job_id')]},'岗位 ID（文本；可选择扩展岗位）'),
        visual('skillfilter','slicer',726,234,680,100,{'Values':[c('Skills','skill_name')]},'技能（审计含无效与扩展证据）'),
        visual('jobs','tableEx',24,352,1382,180,{'Values':[c('Jobs',n) for n in ('source','source_job_id','title_raw','is_core','experience_group','education_group','source_url')]},'岗位信息（点击一行联动证据）'),
        visual('evidence','tableEx',24,550,1382,280,{'Values':[c('Evidence',n) for n in ('skill_name','eligible_for_metric','evidence_field','evidence','evidence_start','evidence_end','matched_text','raw_field_name','body_hash_version','raw_ref')]},'证据审计：包含不计入指标的记录'),
        textbox('foot','位置是 Python Unicode 字符下标，左闭右开；原文及哈希保留在 Evidence/Jobs 表。技能筛选不回传岗位分母。',24,842,1380,42,11),
    ])
    save_page('evidence','03 岗位与证据',vs)
    vs=[textbox('title','构建与质量 | 固定版本、披露范围',24,20,1380,58,24),
        visual('builds','tableEx',24,100,1382,270,{'Values':[c('Builds',n) for n in ('source','batch_id','build_id','skill_denominator','body_hash_version','dictionary_version','rule_version','scope_version','skill_text_scope')]},'本次刷新固定构建（代理键随机器变化）'),
        textbox('decisions','网易：78482、79489 归扩展；78590 城市冲突；71196 学历冲突。\n13 条经验提示中 12 条为冲突；78729 为建议，保留“不限”。\n腾讯：2 条扩展、9 条城市冲突、3 条经验差异；确认一岗北京/深圳双工作地。',24,400,1380,170,17),
        textbox('rules','默认对账：腾讯核心 98 / 技能对 333 / 有技能岗位 83；网易核心 98 / 技能对 334 / 有技能岗位 80。\n指标同时筛核心及有效证据；技能按岗位去重。\n仅为部分小批；正式每日快照、跨源归并及市场趋势尚未验收。',24,590,1380,170,17),
        textbox('refresh','刷新顺序：关闭 Desktop → 运行 prepare_powerbi 固定已对账构建 → 打开 Recruitment.pbip → 刷新 → 运行 DAX 对账。',24,800,1380,60,13)]
    save_page('quality','04 构建与质量',vs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server',default=os.getenv('DW_SERVER','lpc:localhost'))
    parser.add_argument('--database',default=os.getenv('DW_DATABASE','recruitment_dw_dev_cd_v1'))
    args=parser.parse_args()
    if any(x in args.server for x in ';{}'):
        raise ValueError('Invalid local SQL Server name')
    os.environ['DW_SERVER']=args.server
    os.environ['DW_DATABASE']=args.database
    cn=connect()
    cn.timeout=60
    try:
        print('Checking selected ADS builds...',flush=True)
        cursor=cn.execute('SELECT source,batch_id,build_id,skill_denominator,body_hash_version,skill_text_scope,dictionary_version,rule_version,scope_version FROM ads.current_analysis_builds ORDER BY source')
        builds=[dict(zip([x[0] for x in cursor.description],row)) for row in cursor]
        if len(builds)!=2 or {b['source'] for b in builds}!={'tencent','netease'}:
            raise ValueError('Expected exactly two selected pilot sources')
        for b in builds:
            if (b['skill_denominator'],b['body_hash_version'],b['dictionary_version'],b['rule_version']) != (98,'skills-body-1.1','skills-dict-0.2.0','skills-rules-0.3.0'):
                raise ValueError('Reconcile updated pilot inputs before preparing a report')
        ids=[b['build_id'] for b in builds]
        queries=sql_queries(ids)
        # Make the Builds import immutable too; the current pointer may change later.
        queries['Builds']=queries['Builds'].replace('ads.current_analysis_builds', 'ads.cd_overview')
        for name,query in queries.items():
            print('Checking import: '+name,flush=True)
            rows=cn.execute(query).fetchall()
            if name=='SkillJobs' and len(rows)!=667: raise ValueError('Unexpected job-skill pairs')
            if name=='Jobs' and len(rows)!=200: raise ValueError('Unexpected pilot jobs')
        bim=model(ids,args.server,args.database)
        bim['model']['tables'][0]['partitions'][0]['source']['expression'] = bim['model']['tables'][0]['partitions'][0]['source']['expression'].replace('ads.current_analysis_builds','ads.cd_overview')
        write_json(PROJECT/'Recruitment.SemanticModel/model.bim',bim)
        write_json(PROJECT/'Recruitment.SemanticModel/definition.pbism',{
            '$schema':f'{SCHEMA}/semanticModel/definitionProperties/1.0.0/schema.json','version':'4.0','settings':{}})
        write_json(PROJECT/'Recruitment.pbip',{
            '$schema':'https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json','version':'1.0',
            'artifacts':[{'report':{'path':'Recruitment.Report'}}],'settings':{'enableAutoRecovery':True}})
        report()
        write_json(PROJECT/'refresh_selection.json',{'database':args.database,'server':args.server,
                   'builds':builds,'query_sha256':hashlib.sha256(json.dumps(queries,sort_keys=True).encode()).hexdigest(),
                   'note':'IDs frozen for all imports; regenerate only after reconciliation. No credentials stored.'})
        print(json.dumps({'project':str(PROJECT/'Recruitment.pbip'),'builds':builds},ensure_ascii=False))
    finally: cn.close()


if __name__=='__main__': main()
