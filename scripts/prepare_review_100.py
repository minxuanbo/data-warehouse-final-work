"""Freeze a blinded 100-job review packet; never manufacture human labels or scores."""
import argparse
import hashlib
import json
import random
from pathlib import Path

from scripts.check_skills_v11 import input_paths
from scripts.prepare_powerbi import ROOT,write_json
from warehouse.integrate_analysis import prepare,body_digest
from etl.skills.extract import FIELDS,extract

OUTPUT=ROOT/'reports/verification/review_100'


def create():
    reference=json.loads((ROOT/'etl/skills/reviewed_samples_v1_1.json').read_text(encoding='utf-8'))
    cases=[];prior=0
    for source,batch,analysis,dictionary in input_paths():
        checked,_,_,_,jobs,_=prepare(batch,analysis,dictionary)
        old=set(reference['sources'][source]['reviews'])
        known=[j for j in jobs if j['source_job_id'] in old]
        other=sorted((j for j in jobs if j['source_job_id'] not in old),key=lambda j:j['source_job_id'])
        random.Random(20261117).shuffle(other)
        selected=known+other[:50-len(known)]
        assert len(selected)==50
        prior+=len(known)
        for job in selected:
            cases.append({'case_id':source+'|'+job['source_job_id'],'source':source,'source_job_id':job['source_job_id'],
              'batch_id':job['batch_id'],'title_raw':job['title_raw'],'body_sha256':body_digest(job,FIELDS),
              'fields':{f:job.get(f) for f in FIELDS},'raw_ref':job['detail_ref'],
              'previous_frozen_reference_available':job['source_job_id'] in old,
              'reviewed':False,'reviewer':None,'note':None,'labels':None,'no_skills':False})
    OUTPUT.mkdir(parents=True,exist_ok=True)
    target=OUTPUT/'blinded_jobs.jsonl'
    content=''.join(json.dumps(j,ensure_ascii=False)+'\n' for j in cases)
    if target.exists() and target.read_text(encoding='utf-8')!=content:raise ValueError('Review packet differs; do not overwrite an existing review')
    target.write_text(content,encoding='utf-8')
    plan={'unit':'a distinct source job, not an evidence anchor','target_jobs':100,'jobs_per_source':50,
          'prior_reference_jobs':prior,'additional_jobs':100-prior,'packet_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
          'extractor_sha256':hashlib.sha256((ROOT/'etl/skills/extract.py').read_bytes()).hexdigest(),
          'dictionary_sha256':hashlib.sha256((ROOT/'etl/skills/dictionary.json').read_bytes()).hexdigest(),
          'status':'pending_human_review','scores':None,'note':'No extracted candidates included. Prior 40-job frozen holdout results remain separate.'}
    write_json(OUTPUT/'plan.json',plan)
    print(json.dumps({'packet':str(target),'prior_reference_jobs':prior,'additional_jobs':100-prior,'status':plan['status']},ensure_ascii=False))


def check(submission):
    plan=json.loads((OUTPUT/'plan.json').read_text(encoding='utf-8'))
    packet=OUTPUT/'blinded_jobs.jsonl'
    assert hashlib.sha256(packet.read_bytes()).hexdigest()==plan['packet_sha256'],'Packet changed'
    assert hashlib.sha256((ROOT/'etl/skills/extract.py').read_bytes()).hexdigest()==plan['extractor_sha256'],'Extractor changed'
    dictionary_bytes=(ROOT/'etl/skills/dictionary.json').read_bytes()
    assert hashlib.sha256(dictionary_bytes).hexdigest()==plan['dictionary_sha256'],'Dictionary changed'
    baseline={r['case_id']:r for r in map(json.loads,packet.read_text(encoding='utf-8').splitlines())}
    entries=[json.loads(x) for x in Path(submission).read_text(encoding='utf-8').splitlines() if x.strip()]
    if len(entries)!=100 or {r['case_id'] for r in entries}!=set(baseline):raise ValueError('Exactly the 100 frozen source jobs must be reviewed')
    pending=[];tp=fp=fn=0;dictionary=json.loads(dictionary_bytes);known={x['name'] for x in dictionary['skills']};outside=[]
    for row in entries:
        original=baseline[row['case_id']]
        if any(row.get(k)!=original[k] for k in ('source','source_job_id','batch_id','body_sha256','fields','raw_ref')):raise ValueError('Review body/provenance was altered')
        if row.get('reviewed') is not True or not row.get('reviewer') or not row.get('note'):
            pending.append(row['case_id']);continue
        if not isinstance(row.get('labels'),list) or (not row['labels'] and row.get('no_skills') is not True):raise ValueError('Mark actual labels or explicitly confirm no named skills')
        if row['labels'] and row.get('no_skills'):raise ValueError('Named labels and no_skills cannot both be true')
        expected=set()
        for label in row['labels']:
            if label.get('field') not in FIELDS or label.get('level') not in ('必需','优先','提及','不确定','否定'):raise ValueError('Invalid label field/level')
            if not label.get('evidence') or label['evidence'] not in (row['fields'][label['field']] or ''):raise ValueError('Label evidence must be copied from frozen text')
            if label['skill'] not in known:outside.append({'case_id':row['case_id'],'skill':label['skill']});continue
            if label['level'] in ('必需','优先','提及'):expected.add(label['skill'])
        job={**row['fields'],'source':row['source'],'source_job_id':row['source_job_id'],'batch_id':row['batch_id']}
        actual={r['skill_name'] for r in extract(job,dictionary) if r['eligible_for_metric']}
        tp+=len(actual&expected);fp+=len(actual-expected);fn+=len(expected-actual)
    result={'status':'pending' if pending else 'reviewed','reviewed_jobs':100-len(pending),'pending_jobs':pending,
            'audit_precision':None if pending or tp+fp==0 else tp/(tp+fp),'audit_recall':None if pending or tp+fn==0 else tp/(tp+fn),
            'dictionary_external_labels':outside,'note':'Additional audit; not a replacement for the earlier frozen holdout evaluation.'}
    write_json(OUTPUT/'review_result.json',result);print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--submission');a=p.parse_args()
    check(a.submission) if a.submission else create()
