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
SOFTWARE_ROLE=re.compile(r'(?:后端|后台|前端|全栈|客户端|服务端|框架)(?:研发|开发)(?:工程师|专家|架构师)|AI\s*Agent\s*架构师|(?:系统|软件|平台)架构师',re.I)
FOREIGN_CITIES={'伦敦','奥克兰','贝尔维尤','法兰克福','尔湾','悉尼','马德里','慕尼黑','迪拜'}
# Reviewed against this exact new batch. A department prefix such as 营销/客服
# cannot override an explicit software engineering role. Never copy to new scans.
TENCENT_REVIEWED_SOFTWARE={
 '2089960263330742272':'Java后端开发工程师','2056671347148505088':'后台开发工程师',
 '2110211598940549120':'运营开发工程师','2119283217256333312':'全栈开发工程师',
 '1958073234469572608':'Pytorch框架研发','2117825129072472064':'运营开发',
 '2104475912140664832':'AI Agent 架构师','2114892055439392768':'研发负责人',
 '2117169901797027840':'Gameplay开发工程师','1958073219999223808':'预训练框架研发工程师'}


def main(batch,output,accept=False):
    checked=validate(batch);m=checked['manifest'];root=checked['root'];source=m['source']
    for file in m.get('collector_source',[]):
        assert hashlib.sha256((ROOT/file['path']).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==file['sha256'],file['path']
    if m.get('continuation'):
        assert hashlib.sha256((ROOT/'scripts/resume_expansion.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest()==m['continuation']['runner_sha256']
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
        if m['batch_id']=='tencent_20261120T145742Z_cb8952ee' and sid in TENCENT_REVIEWED_SOFTWARE:
            assert TENCENT_REVIEWED_SOFTWARE[sid] in title
            in_core,reason=True,'本批原文复核：部门前缀不替代明确软件研发职责；依据标题 '+TENCENT_REVIEWED_SOFTWARE[sid]
        if m.get('collection_protocol')=='public-pagination-2.0' and SOFTWARE_ROLE.search(title):
            in_core,reason=True,'新版标题职责复核：明确软件研发职能优先于营销/运营等部门前缀；依据 '+SOFTWARE_ROLE.search(title)[0]
        if locations and all(x in FOREIGN_CITIES or OVERSEAS.search(x) for x in locations):
            in_core,reason=False,'来源明确为境外城市，不进入本期中国大陆核心范围'
        decisions[sid]={'is_core':in_core,'reason':reason,'raw_ref':list_ref['path']}
    if m.get('collection_protocol')=='public-pagination-2.0':
        from collectors.pagination_v2 import assess as assess_v2
        proof=assess_v2(root,source,m['stop_reason'],m['counts'],m['error_pages'])
    else:
        proof=(assess(root,source,m['stop_reason'],m['counts'],m['error_pages']) if source in ('xiaomi','jd')
               else assess_coverage(root,source,m['stop_reason'],m['counts'],m['error_pages']))
    assert proof['coverage_status']==m['coverage_status'],proof
    if source=='netease':
        # Detail comparisons can reveal source drift; preserve it as a caveat.
        detail_checks=sum(bool(r['response_path'] and r['response_path'].startswith('raw/detail_') and r['business_success']) for r in requests)
        assert detail_checks>=5,'At least five real public detail checks required'
    result={'status':'passed_for_technical_acceptance','checked_at':datetime.now(timezone.utc).isoformat(),
            'scope_review_version':'daily-software-title-1.0' if m.get('collection_protocol')=='public-pagination-2.0' else 'expanded-v2.1',
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
