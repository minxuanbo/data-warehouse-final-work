"""Bounded repeat probe: one page from each verified enterprise source."""
import json,time
from probe import fetch

def main():
 targets=[('https://careers.tencent.com/tencentcareer/api/post/Query?keyword=&pageIndex=1&pageSize=10&language=zh-cn',None),
          ('https://hr.163.com/api/hr163/position/queryPage',{'currentPage':1,'pageSize':10})]
 for i,(url,payload) in enumerate(targets):
  if i:time.sleep(3)
  record=fetch(url,payload)
  print(json.dumps(record,ensure_ascii=False))
  if record.get('error'):break

if __name__=='__main__':main()
