"""Recheck raw skill lineage and published qualification anchors, without accuracy claims."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.analysis_inputs import input_paths
from warehouse.integrate_analysis import prepare
from warehouse.load import ROOT, connect
from warehouse.qualifications import body_fields, RULE_VERSION
from warehouse.release_build import records


def check(database, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    sources = {}
    identities = set()
    for source, batch, analysis, dictionary in input_paths():
        checked, provenance, _, evidence, jobs, _ = prepare(batch, analysis, dictionary)
        # prepare validates every evidence field/offset, raw hash and official response.
        identities.update((source, j['source_job_id']) for j in jobs)
        sources[source] = {'source_jobs': len(jobs), 'core_jobs': sum(j['is_core'] for j in jobs),
                           'skill_evidence_anchors': len(evidence),
                           'valid_core_job_skill_pairs': len({(e['source_job_id'], e['skill_name'])
                               for e in evidence if e['is_core'] and e['eligible_for_metric']}),
                           'input_hash': checked['input_hash'], 'scope_version': provenance['scope_version']}
    c = connect(database)
    try:
        rid = c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()
        jobs = records(c, 'SELECT * FROM ads.release_job_detail WHERE release_id=?', rid)
    finally:
        c.close()
    assert {(j['source'], j['source_job_id']) for j in jobs} == identities
    anchors = 0
    statuses = Counter()
    for j in jobs:
        fields = {**json.loads(j['content_json']), **body_fields(j),
                  'education_raw': j['education_raw'], 'experience_raw': j['experience_raw']}
        for name in ('education', 'experience'):
            r = json.loads(j[name+'_resolution_json'])
            assert r['value'] == j[name+'_group']
            assert r['rule_version'] == RULE_VERSION
            assert r['raw_refs'] and r['record_ref'].endswith('#'+j['source_job_id'])
            statuses[(j['source'], name, r['status'])] += 1
            for e in r['evidence']:
                original = fields.get(e['field']) or ''
                assert original[e['start']:e['end']] == e['text'], (j['source'], j['source_job_id'], e)
                anchors += 1
    result = {'status': 'passed', 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'database': database, 'release_id': rid, 'sources': sources,
              'qualification_rule_version': RULE_VERSION, 'qualification_anchors_checked': anchors,
              'qualification_statuses': [[list(k), n] for k, n in sorted(statuses.items())],
              'verification_actor': 'programmatic replay and AI-assisted review; not independent human annotation'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return {k: v for k, v in result.items() if k != 'qualification_statuses'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(check(a.database, a.output), ensure_ascii=False))
