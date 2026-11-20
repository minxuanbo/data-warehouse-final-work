"""Reconstruct every collected field before accepting a frozen expansion batch.

Acceptance is technical AI-assisted verification; never human gold annotation.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re

from collectors.enterprise import map_job,core_candidate,NON_CORE,OVERSEAS
from collectors.enterprise_coverage import assess
from collectors.coverage import assess_coverage
from warehouse.load import ROOT
from warehouse.validate import validate,FIELDS
from warehouse.analysis_v11 import raw_post
from warehouse.normalization import category


LANGUAGE=re.compile(r'Java|Python|Android|iOS|HarmonyOS|鸿蒙|\bWeb\b|C\+\+|C#|Golang|SDK|推荐|搜索|智能体|\bAgent\b',re.I)


def main(batch,output,accept=False):
    checked=validate(batch);m=checked['manifest'];root=checked['root'];source=m['source']
    requests=[json.loads(l) for l in (root/'requests.jsonl').read_text(encoding='utf-8').splitlines()]
    times={r['response_path']:r['requested_at'] for r in requests if r['response_path'] and r['business_success']}
    decisions={};reconstructed=0
    for job in checked['jobs']:
        refs=job['raw_refs'];sid=job['source_job_id'];list_ref=next(r for r in refs if r['path'].startswith('raw/list_'))
        payload=json.loads((root/list_ref['path']).read_bytes())
        if source=='tencent':
            from collectors.tencent.mapping import build_job
            posts=[p for p in payload['Data']['Posts'] if str(p['PostId'])==sid];assert len(posts)==1
            detail_ref=next(r for r in refs if r['path'].startswith('raw/detail_'))
            detail=json.loads((root/detail_ref['path']).read_bytes())['Data']
            expected=build_job(posts[0],detail,m['batch_id'],times[detail_ref['path']],list_ref,detail_ref,job['parser_version'])
        elif source=='netease':
            from collectors.netease.mapping import build_job
            posts=[p for p in payload['data']['list'] if str(p['id'])==sid];assert len(posts)==1
            expected=build_job(posts[0],None,m['batch_id'],times[list_ref['path']],list_ref,job['parser_version'])
            expected['raw_refs']=refs  # Sampled detail refs are separately hash/ID verified below.
        else:
            posts=payload['data']['list'] if source=='xiaomi' else payload
            from collectors.enterprise import identity
            posts=[p for p in posts if identity(source,p)==sid];assert len(posts)==1
            expected=map_job(source,posts[0],m['batch_id'],times[list_ref['path']],list_ref)
        for field in FIELDS:
            assert job[field]==expected[field],(source,sid,field)
            reconstructed+=1
        for ref in refs:raw_post(root,ref['path'],source,sid) if source!='tencent' or ref['path'].startswith('raw/detail_') else None
        title=job['title_raw'];locations=job['locations_raw'] or []
        in_core,reason=core_candidate(title,locations)
        if re.search(r'创意设计师|平面设计|视觉设计|UI设计|UX设计',title):
            in_core,reason=False,'设计创作职责；AIGC工具使用不等于算法或软件研发'
        elif re.search(r'游戏(?:性能|功能)?测试|音频QA|引擎.*开发',title) and source=='netease':
            in_core,reason=True,'官网游戏/程序背景下的明确软件测试或引擎开发'
        elif '数据采集工程师' in title and re.search(r'Python|Java|Scrapy|爬虫',job['requirements_raw'] or '',re.I):
            in_core,reason=True,'任职要求明确采集系统与编程研发，区别人工采集/标注'
        if not in_core and not NON_CORE.search(title) and not re.search(r'创意设计师|平面设计|视觉设计|UI设计|UX设计',title) and not (locations and all(OVERSEAS.search(x) for x in locations)):
            if LANGUAGE.search(title):in_core,reason=True,'标题明确软件平台或编程技术方向'
            elif category(title,job['category_raw'])!='待分类' and re.search(r'软件|算法|代码|编程|研发|开发|系统|数据',job['requirements_raw'] or ''):
                in_core,reason=True,'标题/来源类别与任职要求共同支持数字技术职责'
        decisions[sid]={'is_core':in_core,'reason':reason,'raw_ref':list_ref['path']}
    proof=(assess(root,source,m['stop_reason'],m['counts'],m['error_pages']) if source in ('xiaomi','jd')
           else assess_coverage(root,source,m['stop_reason'],m['counts'],m['error_pages']))
    assert proof['coverage_status']==m['coverage_status'],proof
    if source=='netease':
        # Detail comparisons can reveal source drift; preserve it as a caveat.
        detail_checks=sum(bool(r['response_path'] and r['response_path'].startswith('raw/detail_') and r['business_success']) for r in requests)
        assert detail_checks>=5,'At least five real public detail checks required'
    result={'status':'passed_for_technical_acceptance','checked_at':datetime.now(timezone.utc).isoformat(),
            'source':source,'batch_id':m['batch_id'],'jobs':len(checked['jobs']),'field_values_reconstructed':reconstructed,
            'files_hashed':len(checked['files']),'request_attempts':len(requests),'failed_attempts':m['counts']['failed_requests'],
            'coverage_proof':proof,'core_jobs':sum(x['is_core'] for x in decisions.values()),'scope_decisions':decisions,
            'human_annotation':False,'review_actor':'AI-assisted technical verification authorized by user',
            'acceptance_scope':'Collected subset and source lineage; not full market coverage or independent precision/recall'}
    output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if accept:
        if m['acceptance_status']!='pending':raise ValueError('Expected a pending new batch')
        m.update(acceptance_status='accepted',technical_acceptance={'evidence':output.relative_to(ROOT).as_posix(),
                 'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'kind':'AI_assisted_technical_acceptance_not_human_labels'})
        (root/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        validate(root)
    return {k:v for k,v in result.items() if k!='scope_decisions'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('batch');p.add_argument('--output',required=True,type=Path);p.add_argument('--accept',action='store_true')
    a=p.parse_args();print(json.dumps(main(a.batch,a.output,a.accept),ensure_ascii=False))
