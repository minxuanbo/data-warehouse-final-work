"""Low-volume public recruitment feasibility probe. Python standard library only."""
import hashlib,json,re,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
ROOT=Path(__file__).resolve().parent
class Parser(HTMLParser):
 def __init__(self):super().__init__();self.links=[];self.scripts=[];self.text=[];self.skip=0
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='a' and a.get('href'):self.links.append(a['href'])
  if tag=='script' and a.get('src'):self.scripts.append(a['src'])
  if tag in ('script','style'):self.skip+=1
 def handle_endtag(self,tag):
  if tag in ('script','style'):self.skip=max(0,self.skip-1)
 def handle_data(self,data):
  if not self.skip and data.strip():self.text.append(data.strip())
def fetch(url,payload=None):
 raw=ROOT/'raw';raw.mkdir(parents=True,exist_ok=True)
 data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
 key=hashlib.sha256(url.encode()+(data or b'')).hexdigest()[:16]
 rec={'url':url,'at_utc':datetime.now(timezone.utc).isoformat(),'method':'POST' if data else 'GET'}
 if payload is not None:rec['request_payload']=payload
 try:
  with urllib.request.urlopen(urllib.request.Request(url,data=data,headers={'User-Agent':'CourseResearch/0.1 (public recruitment feasibility study)','Content-Type':'application/json'}),timeout=20) as r:
   b=r.read(8_000_000);rec.update(status=r.status,final_url=r.url,bytes=len(b));enc=r.headers.get_content_charset() or 'utf-8'
  key+='_'+hashlib.sha256(b).hexdigest()[:10]
  s=b.decode(enc,errors='replace');(raw/(key+'.body')).write_bytes(b)
  p=Parser();p.feed(s);(raw/(key+'.txt')).write_text('\n'.join(p.text),encoding='utf-8')
  rec.update(sha256=hashlib.sha256(b).hexdigest(),body_file='raw/'+key+'.body',text_file='raw/'+key+'.txt',links=list(dict.fromkeys(urljoin(r.url,u) for u in p.links)),scripts=list(dict.fromkeys(urljoin(r.url,u) for u in p.scripts)))
 except Exception as e:rec['error']=str(e)
 with (ROOT/'requests.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(rec,ensure_ascii=False)+'\n')
 return rec
if __name__=='__main__':
 import sys
 for i,u in enumerate(sys.argv[1:]):
  if i:time.sleep(3)
  print(json.dumps(fetch(u),ensure_ascii=False))
