"""Explicit analysis relationships. Content payloads never identify a fact row."""
import json
from pathlib import Path

from scripts.prepare_powerbi import PROJECT,write_json

RELATIONSHIPS = [
    ('CityJobs','job_key','Jobs','job_key'),('SkillJobs','job_key','Jobs','job_key'),
    ('Pairs','job_key','Jobs','job_key'),('Evidence','job_key','Jobs','job_key'),
    ('Jobs','build_id','Builds','build_id'),('SkillJobs','skill_name','Skills','skill_name'),
    ('Evidence','skill_name','Skills','skill_name'),
    ('QualityKpi','source','SnapshotSources','source'),('SnapshotJobs','source','SnapshotSources','source'),
    ('SnapshotJobs','date_key','Calendar','date_key'),('SnapshotDays','date_key','Calendar','date_key'),
    ('SnapshotCityJobs','snapshot_key','SnapshotJobs','snapshot_key'),
    ('SnapshotSkillJobs','snapshot_key','SnapshotJobs','snapshot_key'),
    ('SnapshotEvidence','snapshot_key','SnapshotJobs','snapshot_key'),
    ('SnapshotSkillJobs','skill_name','SnapshotSkills','skill_name'),
    ('SnapshotEvidence','skill_name','SnapshotSkills','skill_name'),
    ('QualificationEvidence','snapshot_key','SnapshotJobs','snapshot_key'),
]


def signature(r):
    return tuple(r[k] for k in ('fromTable','fromColumn','toTable','toColumn'))


def validate_model(document):
    m=document['model'];tables={t['name']:t for t in m['tables']}
    wanted={r for r in RELATIONSHIPS if r[0] in tables and r[2] in tables}
    actual=[signature(r) for r in m['relationships']]
    if len(actual)!=len(set(actual)) or set(actual)!=wanted:
        raise ValueError('Unexpected/missing relationships; do not accept Desktop auto-detection')
    for r in m['relationships']:
        if r.get('crossFilteringBehavior','oneDirection')!='oneDirection':
            raise ValueError('Only declared single-direction dimension filtering is supported')
        for side in ('from','to'):
            table=tables[r[side+'Table']]
            col=next(c for c in table['columns'] if c['name']==r[side+'Column'])
            if side=='from':left=col['dataType']
            elif left!=col['dataType']:raise ValueError('Relationship key types differ')
    if 'Jobs' in tables:
        assert 'source_category_group' in {c['name'] for c in tables['Jobs']['columns']}
        assert 'category_group' not in {c['name'] for c in tables['Jobs']['columns']}
    return {'status':'passed','relationship_count':len(actual),'tables':len(tables)}


def fix_model(document):
    m=document['model']
    # The explicit Calendar handles analysis dates. Discard only generated auto calendars.
    m['tables']=[t for t in m['tables'] if not t['name'].startswith(('LocalDateTable_','DateTableTemplate_'))]
    names={t['name'] for t in m['tables']}
    for table in m['tables']:
        for c in table.get('columns',[]):c.pop('variations',None)
        if table['name']=='Jobs':
            table['description']='固定历史CD构建的来源岗位投影；source_category_group是官网原类别，不是标准岗位类别。'
            for c in table['columns']:
                if c['name']=='category_group':c.update(name='source_category_group',sourceColumn='source_category_group')
            for part in table['partitions']:
                expr=part['source']['expression']
                if isinstance(expr,list):expr='\n'.join(expr)
                part['source']['expression']=expr.replace('AS category_group','AS source_category_group')
    m['relationships']=[{'name':f'DW_{i:02d}','fromTable':ft,'fromColumn':fc,'toTable':tt,'toColumn':tc,
                         'crossFilteringBehavior':'oneDirection'}
        for i,(ft,fc,tt,tc) in enumerate(RELATIONSHIPS) if ft in names and tt in names]
    annotations={a['name']:a for a in m.get('annotations',[])}
    annotations['__PBI_TimeIntelligenceEnabled']={'name':'__PBI_TimeIntelligenceEnabled','value':'0'}
    annotations['PBI_QueryOrder']={'name':'PBI_QueryOrder','value':json.dumps([t['name'] for t in m['tables']])}
    m['annotations']=list(annotations.values())
    # Auto-generated Q&A metadata carries names from before the source-category rename.
    m.pop('linguisticMetadata',None)
    validate_model(document)
    return document


def rename_visual_fields(value):
    if isinstance(value,list):return [rename_visual_fields(x) for x in value]
    if not isinstance(value,dict):
        if isinstance(value,str):return value.replace('Jobs.category_group','Jobs.source_category_group')
        return value
    value={k:rename_visual_fields(v) for k,v in value.items()}
    for kind in ('Column','Measure'):
        field=value.get(kind,{})
        if field.get('Expression',{}).get('SourceRef',{}).get('Entity')=='Jobs' and field.get('Property')=='category_group':
            field['Property']='source_category_group'
    return value


def main():
    p=PROJECT/'Recruitment.SemanticModel/model.bim'
    write_json(p,fix_model(json.loads(p.read_text(encoding='utf-8'))))
    for page in ('overview','skills','evidence'):
        for path in (PROJECT/f'Recruitment.Report/definition/pages/{page}').rglob('*.json'):
            old=json.loads(path.read_text(encoding='utf-8'));new=rename_visual_fields(old)
            if new!=old:write_json(path,new)
    print(validate_model(json.loads(p.read_text(encoding='utf-8'))))


if __name__=='__main__':main()
