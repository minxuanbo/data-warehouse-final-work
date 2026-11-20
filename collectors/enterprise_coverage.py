"""Recompute coverage from Xiaomi/JD original pagination, never from a flag."""
import json
import re
from pathlib import Path


def assess(root, source, stop_reason, counts, errors):
    root = Path(root);reasons = [];ids = set();totals = [];pages = [];terminal = False
    if stop_reason != 'source_exhausted': reasons.append('not_source_exhausted')
    if errors: reasons.append('error_pages')
    if source == 'jd':
        for name in ('count_start.json', 'count_end.json'):
            try:
                total = json.loads((root/'raw'/name).read_bytes())
                if type(total) is not int: raise ValueError()
                totals.append(total)
            except (ValueError, OSError): reasons.append('missing_or_invalid_count')
    for path in sorted((root/'raw').glob('list_*.json')):
        match = re.fullmatch(r'list_(\d+)\.json', path.name)
        if not match: reasons.append('invalid_page_name');continue
        pages.append(int(match[1]))
        try:
            payload = json.loads(path.read_bytes())
            if source == 'xiaomi':
                if payload['code'] != 0: raise ValueError()
                posts = payload['data']['list'];totals.append(payload['data']['total'])
            else: posts = payload
            if not isinstance(posts, list): raise ValueError()
            terminal = not posts
            for post in posts:
                sid = (post.get('jobPostId') or post.get('id')) if source == 'xiaomi' else post.get('requirementId')
                if sid is None: reasons.append('unidentified_raw_record')
                else: ids.add(str(sid))
        except (ValueError, KeyError, TypeError): reasons.append('invalid_list_payload')
    if pages != list(range(1, len(pages)+1)): reasons.append('page_sequence_has_gaps')
    if not terminal: reasons.append('no_successful_terminal_empty_page')
    if not totals or any(type(n) is not int for n in totals) or len(set(totals)) != 1:
        reasons.append('business_total_changed_or_missing')
    elif len(ids) != totals[0]: reasons.append('unique_ids_do_not_match_business_total')
    if counts.get('unprocessed_unique_ids', 0): reasons.append('unprocessed_ids')
    if len(ids) != counts.get('output_records', 0)+counts.get('excluded_unique_ids', 0):
        reasons.append('ids_not_fully_accounted')
    return {'version': 'enterprise-coverage-proof-1.0', 'coverage_status': 'partial' if reasons else 'complete',
            'unique_listed_ids': len(ids), 'reported_totals': sorted(set(totals)),
            'terminal_empty_page': terminal, 'reasons': sorted(set(reasons))}
