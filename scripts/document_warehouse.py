"""Generate model/field documentation from verified SQL metadata, with business meanings."""
import argparse
from datetime import datetime
from collections import defaultdict
import json
from pathlib import Path
import re
import yaml
from warehouse.load import ROOT,connect
from warehouse.release_build import records

MEANINGS={
 'qualification_rule_version':'学历/经验派生规则版本；原值和旧发布不覆写。',
 'education_resolution_json':'学历值、来源/正文依据、必需/优先/不确定证据、字符位置及原始引用 JSON。',
 'experience_resolution_json':'经验规范值、状态、来源字段证据与原始引用 JSON；中文数字忠实转换。',
 'education_resolution_status':'学历解析状态 structured/body_required/preference_only/not_stated/conflict/ambiguous/unparsed。',
 'education_basis':'学历派生依据类型，区别结构化来源、正文与未提供。',
 'education_basis_label':'供报表阅读的中文学历依据，保留来源/正文/偏好/未注明/冲突的区别。',
 'qualification_kind':'门槛证据类型：学历或经验。','qualification_value':'该门槛的规范化结果。',
 'resolution_status':'门槛解析状态，不将未注明或仅优先当成硬性要求。',
 'strength':'门槛证据强度：必需、优先、不确定或来源值。',
 'degree':'该条证据对应的学历层次；没有学历证据时为空。',
 'record_ref':'规范源记录 jobs.jsonl 及文本岗位ID定位；证据下标指该记录相应字段值。',
 'raw_refs_json':'该规范记录对应的原响应文件与哈希集合，可定位列表/详情，不假定字段都来自详情。',
 'analysis_date':'接口的分析日期；release 系列取北京时间批次结束日，trial/CD 取北京时间观察日；均不是岗位发布日期。',
 'body_valid':'按该构建的 skill_text_scope 判断正文有效；三字段构建含职责、任职要求、补充要求。',
 'core_posting_count':'当前模型粒度下的核心来源岗位计数；多日状态不可直接累加为独立机会。',
 'skill_denominator':'当前模型粒度下全部有效正文核心岗位数，包括零技能命中；不从技能桥取分母。',
 'posting_count':'当前维度组覆盖的不同来源岗位数；技能或城市分组之间可能重叠。',
 'skill_share':'有效技能覆盖岗位数 / 对应完整正文岗位集合；技能筛选不反向缩小分母。',
 'release_id':'整组分析发布版本；固定输入构建、日期范围及规范化/映射规则，查询须显式选择。',
 'build_id':'单来源批次的范围、冲突及技能分析构建；不是整组 release。',
 'date_key':'北京时间批次结束日的 YYYYMMDD 键，引用 dim.calendar_date；不是岗位发布日期。',
 'job_key':'稳定来源岗位分析身份，当前与 posting_key 一对一，不声称完成跨来源归并。',
 'posting_key':'由来源代码与文本岗位 ID 唯一识别的来源身份代理键。',
 'representative_version_key':'本条日状态选中的内容版本；当前等于被选观察的 version_key。',
 'snapshot_key':'release_id、date_key、job_key 拼接的 BI 关系键，用来区分多日状态。',
 'source_key':'来源维代理键；用于统一来源成员，不等于企业键。',
 'source_code':'批准的来源代码 tencent/netease；与来源岗位 ID 组成自然身份。',
 'source_name':'来源显示名称。','official_url':'来源官方招聘入口 URL。',
 'company_key':'来源企业品牌名称的维度键；不是已核实法律主体身份。',
 'company_name':'保守保留的企业/品牌名；缺失为显式未知。',
 'identity_status':'主体核实状态；当前为来源品牌、未核实法律实体。',
 'category_key':'标准岗位方向的维度键，按规范化版本识别。',
 'category_name':'标准方向：开发、测试、数据开发/分析、算法/AI、运维/安全或待分类。',
 'category_group':'快照中的标准岗位方向，按第2章初分类规则；来源原类别为 category_raw。',
 'education_key':'学历规范成员代理键；未知、不限、冲突分别建成员。',
 'education_name':'规范学历分组，源值保留在观察/内容中。',
 'experience_key':'经验规范成员代理键，保留源经验区间，不伪造精度。',
 'experience_name':'规范经验分组；未知、不限、冲突分开。',
 'employment_type_key':'招聘类型维键；未经核实的数字代码为来源代码未释义。',
 'employment_type_name':'招聘类型分组，不将未知代码猜成社招/校招。',
 'employment_type_group':'日状态使用的招聘类型规范分组；当前多为代码未释义。',
 'city_key':'规范地点成员代理键。','city_code':'内部地点业务代码，不冒充官方行政区划代码。',
 'city_name':'规范城市名，统一市字后缀；未知和冲突显式保留。',
 'province_name':'保守查表得到的省级名称；未映射城市不猜测省份。',
 'mapping_status':'地点映射状态 mapped/unmapped/unknown/conflict。',
 'location_key':'历史原地点字典键，区别于规范 dim.city.city_key。',
 'normalization_version':'岗位类别和地点等标准化规则版本。',
 'mapping_version':'来源岗位到分析身份的映射版本；当前 source-identity-only-1.0。',
 'mapping_method':'来源身份到分析身份的映射方法；当前保守一对一。',
 'creation_method':'分析身份创建方法；当前限定 source_identity_only。',
 'calendar_date':'日历 DATE，用于日期维；不代表该日确有采集。',
 'calendar_year':'日历年份。','calendar_quarter':'季度 1—4。','calendar_month':'月份 1—12。','calendar_day':'月内日期。',
 'job_count':'每条日状态为 1；跨日期或多值桥展开后不能直接累加为独立岗位数。',
 'skilled_posting_count':'该来源/方向正文集合中至少命中一项有效技能的不同岗位数。',
 'body_coverage':'有效正文核心岗位数 / 核心岗位数；零分母 NULL。',
 'skill_coverage':'至少命中一项有效技能的岗位数 / 有效正文岗位数；不等于词频。',
 'channel':'发布通道 sample/formal；sample 可包含 partial，formal 必须通过范围完整性。',
 'status':'构建生命周期 building/ready；ready 不等于已发布或数据全量。',
 'code_sha256':'日状态构建实现的代码内容指纹。','input_hash':'不可变输入/规则组合的 SHA-256 指纹，用于幂等和防覆盖。',
 'content_hash':'岗位内容属性的 SHA-256，不含采集时间；相同内容重现仍按有效期维护。',
 'created_at':'技术构建创建时间，不是岗位发布日期。','loaded_at':'原始批次加载时间。','updated_at':'发布指针更新时间。',
 'observed_at':'带时区的真实采集观察时刻。','valid_from_observed':'内容版本观察有效期起点（含）。',
 'valid_to_observed':'内容版本观察有效期终点（不含），当前有效版本为 NULL。',
 'manifest_json':'原始批次清单 JSON，包含范围、起止、请求/页数和验收/覆盖状态。',
 'provenance_json':'提取输入、规则、正文、词典与来源证据的构建血缘 JSON。',
 'payload':'该持久对象的不可变原字段 JSON；业务字段原值保留。',
 'load_mode':'接入模式，当前持久库沿用 trial 命名，不表示已完成正式范围覆盖。',
 'record_count':'批次实际规范来源岗位记录数，不等于请求数或全站总数。',
 'byte_count':'原始响应文件实际字节数。','relative_path':'批次目录内的原始响应相对路径。',
 'sha256':'该文件实际字节的 SHA-256，用于证据一致性校验。','issue_no':'批次内质量问题序号。',
 'expected_sources_json':'发布批准来源集合 JSON，不能因缺来源而自动缩小。',
 'expected_source_count':'批准范围内预期的来源数量。','observed_source_count':'该日实际选入的不同来源数。',
 'complete_source_count':'该日技术验收且 complete 的来源批次数。',
 'is_complete':'该日批准来源集合是否全部完整；不完整不可作变化基线。',
 'is_comparable':'当前与相邻前一日是否都完整，且发布固定同一规则/范围。',
 'previous_date_key':'严格相邻前一日的日历键；没有对应日汇总时不可比较。',
 'newly_observed_count':'可比相邻日中新出现的来源岗位身份数，不等于企业新招聘。',
 'first_discovered_count':'本发布观察窗口内首次发现的岗位数；无完整基线时 NULL。',
 'still_unobserved_count':'曾出现但连续两个合格日未观察的身份数，不确认岗位关闭。',
 'content_changed_count':'可比日相同身份的代表内容哈希变化数，不含凭空追造历史。',
 'comparison_note':'变化计算成立或拒绝计算的业务原因。','dataset_note':'样本/正式观察范围及推断限制提示。',
 'issue_code':'发布校验的违规类型；验证视图每行是一个问题，零行才通过。',
 'publication_id':'一次成功切换发布指针的审计流水键。','previous_release_id':'切换前的同通道发布版本，可为 NULL。',
 'published_at':'技术发布时间，不是采集日或企业发布日期。','validation_json':'该次发布校验的审计说明 JSON。',
 'evidence':'来源正文逐字证据片段。','evidence_field':'职责、任职要求或补充要求的字段名。',
 'evidence_start':'证据片段起始 Unicode 字符索引（含），不是字节位置。',
 'evidence_end':'证据片段结束 Unicode 字符索引（不含）。',
}
MODEL_GRAINS={
 'release_qualification_evidence':'每曾发布 release×日×岗位×门槛证据；区分必需、优先及待确认并保留原文。',
 'release_calendar':'每曾发布 release×日历日；填充分析窗口日历，但不伪造该日岗位。',
 'release_city':'每曾发布 release×分析日×规范城市；不同核心岗位计数，多城市不加总。',
 'release_city_detail':'每曾发布 release×分析日×岗位×城市，供城市筛选集合。',
 'release_job_detail':'每曾发布 release×分析日×来源岗位；标准属性、原值和证据引用。',
 'release_observed_change':'每曾发布 release×分析日；只在完整相邻基线成立时计算变化。',
 'release_skill_demand':'每曾发布 release×分析日×技能；去重覆盖数与当日正文分母。',
 'release_skill_detail':'每曾发布 release×分析日×岗位×有效标准技能。',
 'release_skill_evidence':'每曾发布 release×分析日×岗位×证据锚点，含审计无效证据。',
 'release_validation':'每实际发布违规一行；未发现违规为零行，不伪造通过行。',
 'release_daily_summary':'每 release×分析日；来源完整性、核心岗位及正文计数。',
 'release_job_structure':'B01：每 release×分析日×来源×标准方向，岗位结构计数。',
 'release_skill_profile':'B02：每 release×分析日×来源×标准方向×技能，独立分子/正文分母。',
 'release_entry_profile':'B03：每 release×分析日×来源×标准方向×学历×经验×招聘类型。',
 'job_demand_structure':'B01 对外服务，物理名 ads.release_job_structure；来源/类别显示属性和覆盖率。',
 'job_demand_skill_profile':'B02 对外服务，物理名 ads.release_skill_profile；技能覆盖与类别正文分母。',
 'job_demand_entry_profile':'B03 对外服务，物理名 ads.release_entry_profile；门槛分布供交叉分析。',
}
TABLE_GRAINS={
 'dwd.job_qualification_evidence':'每 release×分析日×岗位的学历/经验派生及证据；原观察不覆写。',
 'ods.raw_response':'一批次×一个原始响应文件，保存引用、哈希和大小。',
 'ods.posting_record':'一批次×一个来源岗位 ID，保存原始规范记录 JSON。',
 'dwd.fact_posting_observation':'一批次×一来源身份；无事实型观察明细，不等于企业发布事件。',
 'dwd.fact_job_daily':'一发布×一分析日×一来源岗位身份；主分析快照，计数对日期半可加。',
 'dwd.bridge_daily_city':'一发布×一分析日×一来源岗位×一个规范地点。',
 'dwd.bridge_daily_skill':'一发布×一分析日×一来源岗位×一个有效标准技能。',
 'dwd.bridge_version_skill':'一提取构建×内容版本×技能×强度×有效性；保存证据组。',
 'dwd.bridge_version_location':'一内容版本×原始地点×原地点映射版本。',
 'dwd.observation_enrichment':'一提取构建×一来源观察；范围、正文增强及字段冲突。',
 'dwd.posting_job_map':'一映射版本×一来源身份；当前一对一保守映射。',
 'dim.posting_identity':'一来源代码×一文本岗位 ID；来源身份字典。',
 'dim.posting_version':'一来源身份的一段观察内容有效期，A→B→A 维护三个版本。',
 'dim.job':'一个分析岗位身份，当前一对一来源身份，不声称跨来源归并。',
 'dim.location':'一个原地点字符串；与规范 dim.city 分开。',
 'dim.skill':'一个标准技能名。','dim.source':'一个批准官网来源。',
 'dim.company':'一个来源企业品牌名，未核实法律主体。','dim.calendar_date':'一个日历日。',
 'dim.city':'一规范化版本×一个内部地点代码，含省市及映射状态。',
 'dim.job_category':'一规范化版本×一个标准方向。','dim.education':'一个规范学历成员。',
 'dim.experience':'一个规范经验成员。','dim.employment_type':'一个规范招聘类型成员。',
 'audit.collection_batch':'一次真实来源扫描的批次元数据，不是分析业务事实。',
 'audit.quality_issue':'一批次×质量问题序号。','audit.analysis_build':'一个单来源批次/提取规则组合。',
 'audit.analysis_selection':'一批次的当前 CD 构建选择，历史基线工具使用。',
 'audit.model_build':'一个固定输入及规则的整组分析 release。',
 'audit.release_input':'一个 release 选择的单来源提取构建；每源×日唯一。',
 'audit.publication_pointer':'每个发布通道当前 release 指针。',
 'audit.publication_history':'一次已成功的发布切换，保留上一版本及验证信息。',
}


def main(database,evidence_output=None):
    evidence_output=Path(evidence_output) if evidence_output else ROOT/('reports/verification/模型文档覆盖_'+datetime.now().strftime('%Y%m%dT%H%M%S')+'.json')
    if evidence_output.exists():raise FileExistsError(evidence_output)
    c=connect(database)
    try:
        rows=records(c,'''SELECT s.name as schema_name,o.name as object_name,o.type,c.column_id,c.name as column_name,
          t.name as sql_type,c.max_length,c.is_nullable,
          CASE WHEN EXISTS(SELECT 1 FROM sys.index_columns ic JOIN sys.indexes i ON i.object_id=ic.object_id AND i.index_id=ic.index_id
           WHERE ic.object_id=o.object_id AND ic.column_id=c.column_id AND i.is_primary_key=1) THEN 1 ELSE 0 END as is_pk,
          (SELECT TOP(1) ss.name+'.'+oo.name+'.'+cc.name FROM sys.foreign_key_columns fk JOIN sys.objects oo ON oo.object_id=fk.referenced_object_id
            JOIN sys.schemas ss ON ss.schema_id=oo.schema_id JOIN sys.columns cc ON cc.object_id=oo.object_id AND cc.column_id=fk.referenced_column_id
           WHERE fk.parent_object_id=o.object_id AND fk.parent_column_id=c.column_id) as fk_target
          FROM sys.objects o JOIN sys.schemas s ON s.schema_id=o.schema_id JOIN sys.columns c ON c.object_id=o.object_id
          JOIN sys.types t ON t.user_type_id=c.user_type_id WHERE o.type IN ('U','V') AND s.name IN ('ods','dim','dwd','dws','ads','audit')
          ORDER BY s.name,o.name,c.column_id''')
    finally:c.close()
    known={};original={}
    managed=ROOT/'dbt/models/release_schema.yml'
    for path in (ROOT/'dbt/models').rglob('*.yml'):
        if path==managed:continue
        for m in (yaml.safe_load(path.read_text(encoding='utf-8')) or {}).get('models',[]):
            original[m['name']]=m
            for col in m.get('columns',[]):known.setdefault(col['name'],col.get('description'))
    meanings={**known,**MEANINGS};missing=sorted({r['column_name'] for r in rows}-set(meanings))
    if missing:raise ValueError(f'Add business meanings before documenting: {missing}')
    objects=defaultdict(list)
    for row in rows:
        row['type']=row['type'].strip()
        objects[(row['schema_name'],row['object_name'])].append(row)
    model_docs=[];sources=defaultdict(list);index=[];details=[]
    for (schema,name),cols in objects.items():
        key=schema+'.'+name
        def meaning(column):
            if column=='analysis_date':
                return ('北京时间批次结束日，来自 manifest.finished_at；不是发布日期。' if name.startswith('release_')
                        else 'observed_at 换算 Asia/Shanghai 的观察日；不是源岗位发布日期或加载日。')
            if column=='body_valid' and key=='dwd.fact_posting_observation':
                return '原始观察的职责/任职要求两字段有效性；三字段增强在 CD/日状态接口另按构建范围计算。'
            return meanings[column]
        if cols[0]['type']=='U':
            description=TABLE_GRAINS[key];sql_path='sql/004_release_schema.sql'
            for p in sorted((ROOT/'sql').glob('*.sql')):
                if f'CREATE TABLE {key}(' in p.read_text(encoding='utf-8'):sql_path=str(p.relative_to(ROOT)).replace('\\','/');break
            sources[schema].append({'name':name,'description':description,'columns':[{'name':r['column_name'],'description':meaning(r['column_name'])} for r in cols]})
        else:
            paths=[]
            for p in (ROOT/'dbt/models'/schema).glob('*.sql'):
                alias=re.search(r"alias=['\"]([^'\"]+)",p.read_text(encoding='utf-8'))
                if (alias.group(1) if alias else p.stem)==name:paths.append(p)
            assert len(paths)==1,(key,paths)
            path=paths[0];sql_path=str(path.relative_to(ROOT)).replace('\\','/');node=path.stem
            description=MODEL_GRAINS.get(node) or original[node]['description']
            if node in MODEL_GRAINS:
                model_docs.append({'name':node,'description':description,'columns':[{'name':r['column_name'],'description':meaning(r['column_name'])} for r in cols]})
        index.append(f'| `{key}` | {"持久表" if cols[0]["type"]=="U" else "dbt视图"} | {description} |')
        details += ['',f'## {key}','',description,'',f'定义与转换 SQL：[源码](../../{sql_path})。业务含义以第 2、4 章为准；视图实际 SELECT 表达式是逐列转换依据。',
          '', '| 字段 | SQL 类型 | 可空 | 键/引用 | 含义 |','| --- | --- | --- | --- | --- |']
        for r in cols:
            typ=r['sql_type']
            if typ in ('nvarchar','varchar','char'):
                length=r['max_length'];typ+=f'({"MAX" if length==-1 else length//2 if typ=="nvarchar" else length})'
            keys=('组合PK成员；' if r['is_pk'] else '')+(('FK '+r['fk_target']) if r['fk_target'] else '')
            details.append(f'| `{r["column_name"]}` | {typ} | {"是" if r["is_nullable"] else "否"} | {keys or "—"} | {meaning(r["column_name"])} |')
    managed.write_text(yaml.safe_dump({'version':2,'models':model_docs},allow_unicode=True,sort_keys=False),encoding='utf-8')
    (ROOT/'dbt/models/sources.yml').write_text(yaml.safe_dump({'version':2,'sources':[{'name':s,'schema':s,'tables':t} for s,t in sorted(sources.items())]},allow_unicode=True,sort_keys=False),encoding='utf-8')
    doc=ROOT/'docs/reference/仓内对象字典.md';doc.parent.mkdir(parents=True,exist_ok=True)
    intro=['# 仓内对象与字段字典','','从主事实 `dwd.fact_job_daily` 及其维度/桥表开始阅读；ODS 和 AUDIT 为输入/支撑。下面为实际 SQL 元数据，不是未来计划对象。','',
      f'核查库：`{database}`；{len(objects)} 个对象，{len(rows)} 个输出/持久列。相同字段跨对象重复计列，不以列数作为工作量结论。','',
      'PK 成员共同组成主键，不表示每列各自唯一。job_key 当前为来源岗位身份；build_id 为单来源提取构建，release_id 为整组日分析发布。未知维成员使用显式业务值及普通代理键，没有固定 0 键约定。',
      '', '## 关键字段来源与转换','','| 分析字段 | 来源与转换 |','| --- | --- |',
      '| 日状态日期 | manifest.finished_at → Asia/Shanghai → date_key；不是源岗位更新时间 |',
      '| 核心资格 | 已验收批次、冻结范围规则及冲突裁定 → is_core |',
      '| 正文资格 | 职责、任职要求、补充要求至少一有效；旧构建按其字段范围保留原含义 |',
      '| 标准类别 | 标题职业特征优先、源宽类别回退；原类别另存；规则见 normalization.py 与需求第2章 |',
      '| 城市 | confirmed_locations_json + 冲突裁定 → 别名与省市查表；无法映射不猜测 |',
      '| 有效技能成员 | 三字段证据同时筛核心/有效/正文资格，按日状态×标准技能去重 |',
      '| 技能占比 | 有效技能覆盖的不同岗位数 / 对应完整正文集合；不是证据行数占比 |',
      '| 原始证据 | source_revision、batch_id、raw_ref、文件/正文哈希、字段及字符位置逐级追溯 |',
      '', '## 对象目录','','| 对象 | 形式 | 粒度和用途 |','| --- | --- | --- |']
    doc.write_text('\n'.join(intro+index+details)+'\n',encoding='utf-8')
    result={'status':'passed','database':database,'documented_objects':len(objects),'documented_columns':len(rows),
      'new_model_descriptions':len(model_docs),'unexplained_columns':missing}
    evidence_output.parent.mkdir(parents=True,exist_ok=True)
    evidence_output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--database',default='recruitment_dw_dev_cd_v1');p.add_argument('--evidence-output',type=Path)
    args=p.parse_args();main(args.database,args.evidence_output)
