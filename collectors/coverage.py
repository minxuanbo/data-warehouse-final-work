"""Conservative page-coverage proof shared by collection and warehouse validation."""
import json
import re
import hashlib
from pathlib import Path


def source_files(source,root=None):
    root=Path(root) if root else Path(__file__).resolve().parents[1]
    paths=[p for p in (root/'collectors'/source).iterdir() if p.is_file() and p.suffix in ('.py','.md','.txt')]
    paths.append(root/'collectors/coverage.py')
    return [{'path':p.relative_to(root).as_posix(),'sha256':hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest(),'newline':'LF'} for p in sorted(paths)]


def assess_coverage(root,source,stop_reason,counts,error_pages):
    failures=[];totals=[];ids=set();pages=[];last_empty=False
    if stop_reason!='source_exhausted':failures.append('not_source_exhausted')
    if error_pages:failures.append('error_pages')
    if counts.get('unprocessed_unique_ids',0):failures.append('unprocessed_ids')
    if counts.get('unidentified_records',0):failures.append('unidentified_records')
    files=sorted((Path(root)/'raw').glob('list_*.json'))
    if not files:failures.append('no_list_responses')
    for path in files:
        match=re.fullmatch(r'list_(\d+)\.json',path.name)
        if not match:failures.append('unrecognized_page_name');continue
        pages.append(int(match[1]))
        try:
            payload=json.loads(path.read_bytes())
            data=payload.get('Data' if source=='tencent' else 'data') or {}
            posts=data.get('Posts' if source=='tencent' else 'list')
            total=data.get('Count' if source=='tencent' else 'total')
            code=payload.get('Code' if source=='tencent' else 'code')
            if code!=200 or not isinstance(posts,list) or type(total) is not int or total<0:
                failures.append('missing_or_invalid_business_total');continue
            totals.append(total);last_empty=not posts
            for post in posts:
                identity=post.get('PostId' if source=='tencent' else 'id')
                if identity is None or not str(identity).strip():failures.append('unidentified_raw_record')
                else:ids.add(str(identity))
        except (ValueError,TypeError,AttributeError):failures.append('invalid_list_payload')
    if pages!=list(range(1,len(pages)+1)):failures.append('page_sequence_has_gaps')
    if not last_empty:failures.append('no_successful_terminal_empty_page')
    if not totals or len(set(totals))!=1:failures.append('business_total_changed_or_missing')
    elif len(ids)!=totals[0]:failures.append('unique_ids_do_not_match_business_total')
    accounted=counts.get('output_records',0)+counts.get('excluded_unique_ids',0)
    if len(ids)!=accounted:failures.append('ids_not_fully_accounted')
    return {'version':'coverage-proof-1.0','coverage_status':'partial' if failures else 'complete',
            'unique_listed_ids':len(ids),'reported_totals':sorted(set(totals)),
            'terminal_empty_page':last_empty,'reasons':sorted(set(failures))}
