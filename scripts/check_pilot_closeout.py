"""Audit fixed pilot evidence without impersonating human reviewers or changing source batches."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
import hashlib
import importlib
import json
from pathlib import Path

from scripts.prepare_powerbi import ROOT,write_json
from warehouse.integrate_analysis import prepare,body_digest
from warehouse.load import connect
from warehouse.normalization import classify,VERSION
from warehouse.qualifications import resolve,RULE_VERSION
from warehouse.release_build import records,implementation_hash
from warehouse.validate import validate
from etl.skills.extract import FIELDS

OUT=ROOT/'reports/verification/pilot_closeout_20261120'


def find_record(value,key,identity):
    if isinstance(value,dict):
        if str(value.get(key))==identity:return value
        children=value.values()
    elif isinstance(value,list):children=value
    else:return None
    for child in children:
        found=find_record(child,key,identity)
        if found is not None:return found
    return None


def audit(database=None):
    config=json.loads((ROOT/'warehouse/pipeline.json').read_text(encoding='utf-8'))
    sources=[];jobs={};evidence=defaultdict(list);qualifications=[];directions=[];anchors=0
    for item in config['inputs']:
        batch=ROOT/item['batch_path'];checked=validate(batch);source=checked['manifest']['source']
        mapper=importlib.import_module('collectors.'+source+'.mapping')
        for job in checked['jobs']:
            refs=job['raw_refs'];key='PostId' if source=='tencent' else 'id'
            post=find_record(json.loads((batch/refs[0]['path']).read_text(encoding='utf-8')),key,job['source_job_id'])
            detail=find_record(json.loads((batch/refs[1]['path']).read_text(encoding='utf-8')),key,job['source_job_id']) if len(refs)>1 else None
            assert post is not None and (len(refs)==1 or detail is not None)
            if source=='tencent':rebuilt=mapper.build_job(post,detail,job['batch_id'],job['observed_at'],refs[0],refs[1],job['parser_version'])
            else:rebuilt=mapper.build_job(post,detail,job['batch_id'],job['observed_at'],refs[0],job['parser_version'],refs[1] if len(refs)>1 else None)
            assert rebuilt==job,(source,job['source_job_id'],'collector mapping differs')
        _,_,_,rows,enriched,_=prepare(batch,ROOT/item['analysis_path'],ROOT/item['dictionary_path'])
        # Independent historical field decisions must survive a skills-rule rebuild.
        prior=ROOT/'reports/analysis'/checked['manifest']['batch_id']/'v1.1'
        historical=prepare(batch,prior,ROOT/item['dictionary_path'])[4]
        flags=lambda data:{j['source_job_id']:(j['location_conflict'],j['experience_conflict'],j['experience_hint']) for j in data}
        assert flags(enriched)==flags(historical),(source,'reviewed field findings lost')
        source_anchors=0
        for job in enriched:
            identity=source+'|'+job['source_job_id'];jobs[identity]=job;labels=classify(job);q=labels['qualifications']
            for name,resolution in q.items():
                for anchor in resolution['evidence']:
                    text=job.get(anchor['field']) or ''
                    assert text[anchor['start']:anchor['end']]==anchor['text'],(identity,name,'qualification anchor')
                    anchors+=1
            if source=='tencent':
                raw=json.loads((batch/job['detail_ref']['path']).read_text(encoding='utf-8'))['Data']
                assert job.get('additional_requirements_raw')==((raw.get('ImportantItem') or '').strip() or None)
            if any(q[k]['status']=='conflict' for k in ('education','experience')):
                qualifications.append({'case_id':identity,'title_raw':job['title_raw'],'is_core':job['is_core'],
                    'resolutions':q,'decision':'retain_explicit_conflict','review_kind':'AI_assisted_source_evidence_review',
                    'reason':'Source structured value and body requirements remain separately traceable; do not silently choose one.',
                    'raw_ref':job['detail_ref'],'human_reviewer':None})
            directions.append({'case_id':identity,'title_raw':job['title_raw'],'is_core':job['is_core'],
                'primary_direction':labels['category'],'normalization_version':VERSION,
                'decision':'AI/model domain first, then data, testing, operations/security, development; this axis is primary direction, not occupational function.',
                'review_kind':'AI_assisted_rule_and_title_review','human_reviewer':None})
        for row in rows:
            job=jobs[source+'|'+row['source_job_id']];text=job.get(row['evidence_field']) or ''
            assert text[row['evidence_start']:row['evidence_end']]==row['evidence']
            assert text[row['match_start']:row['match_end']]==row['matched_text']
            evidence[source+'|'+row['source_job_id']].append(row);source_anchors+=1
        sources.append({'source':source,'jobs':len(checked['jobs']),'collector_fields_roundtripped':sum(len(j) for j in checked['jobs']),
            'manifest_files_checked':len(checked['files']),'requests':checked['summary']['requests'],
            'skill_evidence_anchors_checked':source_anchors,'coverage_status':checked['manifest']['coverage_status'],
            'stop_reason':checked['manifest']['stop_reason'],'input_hash':checked['input_hash']})
    packet=ROOT/'reports/verification/review_100/blinded_jobs.jsonl'
    plan=json.loads((packet.parent/'plan.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(packet.read_bytes()).hexdigest()==plan['packet_sha256']
    reviews=[]
    for row in map(json.loads,packet.read_text(encoding='utf-8').splitlines()):
        job=jobs[row['case_id']]
        assert body_digest(job,FIELDS)==row['body_sha256']
        assert {f:job.get(f) for f in FIELDS}==row['fields']
        candidates=evidence[row['case_id']]
        reviews.append({'case_id':row['case_id'],'title_raw':row['title_raw'],'body_sha256':row['body_sha256'],
            'audit_kind':'AI_assisted_non_blind_evidence_audit','actor':'Codex AI','human_reviewer':None,
            'status':'source_and_spans_reconciled','evidence_rows':len(candidates),
            'eligible_skills':sorted({r['skill_name'] for r in candidates if r['eligible_for_metric']}),
            'excluded_contexts':list(dict.fromkeys(r['evidence'] for r in candidates if not r['eligible_for_metric'])),
            'raw_ref':row['raw_ref'],
            'scope_note':'Candidate evidence and exclusion contexts audited; not an independent blinded gold annotation or a recall estimate.'})
    assert len(reviews)==100 and len({r['case_id'] for r in reviews})==100
    assert Counter(r['case_id'].split('|')[0] for r in reviews)=={'netease':50,'tencent':50}
    OUT.mkdir(parents=True,exist_ok=True)
    for name,data in [('ai_skill_evidence_audit.jsonl',reviews),('qualification_conflict_dispositions.jsonl',qualifications),('primary_direction_review.jsonl',directions)]:
        (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in data),encoding='utf-8',newline='\n')
    result={'checked_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'status':'passed_for_pilot_evidence_scope',
        'normalization_version':VERSION,'qualification_rule_version':RULE_VERSION,'sources':sources,
        'jobs':len(jobs),'core_jobs':sum(j['is_core'] for j in jobs.values()),'qualification_anchors_checked':anchors,
        'skill_audit_jobs':len(reviews),'skill_audit_kind':'AI_assisted_non_blind_evidence_audit',
        'human_gold_annotation_completed':False,'human_precision':None,'human_recall':None,
        'original_human_packet_unchanged':True,'qualification_conflict_cases':len(qualifications),
        'historical_field_findings_preserved':True,
        'primary_direction_cases':len(directions),'database_checked':False}
    if database:
        c=connect(database)
        try:
            rid=c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()
            actual=records(c,'''SELECT source,source_job_id,category_group,education_group,experience_group,
                employment_type_group,is_core FROM ads.release_job_detail WHERE release_id=?''',rid)
            assert len(actual)==200
            for row in actual:
                expected=classify(jobs[row['source']+'|'+row['source_job_id']])
                for output,label in [('category_group','category'),('education_group','education'),('experience_group','experience'),('employment_type_group','employment_type')]:
                    assert row[output]==expected[label],(row['source_job_id'],output)
            assert c.execute('SELECT code_sha256 FROM audit.model_build WHERE release_id=?',rid).fetchval()==implementation_hash()
            assert c.execute('SELECT COUNT(*) FROM ads.release_validation WHERE release_id=?',rid).fetchval()==0
            result.update(database_checked=True,database=database,release_id=rid,
                category_counts=dict(Counter(r['category_group'] for r in actual if r['is_core'])),
                employment_types={s:dict(Counter(r['employment_type_group'] for r in actual if r['source']==s and r['is_core'])) for s in ('netease','tencent')})
        finally:c.close()
    write_json(OUT/'evidence_audit.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database');a=p.parse_args()
    print(json.dumps(audit(a.database),ensure_ascii=False))
