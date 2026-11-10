"""Export the versioned C handoff for D from the verified integration input."""
import json
from pathlib import Path
from .integrate_analysis import prepare
from .load import ROOT, connect
from .validate import digest

BATCH = 'tencent_20261031T093102Z_366ad0a4'
INPUT = ROOT / '.local/cd_input'


def inputs():
    return (INPUT / 'data/tencent' / BATCH,
            INPUT / 'reports/analysis' / BATCH,
            INPUT / 'etl/skills/dictionary.json')


if __name__ == '__main__':
    checked, provenance, policy, _, enriched, input_hash = prepare(*inputs())
    connection = connect()
    try:
        build = connection.execute("SELECT build_id FROM audit.analysis_build WHERE input_hash=? AND status='ready'", input_hash).fetchone()
        if not build:
            raise ValueError('Verified build required before exporting')
        actual = connection.execute('SELECT COUNT(*),SUM(CAST(is_core AS int)) FROM ads.cd_job_detail WHERE build_id=?', build[0]).fetchone()
        if tuple(actual) != (len(enriched), sum(row['is_core'] for row in enriched)):
            raise ValueError('Export and database counts disagree')
    finally:
        connection.close()
    destination = ROOT / 'data/derived/tencent' / BATCH / 'cd_v1.1'
    destination.mkdir(parents=True, exist_ok=True)
    rows = [{**row, 'derived_schema_version': 'cd-handoff-1.1'} for row in enriched]
    data = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode('utf-8')
    output = destination / 'jobs_enriched.jsonl'
    if output.exists() and output.read_bytes() != data:
        raise ValueError('Existing handoff differs; use a new version directory')
    output.write_bytes(data)
    manifest = {
        'derived_schema_version': 'cd-handoff-1.1', 'batch_id': BATCH,
        'source_revision': '25b397bf846a8e7c39bbc249e0700428e89bc0c3',
        'analysis_revision': '0e06c7f9c0eff013f84bce8e5719254174162287',
        'scope_version': policy['scope_version'], 'enrichment_version': policy['enrichment_version'],
        'source_manifest_sha256': checked['input_hash'], 'build_input_sha256': input_hash,
        'source_postings': len(rows), 'core_postings': sum(row['is_core'] for row in rows),
        'current_skill_fields': policy['skill_input_fields'],
        'next_skill_fields': policy['next_skill_input_fields'],
        'file': {'path': output.name, 'bytes': len(data), 'sha256': digest(data)},
    }
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(manifest, ensure_ascii=False))
