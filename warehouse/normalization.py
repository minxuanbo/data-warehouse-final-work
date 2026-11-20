"""Versioned, conservative conformed dimensions. Never infer unknown source codes."""
import re
from .qualifications import resolve,normalize_experience

VERSION = 'conformed-cn-1.3'
MAPPING_VERSION = 'source-identity-only-1.0'
UNKNOWN = '未知'
CONFLICT = '冲突待确认'
CITY_PROVINCE = {
    '北京':'北京','上海':'上海','天津':'天津','重庆':'重庆','深圳':'广东','广州':'广东',
    '杭州':'浙江','宁波':'浙江','南京':'江苏','苏州':'江苏','无锡':'江苏','成都':'四川',
    '武汉':'湖北','西安':'陕西','长沙':'湖南','厦门':'福建','福州':'福建','合肥':'安徽',
    '济南':'山东','青岛':'山东','郑州':'河南','沈阳':'辽宁','大连':'辽宁','长春':'吉林',
    '哈尔滨':'黑龙江','石家庄':'河北','太原':'山西','南昌':'江西','南宁':'广西','海口':'海南',
    '贵阳':'贵州','昆明':'云南','兰州':'甘肃','银川':'宁夏','西宁':'青海','乌鲁木齐':'新疆',
    '呼和浩特':'内蒙古','拉萨':'西藏',
}
CITY_PROVINCE.update({'东莞':'广东','珠海':'广东','佛山':'广东','惠州':'广东','中山':'广东','汕头':'广东',
 '常州':'江苏','徐州':'江苏','扬州':'江苏','宿迁':'江苏','嘉兴':'浙江','绍兴':'浙江','温州':'浙江',
 '烟台':'山东','潍坊':'山东','洛阳':'河南','宜昌':'湖北','泉州':'福建','三亚':'海南'})
PROVINCES={n+'省':n for n in ('河北','山西','辽宁','吉林','黑龙江','江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南','广东','海南','四川','贵州','云南','陕西','甘肃','青海')}
PROVINCES.update({'内蒙古自治区':'内蒙古','广西壮族自治区':'广西','西藏自治区':'西藏','宁夏回族自治区':'宁夏','新疆维吾尔自治区':'新疆'})


def city(raw, conflict=False):
    if conflict:
        return {'code':'conflict','name':CONFLICT,'province':CONFLICT,'mapping_status':'conflict'}
    original=(raw or '').strip()
    if original in PROVINCES:
        province=PROVINCES[original]
        return {'code':'province:'+province,'name':'城市未披露','province':province,'mapping_status':'province_only'}
    name=original.removesuffix('市')
    if not name:
        return {'code':'unknown','name':UNKNOWN,'province':UNKNOWN,'mapping_status':'unknown'}
    province=CITY_PROVINCE.get(name)
    # An unmapped name stays visible, but cannot be assigned an invented province.
    return {'code':('cn:' if province else 'unmapped:')+name,'name':name,
            'province':province or UNKNOWN,'mapping_status':'mapped' if province else 'unmapped'}


def education(raw, conflict=False):
    if conflict: return CONFLICT
    text=(raw or '').strip()
    if not text:return UNKNOWN
    for pattern,label in [(r'不限|无要求|不限制','不限'),(r'博士','博士'),(r'硕士|研究生','硕士'),
                          (r'本科|学士','本科'),(r'大专|专科','大专'),(r'高中|中专|中技','高中/中专')]:
        if re.search(pattern,text):return label
    return '未映射'


def experience(raw, conflict=False):
    return normalize_experience(raw,conflict)


def category(title, raw_category=None):
    # Title takes precedence over broad source categories; no body keyword voting.
    title=title or ''
    patterns=[('算法/AI',r'算法|人工智能|机器学习|深度学习|大模型|AIGC|(?<![A-Za-z])AI(?![A-Za-z])'),
              ('数据开发/分析',r'数据(?:开发|分析|仓库|平台|工程|挖掘|治理)|数仓|大数据|BI\b'),
              ('测试',r'测试|质量保障|\bQA\b'),
              ('运维/安全',r'运维|安全|SRE\b|DevOps|基础设施|网络工程'),
              ('开发',r'开发|研发|工程师|程序|引擎|编译|前端|后端|后台|全栈|客户端|服务端|架构')]
    for label,pattern in patterns:
        if re.search(pattern,title,re.I):return label
    raw=(raw_category or '').strip()
    if re.search(r'人工智能|算法',raw):return '算法/AI'
    if re.search(r'游戏程序|技术|研发|开发',raw):return '开发'
    return '待分类'


def employment_type(source, raw):
    text=(raw or '').strip()
    if not text:return UNKNOWN
    # Official hr.163.com front-end module 0vM+ declares these labels; full-time
    # must not be relabelled as social recruitment. Preserve unknown codes.
    if source=='netease' and text in {'0','1','2'}:
        return {'0':'全职','1':'实习','2':'派遣'}[text]
    if source=='xiaomi' and text in {'1','2','3','4'}:
        return {'1':'社招渠道','2':'校招渠道','3':'实习项目','4':'顶尖人才项目'}[text]
    if source=='jd' and text=='社会招聘':return '社招渠道'
    # Tencent codes remain unverified; never apply another source's codebook.
    if re.search(r'实习',text):return '实习'
    if re.search(r'校招|校园|应届',text):return '校招'
    if re.search(r'社招|社会招聘',text):return '社招'
    return '来源代码未释义'


def classify(job):
    qualifications=resolve(job)
    return {'category':category(job.get('title_raw'),job.get('category_raw')),
            'education':qualifications['education']['value'],
            'experience':qualifications['experience']['value'],
            'qualifications':qualifications,
            'employment_type':employment_type(job['source'],job.get('employment_type_raw')),
            'company':(job.get('company_raw') or '').strip() or UNKNOWN}
