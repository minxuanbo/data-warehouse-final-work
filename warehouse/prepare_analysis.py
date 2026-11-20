"""Prepare reproducible three-field evidence for an arbitrary accepted source batch."""
import argparse
import json
from pathlib import Path
from copy import deepcopy

from etl.skills.extract import extract,RULE_VERSION,BODY_HASH_VERSION,FIELDS
from etl.skills.run import check_dictionary
from .analysis_v11 import raw_post
from .integrate_analysis import body_digest,prepare
from .load import ROOT,dump
from .validate import validate,digest
from .source_catalog import SOURCES


def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')


def generate(batch_path,output_path,dictionary_path=None,policy_path=None,reviewed_analysis_path=None):
    checked=validate(batch_path);batch=checked['root'];m=checked['manifest'];source=m['source']
    if m['acceptance_status']!='accepted':raise ValueError('Pending batches require real technical review before integration')
    dictionary_path=Path(dictionary_path or ROOT/'etl/skills/dictionary.json')
    dictionary_bytes=dictionary_path.read_bytes();dictionary=json.loads(dictionary_bytes);check_dictionary(dictionary)
    policy=deepcopy(json.loads(Path(policy_path or ROOT/'warehouse/cd_policy_v12.json').read_text(encoding='utf-8')))
    ids={j['source_job_id'] for j in checked['jobs']}
    sp=policy['sources'][source]
    sp['excluded_jobs']={k:v for k,v in sp['excluded_jobs'].items() if k in ids}
    sp['additional_locations']={k:v for k,v in sp['additional_locations'].items() if k in ids}
    sp['experience_hint_only']=[k for k in sp['experience_hint_only'] if k in ids]
    # Unrelated source decisions must not invalidate this source's frozen build.
    policy['sources']={source:sp}
    # Freeze the exact policy alongside evidence, so future config changes cannot rewrite this build.
    policy_bytes=(json.dumps(policy,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    # A skill-only rebuild must retain field findings reviewed against this exact raw batch.
    # prepare() verifies source/batch, manifest, jobs, dictionary and every raw reference;
    # an annotation from another observation cannot silently leak into a new batch.
    reviewed_issues=[];review_source=None
    if reviewed_analysis_path:
        prior=Path(reviewed_analysis_path).resolve()
        prior_prepared=prepare(batch,prior,dictionary_path)
        reviewed_issues=[r for r in map(json.loads,(prior/'data_issues.jsonl').read_text(encoding='utf-8').splitlines())
                         if r['kind'] in {'location_conflict','experience_conflict','education_conflict'}]
        review_source={'analysis_path':prior.relative_to(ROOT).as_posix() if prior.is_relative_to(ROOT) else str(prior),
                       'validated_input_hash':prior_prepared[-1],
                       'data_issues_sha256':digest((prior/'data_issues.jsonl').read_bytes()),
                       'input_provenance_sha256':digest((prior/'input_provenance.json').read_bytes()),
                       'scope':'existing field findings for identical immutable source batch; not new human signoff'}
    output=Path(output_path).resolve()
    if output==batch or output.is_relative_to(batch) or batch.is_relative_to(output):raise ValueError('Analysis output must be separate from raw input')
    if output.exists():
        prepared=prepare(batch,output,dictionary_path)
        if prepared[1].get('scope_policy_sha256')!=digest(policy_bytes):raise ValueError('Existing output uses another policy; choose a new version directory')
        if prepared[1].get('field_review_source')!=review_source:raise ValueError('Existing output uses another field review; choose a new version directory')
        return {'status':'unchanged','analysis_path':str(output),'input_hash':prepared[-1]}
    jobs=[];issues=[]
    issue_kinds={'location_conflict','experience_conflict','education_conflict'}
    for job in checked['jobs']:
        refs=[r for r in job['raw_refs'] if r['path'].startswith('raw/detail_')]
        ref=refs[0] if refs else job['raw_refs'][0]
        raw,raw_hash=raw_post(batch,ref['path'],source,job['source_job_id'])
        row={**job,'additional_requirements_raw':(raw.get('ImportantItem') or None) if source=='tencent' else None,
             'is_core':job['source_job_id'] not in sp['excluded_jobs'],'_ref':ref}
        jobs.append(row)
        for issue in checked['issues']:
            kind=issue.get('rule')
            if issue.get('source_job_id')==job['source_job_id'] and kind in issue_kinds:
                issues.append({'source':source,'source_job_id':job['source_job_id'],'kind':kind,
                               'raw_ref':ref['path'],'treatment':'保留原值，冲突单列，按版本策略裁定'})
    # Reviewed rows carry the richer evidence. Prefer them to collector-only flags.
    issues=list({(r['source_job_id'],r['kind']):r for r in issues+reviewed_issues}.values())
    raw_fields=SOURCES[source]['raw_fields']
    evidence=[{**r,'body_sha256':body_digest(j,FIELDS),'body_hash_version':BODY_HASH_VERSION,
               'is_core':j['is_core'],'scope_rule_version':policy['scope_version'],
               'raw_ref':j['_ref']['path'],'raw_sha256':j['_ref']['sha256'],'raw_field_name':raw_fields[r['evidence_field']]}
              for j in jobs for r in extract(j,dictionary)]
    pairs={(r['source_job_id'],r['skill_name']) for r in evidence if r['is_core'] and r['eligible_for_metric']}
    provenance={'source':source,'batch_id':m['batch_id'],'jobs_sha256':digest((batch/'jobs.jsonl').read_bytes()),
                'manifest_sha256':digest((batch/'manifest.json').read_bytes()),'dictionary_sha256':digest(dictionary_bytes),
                'dictionary_version':dictionary['version'],'rule_version':RULE_VERSION,'body_hash_version':BODY_HASH_VERSION,
                'body_hash_fields':list(FIELDS),'scope_version':policy['scope_version'],'scope_policy_sha256':digest(policy_bytes),
                'source_postings':len(jobs),'core_postings':sum(j['is_core'] for j in jobs),
                'extraction_code_sha256':digest((ROOT/'etl/skills/extract.py').read_bytes()),
                'review_status':'automated_evidence_not_human_labels'}
    if review_source:provenance['field_review_source']=review_source
    output.mkdir(parents=True,exist_ok=False)
    try:
        (output/'scope_policy.json').write_bytes(policy_bytes)
        for name,rows in [('skill_evidence.jsonl',evidence),('data_issues.jsonl',issues)]:
            (output/name).write_text(''.join(dump(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
        write_json(output/'input_provenance.json',provenance)
        write_json(output/'reconciliation.json',{'core_ids':sorted(j['source_job_id'] for j in jobs if j['is_core']),
                                                'core_effective_posting_skill_pairs':len(pairs)})
        prepared=prepare(batch,output,dictionary_path)
        return {'status':'prepared','analysis_path':str(output),'source_postings':len(jobs),'core_postings':provenance['core_postings'],
                'posting_skill_pairs':len(pairs),'input_hash':prepared[-1]}
    except Exception:
        # Keep failed evidence visible for diagnosis; never silently reuse an incomplete directory.
        (output/'FAILED.txt').write_text('Preparation failed; do not ingest. Use a new output directory after correction.\n',encoding='utf-8')
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('batch');p.add_argument('--output',required=True)
    p.add_argument('--dictionary');p.add_argument('--policy');p.add_argument('--reviewed-analysis');a=p.parse_args()
    print(json.dumps(generate(a.batch,a.output,a.dictionary,a.policy,a.reviewed_analysis),ensure_ascii=False))
