"""Versioned four-source collection; preserves old collectors for frozen evidence replay."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import requests

from collectors.enterprise import map_job, identity, core_candidate, RESTRICTIONS
from collectors.pagination_v2 import VERSION, page_data, assess

ROOT = Path(__file__).resolve().parents[1]
RUNNER_VERSION = 'daily-public-1.0.0'
LIST = {'tencent':'https://careers.tencent.com/tencentcareer/api/post/Query',
        'netease':'https://hr.163.com/api/hr163/position/queryPage',
        'xiaomi':'https://hr.xiaomi.com/website/api/agent/searchJobPage',
        'jd':'https://zhaopin.jd.com/web/job/job_list'}
COUNT = 'https://zhaopin.jd.com/web/job/job_count'
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def jd_params(): return {'workCityJson':'[]','jobTypeJson':'[]','jobSearch':'','depTypeJson':'[]'}


class Daily:
    def __init__(self, source, target=150, max_pages=400, until_exhausted=False):
        self.source, self.target, self.max_pages, self.until_exhausted = source, target, max_pages, until_exhausted
        self.batch_id = f'{source}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid4().hex[:8]}'
        self.path = ROOT/'data'/source/self.batch_id
        (self.path/'raw').mkdir(parents=True, exist_ok=False)
        for name in ('jobs.jsonl','requests.jsonl','quality_issues.jsonl'): (self.path/name).touch()
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'CourseDataWarehouse/1.1 (public recruitment research; single-threaded)'
        self.last = 0.; self.requests = []; self.jobs = []; self.seen = set(); self.excluded = set(); self.errors = []
        self.pages = set(); self.detail_samples = 0; self.reason = 'max_pages'; self.restricted = False

    def append(self, name, item):
        with (self.path/name).open('a',encoding='utf-8',newline='\n') as f:
            f.write(json.dumps(item,ensure_ascii=False)+'\n')

    def request(self, url, params, name, method='GET', json_body=False):
        for attempt in range(1,4):
            time.sleep(max(0,3-(time.monotonic()-self.last))); self.last=time.monotonic()
            stamp=now(); started=time.perf_counter(); response=None; error=None; payload=None
            try:
                response=self.session.request(method,url,params=params if method=='GET' else None,
                    json=params if json_body else None,data=params if method=='POST' and not json_body else None,timeout=25)
            except requests.RequestException as exc: error=str(exc)
            status=response.status_code if response is not None else None
            body=response.content if response is not None else None
            restricted=status in RESTRICTIONS
            if body:
                try:
                    payload=json.loads(body)
                    message=' '.join(str(payload.get(k) or '') for k in ('Message','message','msg')) if isinstance(payload,dict) else ''
                    restricted=restricted or bool(re.search(r'验证码|请.*登录|访问受限|访问过于频繁',message))
                    if isinstance(payload,dict):
                        code=payload.get('Code',payload.get('code'))
                        if code is not None and code != (0 if self.source=='xiaomi' else 200):
                            error='Source business response failed: '+str(code)
                except ValueError:
                    error='Expected JSON'
                    restricted=restricted or bool(re.search(r'验证码|请.*登录|访问受限',body[:2000].decode('utf-8',errors='ignore')))
            success=status==200 and error is None and not restricted
            path='raw/'+name if success else ('raw/attempt_'+str(len(self.requests)+1)+'_'+name if body else None)
            if path:
                if (self.path/path).exists(): raise FileExistsError(path)
                (self.path/path).write_bytes(body)
            row={'request_id':f'req_{len(self.requests)+1:05d}','requested_at':stamp,'method':method,'url':url,
                 'params':params,'http_status':status,'business_success':success,'response_path':path,
                 'elapsed_ms':round((time.perf_counter()-started)*1000),'attempt':attempt,
                 'error':'access_restricted' if restricted else error,'encoding':response.encoding if response is not None else None}
            self.requests.append(row);self.append('requests.jsonl',row)
            if restricted:
                self.restricted=True; raise PermissionError('Access restriction: stop this source')
            if success: return payload,{'path':path,'sha256':sha(body)},stamp
            if status is not None and status<500: raise ValueError(error or f'HTTP {status}')
            if attempt<3: time.sleep(4*attempt)
        raise ConnectionError(error or 'Network retries exhausted')

    def params(self,page):
        if self.source=='tencent': return {'pageIndex':page,'pageSize':10,'language':'zh-cn'}
        if self.source=='netease': return {'currentPage':page,'pageSize':10}
        if self.source=='xiaomi': return {'keyword':'','cityZhNames':'','pageSize':10,'pageNum':page}
        return {**jd_params(),'pageIndex':page,'pageSize':10}

    def map(self,post,ref,stamp):
        if self.source=='tencent':
            from collectors.tencent.mapping import build_job
            sid=str(post['PostId']);url='https://careers.tencent.com/tencentcareer/api/post/ByPostId'
            detail,dref,dstamp=self.request(url,{'postId':sid,'language':'zh-cn'},f'detail_{sid}.json')
            if detail.get('Code')!=200: raise ValueError('Tencent detail business failure')
            return build_job(post,detail['Data'],self.batch_id,dstamp,ref,dref,RUNNER_VERSION)
        if self.source=='netease':
            from collectors.netease.mapping import build_job
            row=build_job(post,None,self.batch_id,stamp,ref,RUNNER_VERSION)
            if self.detail_samples<5:
                sid=str(post['id']);url='https://hr.163.com/api/hr163/position/query'
                d,dref,_=self.request(url,{'id':sid},f'detail_{sid}.json')
                if d.get('code')!=200 or str(d['data']['id'])!=sid: raise ValueError('NetEase detail identity failure')
                row['raw_refs'].append(dref);self.detail_samples+=1
            return row
        return map_job(self.source,post,self.batch_id,stamp,ref)

    def candidate(self,post):
        if self.source in ('tencent','netease'):
            if self.source=='tencent':
                from collectors.tencent.mapping import classify
            else:
                from collectors.netease.mapping import classify
            decision,reason=classify(post)
            return decision!='exclude',reason or 'source category/title candidate'
        row=map_job(self.source,post,self.batch_id,now(),{'path':'raw/unused','sha256':'0'*64})
        return core_candidate(row['title_raw'],row['locations_raw'])

    def run(self):
        jd_total=None;stop=False
        try:
            if self.source=='jd': jd_total,_,_=self.request(COUNT,jd_params(),'count_start.json','POST')
            for page in range(1,self.max_pages+1):
                method='POST' if self.source in ('jd','netease') else 'GET'
                payload,ref,stamp=self.request(LIST[self.source],self.params(page),f'list_{page:06d}.json',method,self.source=='netease')
                posts,total,last=page_data(self.source,payload,page,10,jd_total)
                if not posts:
                    self.reason='empty_before_validated_last_page';break
                page_ids=[str(p[{'tencent':'PostId','netease':'id','jd':'requirementId','xiaomi':'jobPostId'}[self.source]]) for p in posts]
                signature=tuple(page_ids)
                if signature in self.pages: raise ValueError('Repeated page within advertised page range')
                self.pages.add(signature)
                for post,sid in zip(posts,page_ids):
                    if sid in self.seen:
                        self.append('quality_issues.jsonl',{'source_job_id':sid,'rule':'duplicate_source_id','severity':'warning','action':'review','message':'Repeated ID across pages; no fabricated replacement','raw_refs':[ref]})
                        continue
                    self.seen.add(sid)
                    include,why=self.candidate(post)
                    if not include:
                        self.excluded.add(sid)
                        self.append('quality_issues.jsonl',{'source_job_id':sid,'rule':'scope_exclude','severity':'info','action':'exclude','message':why,'raw_refs':[ref]})
                    elif self.until_exhausted or len(self.jobs)<self.target:
                        row=self.map(post,ref,stamp);self.jobs.append(row);self.append('jobs.jsonl',row)
                    if not self.until_exhausted and len(self.jobs)>=self.target:stop=True
                print(json.dumps({'source':self.source,'batch':self.batch_id,'page':page,'jobs':len(self.jobs),'total':total},ensure_ascii=False),flush=True)
                if last: self.reason='source_exhausted';break
                if stop: self.reason='bounded_sample_limit';break
        except Exception as exc:
            self.reason='access_restricted' if self.restricted else 'request_or_business_failure'
            self.errors.append({'reason':str(exc)})
        # Even bounded or failed JD traversals get a final count, except restrictions.
        if self.source=='jd' and not self.restricted:
            try:self.request(COUNT,jd_params(),'count_end.json','POST')
            except Exception as exc:self.errors.append({'stage':'count_end','reason':str(exc)})
        output={j['source_job_id'] for j in self.jobs}
        counts={'requests':len(self.requests),'failed_requests':sum(not r['business_success'] for r in self.requests),
                'list_pages':len(list((self.path/'raw').glob('list_*.json'))),'raw_response_files':len(list((self.path/'raw').iterdir())),
                'unique_source_ids':len(self.seen),'output_records':len(self.jobs),'excluded_unique_ids':len(self.excluded),
                'unprocessed_unique_ids':len(self.seen-output-self.excluded),'unresolved_unique_ids':0,'unidentified_records':0}
        (self.path/'pagination.json').write_text(json.dumps({'version':VERSION,'page_size':10},indent=2)+'\n',encoding='utf-8')
        proof=assess(self.path,self.source,self.reason,counts,self.errors)
        # Include all list IDs in proof, including a source page interrupted by a detail failure.
        counts['listed_records']=proof['listed_rows'];counts['unique_source_ids']=proof['unique_listed_ids']
        counts['unprocessed_unique_ids']=proof['unique_listed_ids']-len(output|self.excluded)
        proof=assess(self.path,self.source,self.reason,counts,self.errors)
        files=[]
        for p in sorted(self.path.rglob('*')):
            if p.is_file():
                data=p.read_bytes();files.append({'path':p.relative_to(self.path).as_posix(),'bytes':len(data),'sha256':sha(data),'records':len(data.splitlines()) if p.suffix=='.jsonl' else None})
        dependencies=['collectors/daily.py','collectors/pagination_v2.py','collectors/enterprise.py']
        if self.source in ('tencent','netease'):dependencies.append('collectors/'+self.source+'/mapping.py')
        m={'schema_version':'1.0','scope_version':'digital_jobs_cn_v1','phase':'expansion','source':self.source,
           'owner':{'tencent':'A','netease':'B','jd':'C','xiaomi':'D'}[self.source],'batch_id':self.batch_id,
           'started_at':self.requests[0]['requested_at'] if self.requests else now(),'finished_at':now(),
           'collector_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
           'parser_version':RUNNER_VERSION,'collector_version':RUNNER_VERSION,'collection_protocol':VERSION,
           'collection_window':'four-source-20261121-additional','execution_actor':'AI-assisted collection authorized by user; not member manual review',
           'collector_source':[{'path':n,'sha256':sha((ROOT/n).read_bytes().replace(b'\r\n',b'\n')),'newline':'LF'} for n in dependencies],
           'acceptance_status':'pending','coverage_status':proof['coverage_status'],'stop_reason':self.reason,
           'counts':counts,'error_pages':self.errors,'files':files,'coverage_evidence':proof,
           'query_spec':{'endpoints':[LIST[self.source]]+([COUNT] if self.source=='jd' else []),
                         'parameters':{'query':self.params(1),'until_exhausted':self.until_exhausted,'target':self.target},
                         'selection_rule':'Official category/title candidates; no keyword or location filter; bounded output is not full coverage',
                         'pagination_basis':'Validated advertised last data page, stable totals, distinct ID accounting; no beyond-last-page requests'}}
        (self.path/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (self.path/'README.md').write_text(f'# {self.batch_id}\n\n{self.source}今日新增真实观察，{len(self.jobs)}岗；技术验收pending，覆盖{proof["coverage_status"]}。\n\n独立批次、实际请求时刻；重复岗位是再次观察，不称新增发布。原采集器保留，新版分页逻辑见collector_source。停止原因{self.reason}；详情见manifest及coverage_evidence。\n',encoding='utf-8')
        print(json.dumps({'batch':str(self.path),'jobs':len(self.jobs),'proof':proof,'errors':self.errors},ensure_ascii=False),flush=True)
        return 2 if self.errors else 0


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',choices=LIST,required=True)
    p.add_argument('--target',type=int,default=150);p.add_argument('--max-pages',type=int,default=400)
    p.add_argument('--until-exhausted',action='store_true');a=p.parse_args()
    if a.target<=0 or a.max_pages<=0:p.error('Positive limits required')
    raise SystemExit(Daily(a.source,a.target,a.max_pages,a.until_exhausted).run())
