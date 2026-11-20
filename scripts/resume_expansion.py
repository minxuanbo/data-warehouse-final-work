"""One auditable continuation after a transient network stop; never a challenge bypass."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

from warehouse.load import ROOT


def resume(batch, target=500):
    batch = Path(batch).resolve()
    if not batch.is_relative_to(ROOT/'data'): raise ValueError('Formal batch path required')
    manifest = json.loads((batch/'manifest.json').read_text(encoding='utf-8'))
    source = manifest['source']
    if source not in ('netease', 'xiaomi', 'jd') or manifest['acceptance_status'] != 'pending':
        raise ValueError('Only pending network-stopped expansion batches can continue')
    if manifest['stop_reason'] not in ('list_request_failed', 'request_or_business_failure'):
        raise ValueError('Access restrictions and business challenges cannot be resumed here')
    archive = ROOT/'reports/verification/expansion_attempts'/(batch.name+'_before_resume')
    archive.mkdir(parents=True, exist_ok=False)  # At most one automated continuation.
    for name in ('manifest.json', 'README.md', 'jobs.jsonl', 'quality_issues.jsonl'):
        shutil.copy2(batch/name, archive/name)
    # These are derived handoff files, not raw observations. Reparse the saved bytes
    # using their original request timestamps; raw files and requests stay intact.
    (batch/'jobs.jsonl').write_text('', encoding='utf-8')
    if source == 'netease':
        from collectors.netease.__main__ import main
        result = main(['--batch-dir', str(batch), '--target', str(target), '--max-pages', '400',
                       '--sample-seed', '20261120', '--collector-commit', manifest['collector_commit']])
    else:
        from collectors import enterprise
        original = enterprise.core_candidate
        language = re.compile(r'Java|Python|Android|iOS|HarmonyOS|鸿蒙|\bWeb\b|C\+\+|C#|Golang|SDK|推荐|搜索|智能体|\bAgent\b', re.I)
        def expanded_scope(title, locations):
            yes, reason = original(title, locations)
            if yes: return yes, reason
            if not enterprise.NON_CORE.search(title or '') and not (locations and all(enterprise.OVERSEAS.search(x) for x in locations)) and language.search(title or ''):
                return True, '标题含明确软件平台或编程技术方向'
            return False, reason
        enterprise.core_candidate = expanded_scope
        class Continuation(enterprise.Collector):
            def __init__(self):
                self.source, self.target, self.max_pages = source, target, 400 if source == 'xiaomi' else 220
                self.batch_id, self.path = batch.name, batch
                self.requests = [json.loads(l) for l in (batch/'requests.jsonl').read_text(encoding='utf-8').splitlines()]
                self.seen, self.output, self.excluded = set(), set(), set()
                self.errors, self.totals, self.page_hashes = [], [], []
                self.last_request = 0.0
                self.session = enterprise.requests.Session()
                self.session.headers.update({'User-Agent': 'CourseDataWarehouse/1.0 (public recruitment research; single-threaded)'})
            def request(self, url, params, raw_name, method='GET'):
                path = batch/'raw'/raw_name
                if path.exists():
                    ref = 'raw/'+raw_name
                    records = [r for r in self.requests if r['response_path'] == ref and r['business_success']]
                    if not records: raise ValueError('Cached raw response lacks successful observation timestamp')
                    b = path.read_bytes()
                    return json.loads(b), {'path': ref, 'sha256': hashlib.sha256(b).hexdigest()}, records[0]['requested_at']
                return super().request(url, params, raw_name, method)
        # Parent inventory must not include the previous manifest as data.
        for name in ('manifest.json', 'README.md'):
            (batch/name).unlink()
        (batch/'quality_issues.jsonl').write_text('', encoding='utf-8')
        result = Continuation().run()
    current = json.loads((batch/'manifest.json').read_text(encoding='utf-8'))
    current['continuation'] = {'previous_manifest_sha256': hashlib.sha256((archive/'manifest.json').read_bytes()).hexdigest(),
                               'previous_attempt': archive.relative_to(ROOT).as_posix(),
                               'reused_raw_observation_times': True, 'new_observation_day_claimed_for_replay': False,
                               'scope_rule_extension': 'Software platforms and language-specific titles included' if source != 'netease' else None,
                               'runner_sha256': hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest()}
    (batch/'manifest.json').write_text(json.dumps(current, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('batch');p.add_argument('--target', type=int, default=500)
    a = p.parse_args();raise SystemExit(resume(a.batch, a.target))
