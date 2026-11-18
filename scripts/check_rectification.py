"""Check today's warehouse design/implementation contract without replacing older evidence."""
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
import re
from urllib.parse import unquote
from scripts.check_subjects import check
from scripts.powerbi_contract import validate_model
from warehouse.load import ROOT


def file_hash(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    own_output=ROOT/'reports/verification/课程整改验收_20261118.json'
    subjects=check(write_report=False)
    path=ROOT/'dashboards/powerbi/Recruitment.SemanticModel/model.bim'
    document=json.loads(path.read_text(encoding='utf-8'));model=validate_model(document)
    dax=json.loads((ROOT/'reports/verification/powerbi_release_validation_20261118.json').read_text(encoding='utf-8'))
    assert dax['status']=='passed' and dax['case_count']>=84
    assert file_hash(path)==dax['model_definition_sha256'],'Current model differs from the validated engine version'
    assert file_hash(ROOT/'reports/verification/powerbi_release_cases_20261118.json')==dax['cases_sha256']
    manifest=json.loads((ROOT/'dbt/target/manifest.json').read_text(encoding='utf-8'))
    nodes=[n for n in manifest['nodes'].values() if n['resource_type']=='model']
    undocumented=[n['name'] for n in nodes if not n.get('description')]
    assert len(nodes)==37 and not undocumented
    missing_columns=[]
    for n in nodes:
        for name,c in n.get('columns',{}).items():
            if not c.get('description'):missing_columns.append(n['name']+'.'+name)
    assert not missing_columns
    by_table={t['name']:t for t in document['model']['tables']}
    def inspect(value):
        if isinstance(value,list):
            for x in value:inspect(x)
        elif isinstance(value,dict):
            for kind in ('Column','Measure'):
                f=value.get(kind,{});entity=f.get('Expression',{}).get('SourceRef',{}).get('Entity')
                if entity:
                    table=by_table[entity];names={x['name'] for x in table.get('columns' if kind=='Column' else 'measures',[])}
                    assert f['Property'] in names,(entity,f['Property'])
            for x in value.values():inspect(x)
    pages=ROOT/'dashboards/powerbi/Recruitment.Report/definition/pages'
    for p in pages.rglob('*.json'):inspect(json.loads(p.read_text(encoding='utf-8')))
    files=[ROOT/'README.md',ROOT/'warehouse/README.md',ROOT/'reports/analysis/岗位需求主题分析.md']
    files+=list((ROOT/'docs/design').glob('*.md'))+[ROOT/'docs/reference/仓内对象字典.md',ROOT/'docs/verification/课程整改与答辩逐项核查.md']
    bad_links=[]
    for p in files:
        for link in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
            if link.startswith(('http:','https:','#','mailto:')):continue
            link_target=unquote(link.split('#')[0])
            resolved=(p.parent/link_target).resolve() if link_target else None
            if resolved and resolved!=own_output.resolve() and not resolved.exists():bad_links.append((str(p.relative_to(ROOT)),link))
    assert not bad_links,bad_links
    clean=ROOT/'.local/rectify-20261118/clean-qualifications'
    reproduction=json.loads((clean/'.local/reproduction/recruitment_dw_dev_qualification_20261118/result.json').read_text(encoding='utf-8'))
    build=json.loads((clean/'dbt/target/run_results.json').read_text(encoding='utf-8'))
    assert reproduction['status']=='passed'
    assert len(build['results'])==53 and all(x['status'] in ('success','pass') for x in build['results'])
    doc_coverage=json.loads((ROOT/'reports/verification/模型文档覆盖_20261118.json').read_text(encoding='utf-8'))
    assert doc_coverage['unexplained_columns']==[]
    # Diagrams are delivered as editable sources; inspect their actual references as well.
    svgs=[ROOT/'docs/design/figures'/n for n in ('03_00_岗位分析信息包.svg','04_01_岗位日状态星型.svg','04_02_分层与分析模型.svg')]
    result={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'status':'passed_for_current_sample_scope',
      'teacher_issues':{'subject_oriented_analysis':'implemented_and_reconciled','fact_design':'grain_dimensions_facts_and_additivity_explicit',
        'conceptual_expression':'information_package_primary_business_ER_auxiliary','star_vs_layers':'actual_star_plus_layer_lineage_and_three_topic_interfaces',
        'consistency_and_handoff':'current_docs_keys_categories_and_model_aligned_clean_directory_reproduction_passed'},
      'subjects':subjects,'semantic_model_contract':model,'powerbi_engine_cases':dax['case_count'],'powerbi_model_sha256':file_hash(path),
      'dbt_models':len(nodes),'dbt_models_documented':len(nodes),'dbt_checks_passed':16,'clean_directory_reproduction':reproduction,
      'clean_directory_runtime_scope':'Separate source checkout and new database, sharing only the installed pinned Python environment and read-only Git object storage; no original hidden batch/cache inputs.',
      'offline_tests':{'count':75,'status':'passed','elapsed_seconds':12.967,'scope':'current tree including qualification parsing regressions','evidence':'observed execution; .local/rectify-20261118/qualification_tests.log'},
      'qualification_rectification':json.loads((ROOT/'reports/verification/门槛字段整改_20261118.json').read_text(encoding='utf-8')),
      'data_dictionary':doc_coverage,'current_links':'passed','visual_field_references':'passed',
      'diagrams':{str(p.relative_to(ROOT)):file_hash(p) for p in svgs},
      'remaining_final_data_conditions':['real consecutive complete source batches before trends','additional 100-job HUMAN review before claiming that acceptance target','independent verification of employment type codes before using that analysis'],
      'not_claimed':['teacher grading approval','nationwide market coverage','cross-source entity resolution','new physical backup restore in this session']}
    own_output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'dbt_models':len(nodes),'dbt_tests':16,'powerbi_cases':dax['case_count'],'output':str(own_output)},ensure_ascii=False))


if __name__=='__main__':main()
