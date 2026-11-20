"""Public Xiaomi/JD list collectors. No login; one request per source per >=3s."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlencode
from uuid import uuid4

import requests

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'enterprise-public-1.0.0'
ENDPOINTS = {'xiaomi': 'https://hr.xiaomi.com/website/api/agent/searchJobPage',
             'jd': 'https://zhaopin.jd.com/web/job/job_list'}
RESTRICTIONS = {401, 403, 418, 429}
DIGITAL = re.compile(r'软件|前端|后端|后台|客户端|服务端|嵌入式|驱动|固件|算法|人工智能|大模型|AIGC|(?<![a-z])AI(?![a-z])|数据(?:开发|分析|工程|平台|挖掘|治理)|大数据|数据仓库|数仓|数据库|测试开发|开发测试|自动化测试|软件测试|渗透|网络安全|信息安全|SRE|DevOps|云平台|云计算|运维|机器学习|深度学习|计算机视觉|图像处理|语音|自然语言|操作系统|编译|中间件|全栈|游戏引擎|图形引擎|系统架构|网络工程', re.I)
NON_CORE = re.compile(r'产品经理|项目经理|项目管理|销售|售前|商务|市场|营销|客服|人力|财务|行政|采购|法务|美术|策划|运营|标注|数据采集|结构设计|机械设计|电路设计|硬件工程师')
OVERSEAS = re.compile(r'香港|澳门|台湾|海外|美国|日本|新加坡|英国|德国|印度|越南|韩国|法国')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def core_candidate(title, locations):
    if NON_CORE.search(title or ''):
        return False, '非本期软件数据数字技术职责或管理/运营岗位'
    if locations and all(OVERSEAS.search(x) for x in locations):
        return False, '工作地点均为海外或港澳台'
    return (True, '标题明确数字技术方向') if DIGITAL.search(title or '') else (False, '标题未明确属于本期数字技术方向，保守排除')


def identity(source, post):
    value = post.get('jobPostId') or post.get('id') if source == 'xiaomi' else post.get('requirementId')
    if value is None or not str(value).strip():
        raise ValueError('Missing actual source identity')
    return str(value)


def map_job(source, post, batch_id, observed_at, ref):
    """No derived degree/experience is inserted into raw fields."""
    sid = identity(source, post)
    if source == 'xiaomi':
        title, places, category = post['title'], post.get('cityZhNames') or None, None
        description, requirement = post.get('description'), post.get('requirement')
        employment, published, url = str(post['type']) if post.get('type') is not None else None, post.get('publishTime'), post.get('url')
    else:
        title, category = post.get('positionNameOpen') or post.get('positionName'), post.get('jobType')
        places = [x.strip() for x in re.split(r'[,，、/;；|]+', post.get('workCity') or '') if x.strip()] or None
        description, requirement = post.get('workContent'), post.get('qualification')
        employment, published = '社会招聘', post.get('formatPublishTime')
        url = 'https://zhaopin.jd.com/web/job/job_info_list/3?requirementId='+sid
    row = {k: None for k in ('education_raw', 'experience_raw', 'salary_raw', 'headcount_raw', 'source_updated_at_raw')}
    row.update(schema_version='1.0', source=source, source_job_id=sid, batch_id=batch_id,
               observed_at=observed_at, source_url=url, title_raw=title,
               company_raw={'xiaomi': '小米', 'jd': '京东'}[source], locations_raw=places,
               category_raw=category, description_raw=description or None, requirements_raw=requirement or None,
               employment_type_raw=employment, source_published_at_raw=str(published) if published else None,
               raw_refs=[ref], parser_version=VERSION)
    if not title or not url:
        raise ValueError('Missing public title or URL')
    return row


class Collector:
    def __init__(self, source, target, max_pages):
        self.source, self.target, self.max_pages = source, target, max_pages
        self.batch_id = f'{source}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid4().hex[:8]}'
        self.path = ROOT/'data'/source/self.batch_id
        (self.path/'raw').mkdir(parents=True, exist_ok=False)
        for name in ('jobs.jsonl', 'requests.jsonl', 'quality_issues.jsonl'):
            (self.path/name).touch()
        self.requests, self.seen, self.output, self.excluded = [], set(), set(), set()
        self.errors, self.totals, self.page_hashes = [], [], []
        self.last_request = 0.0
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'CourseDataWarehouse/1.0 (public recruitment research; single-threaded)'})

    def append(self, name, row):
        with (self.path/name).open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')

    def request(self, url, params, raw_name, method='GET'):
        for attempt in range(1, 4):
            time.sleep(max(0, 3-(time.monotonic()-self.last_request)))
            self.last_request = time.monotonic();stamp = now();started = time.perf_counter()
            response = None;error = None
            try:
                response = self.session.request(method, url, params=params if method == 'GET' else None,
                                                data=params if method == 'POST' else None, timeout=25)
            except requests.RequestException as exc:
                error = str(exc)
            status = response.status_code if response is not None else None
            body = response.content if response is not None else None
            raw_path = 'raw/'+raw_name if body is not None else None
            if raw_path:
                f = self.path/raw_path
                if f.exists():
                    raw_path = 'raw/attempt_'+str(len(self.requests)+1)+'_'+raw_name
                (self.path/raw_path).write_bytes(body)
            restricted = status in RESTRICTIONS
            if body:
                try:
                    payload = response.json()
                    message = str(payload.get('message') or payload.get('msg') or '') if isinstance(payload, dict) else ''
                    restricted = restricted or bool(re.search(r'验证码|请.*登录|访问受限|访问过于频繁', message))
                except ValueError:
                    if status == 200:
                        error = 'Expected JSON response; received non-JSON page'
            row = {'request_id': f'req_{len(self.requests)+1:04d}', 'requested_at': stamp, 'method': method,
                   'url': url, 'params': params, 'http_status': status,
                   'business_success': bool(status == 200 and not error and not restricted),
                   'response_path': raw_path, 'encoding': response.encoding if response is not None else None,
                   'elapsed_ms': round((time.perf_counter()-started)*1000), 'attempt': attempt,
                   'error': 'access_restricted' if restricted else error}
            self.requests.append(row);self.append('requests.jsonl', row)
            if restricted:
                raise PermissionError('Access restriction; stop this source')
            if status == 200 and not error:
                return response.json(), {'path': raw_path, 'sha256': digest(body)}, stamp
            if status is not None and status < 500:
                raise ValueError('Public request failed: '+str(status))
            if attempt < 3: time.sleep(4*attempt)
        raise ConnectionError(error or 'Request retries exhausted')

    def run(self):
        reason, terminal, listed = 'max_pages', False, 0
        try:
            if self.source == 'jd':
                total, _, _ = self.request('https://zhaopin.jd.com/web/job/job_count', self.jd_params(), 'count_start.json', 'POST')
                self.totals.append(int(total))
            for page in range(1, self.max_pages+1):
                params = {'keyword': '', 'cityZhNames': '', 'pageSize': 10, 'pageNum': page} if self.source == 'xiaomi' else {**self.jd_params(), 'pageIndex': page, 'pageSize': 10}
                payload, ref, stamp = self.request(ENDPOINTS[self.source], params, f'list_{page:06d}.json', 'GET' if self.source == 'xiaomi' else 'POST')
                if self.source == 'xiaomi':
                    if payload.get('code') != 0: raise ValueError('Xiaomi business response failed')
                    posts = payload['data']['list'];self.totals.append(int(payload['data']['total']))
                else: posts = payload
                if not isinstance(posts, list): raise ValueError('List response is not a list')
                if not posts:
                    terminal, reason = True, 'source_exhausted';break
                page_ids = [identity(self.source, post) for post in posts]
                signature = digest(json.dumps(page_ids).encode())
                if signature in self.page_hashes: raise ValueError('Repeated pagination; stop')
                self.page_hashes.append(signature);listed += len(posts)
                for post in posts:
                    sid = identity(self.source, post)
                    if sid in self.seen: continue
                    self.seen.add(sid)
                    row = map_job(self.source, post, self.batch_id, stamp, ref)
                    include, why = core_candidate(row['title_raw'], row['locations_raw'])
                    if not include:
                        self.excluded.add(sid)
                        self.append('quality_issues.jsonl', {'source_job_id': sid, 'rule': 'scope_exclude', 'severity': 'info', 'action': 'exclude', 'message': why, 'raw_refs': [ref]})
                    elif len(self.output) < self.target:
                        self.output.add(sid);self.append('jobs.jsonl', row)
                        if not row['requirements_raw'] or not row['locations_raw']:
                            self.append('quality_issues.jsonl', {'source_job_id': sid, 'rule': 'missing_body_or_location', 'severity': 'warning', 'action': 'review', 'message': '保留来源缺失，待ETL质量验收', 'raw_refs': [ref]})
                print(json.dumps({'source': self.source, 'page': page, 'listed_ids': len(self.seen), 'jobs': len(self.output)}, ensure_ascii=False), flush=True)
                if len(self.output) >= self.target: reason = 'bounded_sample_limit';break
            if self.source == 'jd':
                total, _, _ = self.request('https://zhaopin.jd.com/web/job/job_count', self.jd_params(), 'count_end.json', 'POST')
                self.totals.append(int(total))
        except Exception as exc:
            reason = 'access_restricted' if isinstance(exc, PermissionError) else 'request_or_business_failure'
            self.errors.append({'reason': str(exc)})
        counts = {'requests': len(self.requests), 'failed_requests': sum(not r['business_success'] for r in self.requests),
                  'list_pages': len(list((self.path/'raw').glob('list_*.json'))),
                  'raw_response_files': len(list((self.path/'raw').iterdir())), 'listed_records': listed,
                  'unique_source_ids': len(self.seen), 'output_records': len(self.output),
                  'excluded_unique_ids': len(self.excluded), 'unresolved_unique_ids': 0, 'unidentified_records': 0,
                  'unprocessed_unique_ids': len(self.seen-self.output-self.excluded), 'unprocessed_ids': sorted(self.seen-self.output-self.excluded)}
        complete = terminal and not self.errors and len(set(self.totals)) == 1 and len(self.seen) == self.totals[0] and not counts['unprocessed_unique_ids']
        files = []
        for f in sorted(self.path.rglob('*')):
            if f.is_file():
                b = f.read_bytes();files.append({'path': f.relative_to(self.path).as_posix(), 'bytes': len(b), 'sha256': digest(b), 'records': len(b.splitlines()) if f.suffix == '.jsonl' else None})
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        manifest = {'schema_version': '1.0', 'scope_version': 'digital_jobs_cn_v1', 'phase': 'expansion',
                    'source': self.source, 'owner': 'C' if self.source == 'jd' else 'D', 'batch_id': self.batch_id,
                    'started_at': self.requests[0]['requested_at'] if self.requests else None,
                    'finished_at': self.requests[-1]['requested_at'] if self.requests else None,
                    'collector_commit': commit, 'parser_version': VERSION,
                    'collector_source': [{'path': 'collectors/enterprise.py', 'sha256': digest(Path(__file__).read_bytes().replace(b'\r\n', b'\n')), 'newline': 'LF'}],
                    'collection_window': 'four-source-expansion-20261120-night',
                    'execution_actor': 'AI-assisted technical takeover authorized by user; not member manual review',
                    'acceptance_status': 'pending', 'coverage_status': 'complete' if complete else 'partial', 'stop_reason': reason,
                    'counts': counts, 'error_pages': self.errors, 'files': files,
                    'coverage_evidence': {'version': 'enterprise-coverage-1.0', 'terminal_empty_page': terminal, 'reported_totals': sorted(set(self.totals)), 'unique_listed_ids': len(self.seen)},
                    'query_spec': {'endpoints': [ENDPOINTS[self.source]], 'parameters': {'all_cities': True, 'all_projects': self.source == 'xiaomi', 'page_size': 10, 'target': self.target},
                                   'selection_rule': 'All public list pages in source order; conservative title-based mainland software/data core; exclusions retain raw refs', 'pagination_basis': 'Source total and successful terminal empty page; bounded target does not imply complete'}}
        (self.path/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        (self.path/'README.md').write_text(f'# {self.batch_id}\n\n真实扩量采集；技术验收pending。执行者为经用户授权的AI辅助技术接管，不代表成员人工签字。\n\n来源：{ENDPOINTS[self.source]}\n\n输出{len(self.output)}；列表唯一ID{len(self.seen)}；覆盖{manifest["coverage_status"]}；停止原因{reason}。\n\n列表已提供职责与任职全文，无额外详情请求。原始文本、ID、来源链接保留；缺失不补造。观察窗口和计数见manifest；不代表全市场。\n', encoding='utf-8')
        print(json.dumps({'batch': str(self.path), 'coverage': manifest['coverage_status'], 'reason': reason, 'counts': counts}, ensure_ascii=False), flush=True)
        return 0 if not self.errors else 2

    @staticmethod
    def jd_params():
        return {'workCityJson': '[]', 'jobTypeJson': '[]', 'jobSearch': '', 'depTypeJson': '[]'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('--source', choices=ENDPOINTS, required=True)
    p.add_argument('--target', type=int, default=500);p.add_argument('--max-pages', type=int, default=400)
    a = p.parse_args()
    if a.target <= 0 or a.max_pages <= 0: p.error('Positive limits required')
    raise SystemExit(Collector(a.source, a.target, a.max_pages).run())
