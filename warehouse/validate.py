"""Validate bytes and the frozen input contract before any database write."""
import hashlib
import json
from datetime import datetime
from pathlib import Path, PurePosixPath

FIELDS = set('schema_version source source_job_id batch_id observed_at source_url title_raw company_raw locations_raw category_raw education_raw experience_raw description_raw requirements_raw employment_type_raw salary_raw headcount_raw source_published_at_raw source_updated_at_raw raw_refs parser_version'.split())
REQUIRED = 'source source_job_id batch_id observed_at source_url title_raw company_raw parser_version'.split()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def jsonl(path):
    data = path.read_bytes()
    if data.startswith(b'\xef\xbb\xbf') or (data and not data.endswith(b'\n')):
        raise ValueError(f'BOM or missing final newline: {path.name}')
    return [json.loads(line) for line in data.decode('utf-8').splitlines() if line.strip()]


def safe_path(root, name):
    if not isinstance(name, str) or '\\' in name or ':' in name:
        raise ValueError('Invalid relative path')
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError('Path escapes batch')
    result = (root / name).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError('Path escapes batch')
    return result


def validate(path):
    root = Path(path).resolve()
    manifest_bytes = (root / 'manifest.json').read_bytes()
    m = json.loads(manifest_bytes)
    if m['schema_version'] != '1.0' or m['batch_id'] != root.name:
        raise ValueError('Unsupported schema or batch directory mismatch')
    if m['source'] not in ('tencent', 'netease') or m['coverage_status'] not in ('complete','partial','failed'):
        raise ValueError('Unsupported source/coverage')
    files = {}
    for entry in m['files']:
        name = entry['path']
        if name in files:
            raise ValueError('Duplicate manifest path')
        p = safe_path(root, name)
        data = p.read_bytes()
        if len(data) != entry['bytes'] or digest(data) != entry['sha256']:
            raise ValueError(f'Hash/size mismatch: {name}')
        if entry['records'] is not None and len(jsonl(p)) != entry['records']:
            raise ValueError(f'Record count mismatch: {name}')
        files[name] = entry
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name not in ('README.md','manifest.json','.gitkeep')}
    if actual != set(files):
        raise ValueError('Manifest file inventory differs from directory')
    jobs = jsonl(root / 'jobs.jsonl')
    requests = jsonl(root / 'requests.jsonl')
    issues = jsonl(root / 'quality_issues.jsonl')
    seen = set()
    start = datetime.fromisoformat(m['started_at'].replace('Z','+00:00'))
    end = datetime.fromisoformat(m['finished_at'].replace('Z','+00:00'))
    if start.tzinfo is None or end.tzinfo is None or end < start:
        raise ValueError('Invalid batch time window')
    for row in jobs:
        if set(row) != FIELDS:
            raise ValueError('Job fields do not match v1.0')
        if any(not isinstance(row[k],str) or not row[k].strip() for k in REQUIRED):
            raise ValueError('Missing required string')
        if any(v is not None and not isinstance(v,str) for k,v in row.items() if k not in ('locations_raw','raw_refs')):
            raise ValueError('Invalid scalar type')
        if row['schema_version'] != '1.0' or row['batch_id'] != m['batch_id'] or row['source'] != m['source']:
            raise ValueError('Job identity disagrees with manifest')
        if len(row['source_job_id']) > 200 or row['source_job_id'] in seen:
            raise ValueError('Duplicate/overlong source ID')
        seen.add(row['source_job_id'])
        ts = datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'))
        if ts.tzinfo is None or not start <= ts <= end:
            raise ValueError('Observation outside batch window')
        if not row['source_url'].startswith(('https://','http://')):
            raise ValueError('Invalid source URL')
        locations = row['locations_raw']
        if locations is not None and (not isinstance(locations,list) or not locations or any(not isinstance(x,str) or not x.strip() or len(x)>200 for x in locations)):
            raise ValueError('Invalid locations')
        if not isinstance(row['raw_refs'],list) or not row['raw_refs']:
            raise ValueError('Missing raw references')
        for ref in row['raw_refs']:
            name = ref['path']
            safe_path(root,name)
            if not name.startswith('raw/') or name not in files or ref['sha256'] != files[name]['sha256']:
                raise ValueError('Invalid raw reference')
        for key,limit in {'title_raw':1000,'company_raw':500,'category_raw':500,'education_raw':500,'experience_raw':500,'employment_type_raw':500,'source_url':2048}.items():
            if row[key] is not None and len(row[key])>limit:
                raise ValueError(f'Overlong field: {key}')
    if not jobs or m['counts']['output_records'] != len(jobs) or m['counts']['requests'] != len(requests):
        raise ValueError('Empty batch or counts mismatch')
    # Review state stays unchanged. Passing structural validation is NOT acceptance.
    return {'root':root,'manifest':m,'jobs':jobs,'issues':issues,'files':files,
            'input_hash':digest(manifest_bytes), 'summary':{'jobs':len(jobs),'files':len(files),'issues':len(issues),'requests':len(requests)}}
