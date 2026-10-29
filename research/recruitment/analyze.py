"""Offline sample validation and normalization; not a production ETL pipeline."""
import hashlib,json,re
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from probe import ROOT

logs=[json.loads(x) for x in (ROOT/'requests.jsonl').read_text(encoding='utf-8').splitlines()]
jobs={};pages=[];details=[];hash_errors=[];failures=[]
def timestamp(value):
 if isinstance(value,(int,float)):return datetime.fromtimestamp(value/1000,timezone(timedelta(hours=8))).isoformat()
 return value
def put(source,ident,title,company,locations,education,experience,description,requirement,updated,url,record,**extra):
 key=(source,str(ident));old=jobs.get(key,{})
 row=dict(source=source,source_job_id=str(ident),title=title,company=company,locations_raw=locations,
          education_structured_raw=education,experience_raw=experience,description=description or old.get('description'),
          requirement=requirement or old.get('requirement'),updated_at_raw=timestamp(updated),url=url,
          salary_min_cny_month=None,salary_max_cny_month=None,**extra)
 row['evidence']=old.get('evidence',[])+[dict(url=record['url'],at_utc=record['at_utc'],sha256=record['sha256'])]
 jobs[key]=row
for r in logs:
 if not r.get('body_file'):
  failures.append({'url':r['url'],'error':r.get('error')});continue
 b=(ROOT/r['body_file']).read_bytes()
 if hashlib.sha256(b).hexdigest()!=r['sha256']:hash_errors.append(r['body_file'])
 u=r['url']; q=parse_qs(urlparse(u).query,keep_blank_values=True)
 try:j=json.loads(b)
 except (ValueError,UnicodeDecodeError):j=None
 if '/tencentcareer/api/post/' in u and j and j.get('Code')==200:
  is_list='/Query?' in u
  data=j['Data'];rows=data.get('Posts',[]) if is_list else [data]
  if is_list:pages.append(dict(source='tencent',page=int(q['pageIndex'][0]),keyword=q.get('keyword',[''])[0],returned=len(rows),reported_total=data['Count'],ids=[str(x['PostId']) for x in rows],at_utc=r['at_utc']))
  else:details.append(dict(source='tencent',id=str(data['PostId']),success=bool(data.get('Requirement'))))
  for x in rows:put('tencent',x['PostId'],x['RecruitPostName'],'腾讯',[x.get('LocationName')],None,x.get('RequireWorkYearsName'),x.get('Responsibility'),x.get('Requirement'),x.get('LastUpdateTime'),x.get('PostURL'),r,category_raw=x.get('CategoryName'))
 elif '/api/hr163/position/' in u and j and j.get('code')==200 and j.get('data'):
  data=j['data'];is_list='queryPage' in u;rows=data.get('list',[]) if is_list else [data]
  if is_list:pages.append(dict(source='netease',page=r['request_payload']['currentPage'],keyword='',returned=len(rows),reported_total=data['total'],ids=[str(x['id']) for x in rows],at_utc=r['at_utc']))
  else:details.append(dict(source='netease',id=str(data['id']),success=bool(data.get('requirement'))))
  for x in rows:put('netease',x['id'],x['name'],'网易',x.get('workPlaceNameList'),x.get('reqEducationName'),x.get('reqWorkYearsName'),x.get('description'),x.get('requirement'),x.get('updateTime'),'https://hr.163.com/api/hr163/position/query?id='+str(x['id']),r,category_raw=x.get('firstPostTypeName'),recruit_count_raw=x.get('recruitNum'),employment_type_code_raw=x.get('workType'))
 elif '/student/jobs/jobslist/ajax/' in u and j:
  if not j.get('flag'):
   failures.append(dict(url=u,error=j.get('global'),http_status=r['status']));continue
  rows=j['data']['list'];pages.append(dict(source='ncss',page=int(q['offset'][0]),keyword=q.get('jobName',[''])[0],returned=len(rows),reported_total=j['data']['pagenation']['count'],ids=[x['jobId'] for x in rows],at_utc=r['at_utc']))
  for x in rows:
   put('ncss',x['jobId'],x['jobName'],x['recName'],[x.get('areaCodeName')],x.get('degreeName'),None,None,None,x.get('updateDate'),'https://www.ncss.cn/student/jobs/'+x['jobId']+'/detail.html',r,
       upstream_publisher=x.get('sourcesNameCh'),recruit_count_raw=x.get('headCount'),company_size_raw=x.get('recScale'),company_property_raw=x.get('recProperty'),major_raw=x.get('major'),published_at_raw=timestamp(x.get('publishDate')))
   row=jobs[('ncss',x['jobId'])];lo=x.get('lowMonthPay');hi=x.get('highMonthPay')
   row['salary_source_raw']=[lo,hi];row['salary_status']='negotiable' if lo==hi==0 else 'disclosed'
   if lo is not None and hi is not None and not(lo==hi==0):row['salary_min_cny_month']=lo*1000;row['salary_max_cny_month']=hi*1000
 elif re.search(r'ncss.cn/student/jobs/[^/]+/detail.html',u):
  text=(ROOT/r['text_file']).read_text(encoding='utf-8');ident=u.split('/')[-2]
  # Exclude hidden application dialogs, recommendations and company boilerplate.
  desc=text.split('职位详情\n',1)[-1].split('扫码快速投递简历',1)[0] if '职位详情\n' in text else ''
  details.append(dict(source='ncss',id=ident,success=bool(desc.strip()),linked_to_sample=('ncss',ident) in jobs))
  if ('ncss',ident) in jobs:
   jobs[('ncss',ident)]['description']=desc.strip();jobs[('ncss',ident)]['detail_url']=u

skill_patterns={'Python':r'\bpython\b','SQL':r'\bsql\b','MySQL':r'\bmysql\b','Redis':r'\bredis\b','MongoDB':r'\bmongodb\b','Oracle':r'\boracle\b','PyTorch':r'\bpytorch\b','Spark':r'\bspark\b','Hadoop':r'\bhadoop\b','Excel':r'\bexcel\b','Java':r'\bjava\b','C++':r'(?<!\w)c\+\+(?!\w)','机器学习':'机器学习','数据治理':'数据治理','数据仓库':r'数据仓库|数仓'}
for row in jobs.values():
 text='\n'.join([row.get('description') or '',row.get('requirement') or ''])
 row['skills_demo']=[k for k,p in skill_patterns.items() if re.search(p,text,re.I|re.ASCII)]
 row['skills_demo_note']='词典匹配，仅演示可提取性；未区分必需、优先、职责和否定语境'
summary={'sample_period':'2026-10-29 至 2026-10-30（Asia/Shanghai）','hash_errors':hash_errors,'request_count':len(logs),'pages':pages,'details':details,'failures':failures,'sources':{}}
for source in ['tencent','netease','ncss']:
 rows=[x for x in jobs.values() if x['source']==source];groups=defaultdict(list)
 for x in rows:groups[(x['company'],x['title'],tuple(x['locations_raw'] or []))].append(x['source_job_id'])
 summary['sources'][source]={'unique_source_ids':len(rows),'companies':len({x['company'] for x in rows}),
  'field_presence':{k:sum(x.get(k) is not None and x.get(k) not in ('',[]) for x in rows) for k in ['title','company','locations_raw','education_structured_raw','experience_raw','description','requirement','salary_min_cny_month','updated_at_raw']},
  'possible_repost_groups':[dict(company=k[0],title=k[1],locations=list(k[2]),ids=v) for k,v in groups.items() if len(v)>1],
  'skills_demo_counts':dict(Counter(s for x in rows for s in x['skills_demo']))}
(ROOT/'samples.json').write_text(json.dumps(list(jobs.values()),ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k not in ('pages','failures')},ensure_ascii=False,indent=2))
print('PAGES',[(p['source'],p['page'],p['returned'],p['reported_total']) for p in pages])
