"""Three-field evidence preparation with source-specific C scope decisions."""
import json
from collections import defaultdict
from pathlib import Path

from .integrate_analysis import check_evidence
from .load import ROOT, dump
from .validate import digest, jsonl, safe_path, validate


def raw_post(batch, reference, source, identity):
    raw = safe_path(batch, reference).read_bytes()
    payload = json.loads(raw)
    if source == 'tencent':
        post = payload['Data']
        if str(post['PostId']) != identity:
            raise ValueError('Tencent raw identity mismatch')
    else:
        data = payload['data']
        matches = [post for post in data.get('list', []) if str(post.get('id')) == identity] if 'list' in data else [data]
        if len(matches) != 1 or str(matches[0]['id']) != identity:
            raise ValueError('NetEase raw identity mismatch')
        post = matches[0]
    return post, digest(raw)


def prepare_v11(batch_path, analysis_path, dictionary_path):
    checked = validate(batch_path)
    batch = checked['root']
    manifest = checked['manifest']
    analysis = Path(analysis_path)
    provenance = json.loads((analysis / 'input_provenance.json').read_text(encoding='utf-8'))
    policy = json.loads((ROOT / 'warehouse/cd_policy_v12.json').read_text(encoding='utf-8'))
    fields = policy['skill_input_fields']
    if provenance['body_hash_fields'] != fields or provenance['body_hash_version'] != policy['body_hash_version']:
        raise ValueError('Unsupported three-field hash definition')
    if provenance['source'] != manifest['source'] or provenance['batch_id'] != manifest['batch_id']:
        raise ValueError('Analysis source/batch mismatch')
    if manifest['acceptance_status'] != 'accepted':
        raise ValueError('Accepted batch required')
    for file_name, key in [('jobs.jsonl','jobs_sha256'), ('manifest.json','manifest_sha256')]:
        if digest((batch / file_name).read_bytes()) != provenance[key]:
            raise ValueError('Input file differs from D provenance')
    dictionary_bytes = Path(dictionary_path).read_bytes()
    dictionary = json.loads(dictionary_bytes)
    if digest(dictionary_bytes) != provenance['dictionary_sha256'] or dictionary['version'] != provenance['dictionary_version']:
        raise ValueError('Dictionary version/hash mismatch')
    skill_names = {row['name'] for row in dictionary['skills']}
    if len(skill_names) != len(dictionary['skills']):
        raise ValueError('Duplicate dictionary skill')
    source = manifest['source']
    source_policy = policy['sources'][source]
    jobs = {row['source_job_id']: row for row in checked['jobs']}
    if not set(source_policy['excluded_jobs']).issubset(jobs):
        raise ValueError('Scope decision references absent jobs')
    issue_rows = jsonl(analysis / 'data_issues.jsonl')
    by_job = defaultdict(list)
    for issue in issue_rows:
        identity = issue['source_job_id']
        if identity not in jobs or issue['source'] != source:
            raise ValueError('Issue source identity mismatch')
        if issue['raw_ref'] not in checked['files']:
            raise ValueError('Issue reference not in manifest')
        raw_post(batch, issue['raw_ref'], source, identity)
        by_job[identity].append(issue)
    enriched = []
    for identity, job in jobs.items():
        refs = [ref for ref in job['raw_refs'] if ref['path'].startswith('raw/detail_')]
        reference = refs[0] if refs else job['raw_refs'][0]
        raw, raw_hash = raw_post(batch, reference['path'], source, identity)
        if reference['sha256'] != raw_hash:
            raise ValueError('Raw reference hash mismatch')
        locations = list(dict.fromkeys(job['locations_raw'] or []))
        extra = source_policy['additional_locations'].get(identity)
        if extra:
            if extra['evidence'] not in (raw.get(extra['evidence_field']) or ''):
                raise ValueError('Additional location evidence missing')
            locations = list(dict.fromkeys(locations + extra['locations']))
        kinds = {issue['kind'] for issue in by_job[identity]}
        hint_only = identity in source_policy['experience_hint_only']
        enriched.append({
            **job,
            'additional_requirements_raw': raw.get('ImportantItem') or None if source == 'tencent' else None,
            'location_notes_raw': raw.get('PostLightItem') or None if source == 'tencent' else None,
            'is_core': identity not in source_policy['excluded_jobs'],
            'scope_reason': source_policy['excluded_jobs'].get(identity, '核心数字技术岗位'),
            'location_conflict': 'location_conflict' in kinds,
            'education_conflict': 'education_conflict' in kinds,
            'experience_hint': 'experience_conflict' in kinds,
            'experience_conflict': 'experience_conflict' in kinds and not hint_only,
            'confirmed_locations': locations, 'issues': by_job[identity], 'detail_ref': reference,
        })
    enriched_by_id = {row['source_job_id']: row for row in enriched}
    evidence = jsonl(analysis / 'skill_evidence.jsonl')
    seen = set()
    raw_fields = {'tencent': {'description_raw':'Responsibility','requirements_raw':'Requirement','additional_requirements_raw':'ImportantItem'},
                  'netease': {'description_raw':'description','requirements_raw':'requirement'}}
    for row in evidence:
        check_evidence(row, enriched_by_id, skill_names, provenance)
        identity = row['source_job_id']
        job = enriched_by_id[identity]
        if type(row['is_core']) is not bool or row['is_core'] != job['is_core']:
            raise ValueError('D core flag differs from C decision')
        if row['body_hash_version'] != 'skills-body-1.1' or row['scope_rule_version'] != provenance['scope_version']:
            raise ValueError('Evidence version mismatch')
        ref = row['raw_ref']
        if ref not in {item['path'] for item in job['raw_refs']}:
            raise ValueError('Evidence reference outside job lineage')
        raw, raw_hash = raw_post(batch, ref, source, identity)
        field_name = raw_fields[source].get(row['evidence_field'])
        if row['raw_sha256'] != raw_hash or row['raw_field_name'] != field_name:
            raise ValueError('Evidence raw hash/field mismatch')
        if (raw.get(field_name) or '').strip() != (job[row['evidence_field']] or '').strip():
            raise ValueError('Raw evidence differs from normalized body')
        key = (identity, row['skill_name'], row['evidence_field'], row['match_start'], row['match_end'])
        if key in seen:
            raise ValueError('Duplicate evidence row')
        seen.add(key)
    reconciliation = json.loads((analysis / 'reconciliation.json').read_text(encoding='utf-8'))
    core = {row['source_job_id'] for row in enriched if row['is_core']}
    pairs = {(row['source_job_id'],row['skill_name']) for row in evidence if row['is_core'] and row['eligible_for_metric']}
    if set(reconciliation['core_ids']) != core or reconciliation['core_effective_posting_skill_pairs'] != len(pairs):
        raise ValueError('D reconciliation differs from validated evidence')
    if provenance['core_postings'] != len(core) or provenance['source_postings'] != len(jobs):
        raise ValueError('D denominator differs from C scope')
    provenance = {**provenance, 'c_scope_decision': {'version':policy['scope_version'], 'status':'confirmed_by_C',
                   'excluded_jobs':source_policy['excluded_jobs'], 'experience_hint_only':source_policy['experience_hint_only']}}
    hashes = {name:digest((analysis/name).read_bytes()) for name in
              ('input_provenance.json','skill_evidence.jsonl','data_issues.jsonl','reconciliation.json')}
    hashes.update(dictionary=digest(dictionary_bytes), policy=digest(dump(policy).encode()), manifest=checked['input_hash'])
    return checked, provenance, policy, evidence, enriched, digest(dump(hashes).encode())
