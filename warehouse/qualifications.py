"""Conservative qualification resolution with verbatim, offset-addressable evidence."""
import json
import re
import unicodedata

RULE_VERSION='qualification-cn-1.0'
DEGREES={'高中':'高中/中专','中专':'高中/中专','中技':'高中/中专','大专':'大专','专科':'大专',
         '本科':'本科','学士':'本科','硕士':'硕士','研究生':'硕士','博士':'博士'}
RANK={'高中/中专':1,'大专':2,'本科':3,'硕士':4,'博士':5}
TOKEN=re.compile('|'.join(DEGREES))


def chinese_number(text):
    if text.isdigit():return int(text)
    digits={'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if '十' in text:
        left,right=text.split('十',1)
        return (digits.get(left,1) if left else 1)*10+(digits.get(right,0) if right else 0)
    return digits.get(text)


def normalize_experience(raw,conflict=False):
    if conflict:return '冲突待确认'
    text=unicodedata.normalize('NFKC',raw or '').strip()
    if not text:return '未注明'
    if re.fullmatch(r'(?:经验)?(?:不限|无要求|不限制)(?:工作经验)?',text):return '不限'
    if re.search(r'应届|无经验|无需经验',text):return '应届/无经验'
    text=re.sub(r'\s+','',text).replace('～','-').replace('—','-').replace('－','-')
    num=r'[0-9零〇一二两三四五六七八九十]+'
    m=re.fullmatch(fr'({num})(?:[-~至到]({num}))?年(及以上|以上|及以下|以下|以内)?(?:相关)?(?:工作)?(?:经验)?',text)
    if not m:return '待解析'
    lo=chinese_number(m[1]);hi=chinese_number(m[2]) if m[2] else None
    if lo is None or (m[2] and (hi is None or hi<lo)):return '待解析'
    bound=(m[3] or '').replace('及以上','以上').replace('及以下','以下')
    return f'{lo}'+(f'-{hi}' if hi is not None else '')+'年'+bound


def body_fields(job):
    payload=job.get('content_json') or {}
    if isinstance(payload,str):payload=json.loads(payload)
    return {f:job.get(f) if job.get(f) is not None else payload.get(f)
            for f in ('requirements_raw','additional_requirements_raw')}


def degree_mentions(field,text):
    """A local comma/semicolon bounds preference. Later skill preferences do not leak."""
    if not text:return []
    result=[]
    for m in TOKEN.finditer(text):
        before=text[max(0,m.start()-18):m.start()]
        after=text[m.end():]
        # A degree held by people being mentored is not the applicant's degree.
        if after.startswith(('生','后')) or re.search(r'(?:指导|辅导|培养|教授).{0,6}$',before):continue
        left=re.split(r'[，,。；;\n\r]',before)[-1]
        right=re.split(r'[，,。；;\n\r]',after)[0]
        # Include paired degree alternatives before a shared 优先, e.g. 硕士、博士优先.
        preference=bool(re.search(r'优先(?:考虑)?[^，,；;。]{0,8}$',left) or re.search(r'^(?:及以上|以上)?(?:学历|学位|毕业)?[（(]?(?:者|人才|候选人)?(?:\s|、|或|博士|硕士|本科|研究生){0,12}(?:优先|加分|更佳)',right))
        uncertain=bool(re.search(r'(?:不要求|无需|非)$',left) or re.search(r'放宽|破格|同等.*经验',right))
        strength='不确定' if uncertain else '优先' if preference else '必需'
        start=max(text.rfind('\n',0,m.start()),text.rfind('；',0,m.start()),text.rfind('。',0,m.start()))+1
        ends=[p for ch in ('\n','；','。') if (p:=text.find(ch,m.end()))>=0]
        end=min(ends) if ends else len(text)
        result.append({'field':field,'start':start,'end':end,'text':text[start:end],
                       'match_start':m.start(),'match_end':m.end(),'degree':DEGREES[m[0]],'strength':strength})
    # An explicit no-limit statement is evidence, not an inference from missing text.
    for m in re.finditer(r'学历(?:不限|无要求|不限制)|不限学历|无学历要求',text):
        result.append({'field':field,'start':m.start(),'end':m.end(),'text':m[0],
                       'match_start':m.start(),'match_end':m.end(),'degree':'不限','strength':'必需'})
    return result


def education_resolution(job):
    raw=job.get('education_raw');fields=body_fields(job)
    evidence=[]
    if raw:
        evidence=degree_mentions('education_raw',raw)
        if re.fullmatch(r'不限|无要求|不限制',raw.strip()):
            evidence=[{'field':'education_raw','start':0,'end':len(raw),'text':raw,'degree':'不限','strength':'必需'}]
    body=[e for f,t in fields.items() for e in degree_mentions(f,t)]
    all_evidence=evidence+body
    structured=[e['degree'] for e in evidence if e['strength']=='必需']
    required=[e['degree'] for e in body if e['strength']=='必需']
    preferred=sorted({e['degree'] for e in all_evidence if e['strength']=='优先'},key=lambda x:RANK.get(x,0))
    def minimum(values):
        return '不限' if '不限' in values else min(values,key=lambda x:RANK[x]) if values else None
    source_value=minimum(structured);body_value=minimum(required)
    conflict=job.get('education_conflict',False) or (source_value is not None and body_value is not None and source_value!=body_value)
    uncertain=any(e['strength']=='不确定' for e in body)
    if conflict:value,status,basis='冲突待确认','conflict','structured_and_body'
    elif source_value:value,status,basis=source_value,'structured','education_raw'
    elif uncertain:value,status,basis='待确认','ambiguous','body'
    elif body_value:value,status,basis=body_value,'body_required','body'
    elif raw:value,status,basis='待解析','unparsed','education_raw'
    elif preferred:value,status,basis='未注明','preference_only','body'
    else:value,status,basis='未注明','not_stated','none'
    return {'value':value,'status':status,'basis':basis,'preferred':preferred,'evidence':all_evidence,'rule_version':RULE_VERSION}


def resolve(job):
    ed=education_resolution(job)
    raw=job.get('experience_raw');value=normalize_experience(raw,job.get('experience_conflict',False))
    ex={'value':value,'status':'conflict' if job.get('experience_conflict') else 'not_stated' if not raw else 'unparsed' if value=='待解析' else 'structured',
        'basis':'experience_raw' if raw else 'none','rule_version':RULE_VERSION,
        'evidence':[{'field':'experience_raw','start':0,'end':len(raw),'text':raw,'strength':'来源值'}] if raw else []}
    return {'education':ed,'experience':ex}
