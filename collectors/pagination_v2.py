"""Explicit last-page proofs; repeated/out-of-range responses never prove coverage."""
import json
import math
from pathlib import Path

VERSION = 'public-pagination-2.0'


def page_data(source, payload, page, page_size, jd_total=None):
    if source == 'jd':
        posts, total = payload, jd_total
        last = page == math.ceil(total/page_size) if type(total) is int and total > 0 else False
    else:
        key = 'Data' if source == 'tencent' else 'data'
        code = 'Code' if source == 'tencent' else 'code'
        expected = 0 if source == 'xiaomi' else 200
        if payload.get(code) != expected:
            raise ValueError('Source business response failed')
        data = payload[key]
        posts = data['Posts' if source == 'tencent' else 'list']
        total = data['Count' if source == 'tencent' else 'total']
        last = page == math.ceil(total/page_size) if type(total) is int and total > 0 else False
        if source == 'netease' and total:
            if data.get('pages') != math.ceil(total/page_size) or type(data.get('lastPage')) is not bool:
                raise ValueError('NetEase pagination metadata disagrees with total')
            if data['lastPage'] != last:
                raise ValueError('NetEase lastPage contradicts page index')
    if type(total) is not int or total < 0 or not isinstance(posts, list):
        raise ValueError('Invalid list or business count')
    if len(posts) > page_size:
        raise ValueError('Source exceeded requested page size')
    return posts, total, last


def assess(root, source, stop_reason, counts, errors):
    root = Path(root); reasons = []; ids = set(); totals = []; pages = []; listed = 0; terminal = False
    meta = json.loads((root/'pagination.json').read_text(encoding='utf-8'))
    size = meta['page_size']
    if type(size) is not int or size <= 0:
        raise ValueError('Invalid page size')
    if stop_reason != 'source_exhausted': reasons.append('not_source_exhausted')
    if errors: reasons.append('error_pages')
    jd_total = None
    if source == 'jd':
        for name in ('count_start.json', 'count_end.json'):
            try:
                total = json.loads((root/'raw'/name).read_bytes())
                if type(total) is not int or total < 0: raise ValueError()
                totals.append(total)
            except (ValueError, OSError): reasons.append('missing_or_invalid_count')
        jd_total = totals[0] if totals else None
    for f in sorted((root/'raw').glob('list_*.json')):
        try:
            page = int(f.stem.split('_')[1]); pages.append(page)
            posts, total, last = page_data(source, json.loads(f.read_bytes()), page, size, jd_total)
            totals.append(total); listed += len(posts); terminal = last
            expected = min(size, max(0, total-(page-1)*size))
            if len(posts) != expected: reasons.append('page_length_disagrees_with_total')
            key = {'jd':'requirementId','netease':'id','tencent':'PostId','xiaomi':'jobPostId'}[source]
            for post in posts:
                sid = post.get(key) or (post.get('id') if source == 'xiaomi' else None)
                if sid is None: reasons.append('unidentified_raw_record')
                elif str(sid) in ids: reasons.append('duplicate_id_across_pages')
                else: ids.add(str(sid))
        except (ValueError, KeyError, TypeError, AttributeError): reasons.append('invalid_list_payload')
    if pages != list(range(1, len(pages)+1)): reasons.append('page_sequence_has_gaps')
    if not terminal: reasons.append('no_validated_last_data_page')
    if not totals or len(set(totals)) != 1: reasons.append('business_total_changed_or_missing')
    elif len(ids) != totals[0]: reasons.append('unique_ids_do_not_match_business_total')
    if counts.get('unprocessed_unique_ids', 0): reasons.append('unprocessed_ids')
    if len(ids) != counts.get('output_records',0)+counts.get('excluded_unique_ids',0):
        reasons.append('ids_not_fully_accounted')
    return {'version':VERSION, 'coverage_status':'partial' if reasons else 'complete',
            'unique_listed_ids':len(ids), 'listed_rows':listed, 'reported_totals':sorted(set(totals)),
            'validated_last_page':terminal, 'reasons':sorted(set(reasons))}
