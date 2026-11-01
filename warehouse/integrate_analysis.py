"""Validate D's evidence and atomically build versioned C/D integration results."""
import csv
import json
from collections import defaultdict
from pathlib import Path

from .load import ROOT, connect, dump
from .validate import digest, jsonl, safe_path, validate


def body_digest(job):
    fields = [job.get('description_raw'), job.get('requirements_raw')]
    return digest(json.dumps(fields, ensure_ascii=False).encode('utf-8'))


def check_evidence(row, jobs, skills, provenance):
    identity = row['source_job_id']
    if identity not in jobs:
        raise ValueError('Skill references an unknown job')
    job = jobs[identity]
    if row['source'] != job['source'] or row['batch_id'] != job['batch_id']:
        raise ValueError('Skill identity mismatch')
    if row['skill_name'] not in skills:
        raise ValueError('Skill absent from dictionary')
    if row['dictionary_version'] != provenance['dictionary_version'] or row['rule_version'] != provenance['rule_version']:
        raise ValueError('Skill rule version mismatch')
    if row['evidence_field'] not in ('description_raw', 'requirements_raw'):
        raise ValueError('Current D rule only covers two body fields')
    body = job[row['evidence_field']] or ''
    start, end = row['evidence_start'], row['evidence_end']
    match_start, match_end = row['match_start'], row['match_end']
    if any(type(value) is not int for value in (start, end, match_start, match_end)):
        raise ValueError('Evidence offsets must be integers')
    if not 0 <= start <= match_start < match_end <= end <= len(body):
        raise ValueError('Evidence offsets outside body')
    if body[start:end] != row['evidence'] or body[match_start:match_end] != row['matched_text']:
        raise ValueError('Evidence does not match source text')
    if row['body_sha256'] != body_digest(job):
        raise ValueError('D body hash mismatch')
    if row['requirement_level'] not in ('必需', '优先', '提及', '不确定'):
        raise ValueError('Unknown requirement level')
    expected = row['context_polarity'] == 'positive' and row['requirement_level'] in ('必需', '优先', '提及')
    if type(row['eligible_for_metric']) is not bool or row['eligible_for_metric'] != expected:
        raise ValueError('Metric eligibility disagrees with evidence context')


def prepare(batch_path, analysis_path, dictionary_path):
    checked = validate(batch_path)
    batch = checked['root']
    analysis = Path(analysis_path)
    provenance = json.loads((analysis / 'input_provenance.json').read_text(encoding='utf-8'))
    dictionary_bytes = Path(dictionary_path).read_bytes()
    dictionary = json.loads(dictionary_bytes)
    for path, expected in [(batch / 'jobs.jsonl', provenance['jobs_sha256']),
                           (batch / 'manifest.json', provenance['manifest_sha256'])]:
        if digest(path.read_bytes()) != expected:
            raise ValueError('D provenance references another input revision')
    if digest(dictionary_bytes) != provenance['dictionary_sha256']:
        raise ValueError('D dictionary hash mismatch')
    if checked['manifest']['acceptance_status'] != 'accepted':
        raise ValueError('C/D baseline requires technical acceptance')
    if dictionary['version'] != provenance['dictionary_version']:
        raise ValueError('Dictionary version mismatch')
    skills = {skill['name'] for skill in dictionary['skills']}
    if len(skills) != len(dictionary['skills']):
        raise ValueError('Duplicate skill names')
    jobs = {row['source_job_id']: row for row in checked['jobs']}
    evidence = jsonl(analysis / 'skill_evidence.jsonl')
    seen = set()
    for row in evidence:
        check_evidence(row, jobs, skills, provenance)
        key = (row['source_job_id'], row['skill_name'], row['evidence_field'], row['match_start'], row['match_end'])
        if key in seen:
            raise ValueError('Duplicate skill evidence')
        seen.add(key)
    with (analysis / 'data_issues.csv').open(encoding='utf-8-sig', newline='') as handle:
        issues = list(csv.DictReader(handle))
    by_job = defaultdict(list)
    for issue in issues:
        identity = issue['source_job_id']
        if identity not in jobs or issue['batch_id'] != checked['manifest']['batch_id'] or issue['source'] != checked['manifest']['source']:
            raise ValueError('Issue identity mismatch')
        if digest(safe_path(batch, issue['raw_ref']).read_bytes()) != issue['raw_sha256']:
            raise ValueError('Issue raw hash mismatch')
        by_job[identity].append(issue)
    policy_bytes = (ROOT / 'warehouse/cd_policy.json').read_bytes()
    policy = json.loads(policy_bytes)
    if not set(policy['excluded_jobs']).issubset(jobs):
        raise ValueError('Policy refers to absent jobs')
    enriched = []
    for identity, job in jobs.items():
        detail_refs = [ref for ref in job['raw_refs'] if ref['path'].startswith('raw/detail_')]
        if len(detail_refs) != 1:
            raise ValueError('Expected one Tencent detail per job')
        ref = detail_refs[0]
        raw = json.loads(safe_path(batch, ref['path']).read_bytes())['Data']
        if str(raw['PostId']) != identity:
            raise ValueError('Detail belongs to another job')
        locations = list(dict.fromkeys(job['locations_raw'] or []))
        extra = policy['additional_locations'].get(identity)
        if extra:
            if extra['evidence'] not in (raw.get(extra['evidence_field']) or ''):
                raise ValueError('Reviewed extra location evidence missing')
            locations = list(dict.fromkeys(locations + extra['locations']))
        types = {issue['type'] for issue in by_job[identity]}
        enriched.append({
            **job,
            'additional_requirements_raw': raw.get('ImportantItem') or None,
            'location_notes_raw': raw.get('PostLightItem') or None,
            'is_core': identity not in policy['excluded_jobs'],
            'scope_reason': policy['excluded_jobs'].get(identity, '保留于核心数字技术岗位集合'),
            'scope_rule_version': policy['scope_version'],
            'enrichment_version': policy['enrichment_version'],
            'location_conflict': '标题与地点完全无交集' in types,
            'experience_conflict': '经验口径差异' in types,
            'confirmed_locations': locations,
            'issues': by_job[identity], 'detail_ref': ref,
        })
    hashes = {name: digest((analysis / name).read_bytes()) for name in
              ('input_provenance.json', 'skill_evidence.jsonl', 'data_issues.csv')}
    hashes.update(dictionary=digest(dictionary_bytes), policy=digest(policy_bytes), manifest=checked['input_hash'])
    return checked, provenance, policy, evidence, enriched, digest(dump(hashes).encode())


def integrate(batch_path, analysis_path, dictionary_path, *, fail_after=None):
    checked, provenance, policy, evidence, enriched, input_hash = prepare(batch_path, analysis_path, dictionary_path)
    connection = connect()
    try:
        connection.execute('SET XACT_ABORT ON; BEGIN TRANSACTION;')
        connection.execute("DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource='warehouse_cd_build',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000; IF @r<0 THROW 50002,'build lock timeout',1;")
        batch_id = checked['manifest']['batch_id']
        stored = connection.execute('SELECT input_hash FROM audit.collection_batch WHERE batch_id=?', batch_id).fetchone()
        if not stored or stored[0] != checked['input_hash']:
            raise ValueError('Warehouse batch differs from D input')
        old = connection.execute('SELECT build_id FROM audit.analysis_build WHERE input_hash=?', input_hash).fetchone()
        if old:
            connection.execute('COMMIT TRANSACTION;')
            return {'status': 'unchanged', 'build_id': old[0]}
        build_id = connection.execute('INSERT INTO audit.analysis_build(input_hash,batch_id,scope_version,dictionary_version,rule_version,provenance_json,status) OUTPUT INSERTED.build_id VALUES(?,?,?,?,?,?,?)',
                                      input_hash, batch_id, policy['scope_version'], provenance['dictionary_version'], provenance['rule_version'], dump(provenance), 'building').fetchval()
        identities = connection.execute('SELECT i.source_job_id,o.observation_key,o.version_key FROM dwd.fact_posting_observation o JOIN dim.posting_identity i ON i.posting_key=o.posting_key WHERE o.batch_id=?', batch_id).fetchall()
        keys = {row[0]: (row[1], row[2]) for row in identities}
        if len(identities) != len(enriched) or set(keys) != {row['source_job_id'] for row in enriched}:
            raise ValueError('Warehouse identity set mismatch')
        for index, row in enumerate(enriched, 1):
            observation_key, _ = keys[row['source_job_id']]
            connection.execute('INSERT INTO dwd.observation_enrichment VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                               build_id, observation_key, row['is_core'], row['scope_reason'], row['additional_requirements_raw'],
                               row['location_notes_raw'], row['location_conflict'], row['experience_conflict'],
                               dump(row['confirmed_locations']), dump(row['issues']), row['detail_ref']['path'], row['detail_ref']['sha256'])
            if fail_after == index:
                raise RuntimeError('Injected C/D build failure')
        grouped = defaultdict(list)
        for row in evidence:
            version_key = keys[row['source_job_id']][1]
            key = (version_key, row['skill_name'], row['requirement_level'], row['eligible_for_metric'])
            grouped[key].append(row)
        for (version_key, name, level, eligible), rows in grouped.items():
            existing = connection.execute('SELECT skill_key FROM dim.skill WHERE skill_name=?', name).fetchone()
            skill_key = existing[0] if existing else connection.execute('INSERT INTO dim.skill(skill_name) OUTPUT INSERTED.skill_key VALUES(?)', name).fetchval()
            connection.execute('INSERT INTO dwd.bridge_version_skill VALUES(?,?,?,?,?,?,?)',
                               build_id, version_key, skill_key, level, eligible, len(rows), dump(rows))
        connection.execute("UPDATE audit.analysis_build SET status='ready' WHERE build_id=?", build_id)
        connection.execute('COMMIT TRANSACTION;')
        return {'status': 'ready', 'build_id': build_id, 'jobs': len(enriched),
                'core_jobs': sum(row['is_core'] for row in enriched), 'evidence': len(evidence), 'bridge_rows': len(grouped)}
    except Exception:
        connection.execute('IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;')
        raise
    finally:
        connection.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--analysis', required=True)
    parser.add_argument('--dictionary', required=True)
    args = parser.parse_args()
    print(json.dumps(integrate(args.batch, args.analysis, args.dictionary), ensure_ascii=False))
