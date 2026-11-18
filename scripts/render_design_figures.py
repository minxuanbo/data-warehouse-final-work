"""Editable course information package, actual analytical star and layered lineage."""
from html import escape
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]/'docs/design/figures'

class Svg:
    def __init__(self,w,h):
        self.parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
          '<rect width="100%" height="100%" fill="white"/>',
          '<defs><marker id="a" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#50677c"/></marker></defs>']
    def text(self,x,y,s,size=20,anchor='start'):
        self.parts.append(f'<text x="{x}" y="{y}" font-family="Microsoft YaHei, sans-serif" font-size="{size}" text-anchor="{anchor}" fill="#172e42">{escape(s)}</text>')
    def rect(self,x,y,w,h,fill='#f6f8fa'):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="#526779" stroke-width="1.5"/>')
    def line(self,points,label=None,arrow=False,dashed=False):
        self.parts.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+'" fill="none" stroke="#50677c" stroke-width="2"'+(' marker-end="url(#a)"' if arrow else '')+(' stroke-dasharray="7 5"' if dashed else '')+'/>')
        if label:
            a,b=points[0],points[-1]
            self.text((a[0]+b[0])/2+7,(a[1]+b[1])/2+(6 if a[0]==b[0] else -7),label,18)
    def box(self,x,y,w,title,lines,fill='#eaf1f8',size=19):
        self.rect(x,y,w,66+len(lines)*30);self.rect(x,y,w,46,fill);self.text(x+14,y+31,title,21)
        for i,line in enumerate(lines):self.text(x+14,y+75+i*30,line,size)
    def save(self,name):
        OUT.mkdir(parents=True,exist_ok=True);(OUT/name).write_text('\n'.join(self.parts+['</svg>'])+'\n',encoding='utf-8')

def information_package():
    s=Svg(1600,790);s.text(800,48,'图3-1 公开数字技术岗位需求分析信息包',30,'middle')
    s.text(800,89,'使用者：人才培训与就业指导规划人员   决策：岗位方向、技能训练与门槛适配',22,'middle')
    s.text(40,137,'业务观察：官网在扫描窗口可见的岗位状态；一份日样本内，同一来源岗位只计一次。',22)
    columns=[('时间',['年 → 季度 → 月 → 日','北京时间批次结束日','不是企业发布日期','当前不具备完整日趋势']),
      ('来源与企业',['来源、企业分别分析','腾讯 / 网易官网','企业保留来源品牌名','不将来源当法律雇主']),
      ('岗位方向',['标准类别 → 岗位明细','开发 / 测试 / 数据','算法AI / 运维安全','源类别与标准类别分列']),
      ('学历与经验',['两个独立分析属性','本科、硕士等门槛','经验原区间保守保留','未知 / 不限 / 冲突分开']),
      ('地点',['省 → 市','一个岗位可有多地点','按岗位集合取并集','未映射不猜省份']),
      ('技能',['标准技能名','一个岗位可有多技能','必需 / 优先 / 明确提及','否定与不确定仅审计'])]
    for i,(name,lines) in enumerate(columns):
        x=40+i*253;s.rect(x,175,253,58,'#eaf1f8');s.text(x+126,212,name,24,'middle')
        for j,line in enumerate(lines):s.rect(x,233+j*56,253,56);s.text(x+12,268+j*56,line,18)
    s.box(40,490,1518,'业务度量与汇总规则',[
      'B01 岗位结构：不同核心岗位数、地区及方向分布；岗位数不是实际招聘人数。',
      'B02 技能需求：技能 / 组合覆盖岗位数 ÷ 有效正文岗位数；零技能命中仍保留正文分母。',
      'B03 门槛适配：学历、经验分布及技能交叉；未知和冲突单独解释。',
      'B04 观察变化：同范围、同规则、相邻完整日成立才计算；不等于企业新增或关闭。',
      '可加性：跨日岗位重复需去重，多技能 / 多城市分组不直接相加，比率重算分子分母。'],size=21)
    s.text(40,758,'质量、采集与发布是分析支撑；业务实体 ER 不替代这个数仓概念模型。',21);s.save('03_00_岗位分析信息包.svg')

def analytical_star():
    s=Svg(1600,1260);s.text(800,43,'图4-1 岗位日状态扩展星型（与实际 SQL 对象对应）',29,'middle')
    for points,label in [([(440,180),(500,180),(500,370),(550,370)],'1 : N'),
      ([(800,205),(800,320)],'1 : N'), ([(1160,180),(1100,180),(1100,400),(1050,400)],'1 : N'),
      ([(440,420),(550,420)],'1 : N'), ([(440,640),(550,640)],'1 : N'), ([(1160,500),(1050,500)],'1:N'),
      ([(700,670),(700,815),(500,815),(500,850)],'1 : N'), ([(900,670),(900,815),(1100,815),(1100,850)],'1 : N'),
      ([(500,1006),(500,1050)],'N : 1'), ([(1100,1006),(1100,1050)],'N : 1')]:s.line(points,label)
    s.box(40,95,400,'dim.source 来源维',['PK source_key','来源代码、名称、官网'])
    s.box(550,95,500,'dim.calendar_date 日期维',['PK date_key','年、季度、月、日；北京时间结束日'])
    s.box(1160,95,400,'dim.company 企业维',['PK company_key','来源品牌名、主体核实状态'])
    s.box(40,340,400,'dim.job_category 类别维',['PK category_key','标准方向、规范化版本'])
    s.box(40,560,400,'dim.job 来源岗位身份维',['PK job_key；UQ posting_key','当前一对一绑定来源岗位','不是已完成的跨来源归并'])
    s.box(1160,340,400,'门槛及类型：三张独立维表',[
      'dim.education：PK education_key','dim.experience：PK experience_key','dim.employment_type：',
      '  PK employment_type_key','分别保存学历、经验、招聘类型','未知、不限、冲突不合并'],size=18)
    s.box(550,320,500,'dwd.fact_job_daily 日状态事实',[
      '粒度：发布版本 × 分析日 × 来源岗位','组合PK：release_id, date_key, job_key','FK：source_key, company_key',
      'FK：category_key, education_key','FK：experience_key, employment_type_key','度量：job_count=1, is_core, body_valid',
      '技术引用：build_id, observation_key','技术引用：representative_version_key','日期不可直接累加为独立岗位数',
      'sample 可含 partial；formal 检查完整性'],'#fff0d7',20)
    s.box(230,850,540,'dwd.bridge_daily_city 多地点桥',[
      '组合PK：release_id, date_key, job_key, city_key','前三列 FK → 日状态事实；city_key → 地点维','一岗多城市；汇总取岗位并集'],size=18)
    s.box(830,850,540,'dwd.bridge_daily_skill 多技能桥',[
      '组合PK：release_id, date_key, job_key, skill_key','前三列 FK → 日状态事实；skill_key → 技能维','仅有效技能；审计证据另保留'],size=18)
    s.box(230,1050,540,'dim.city 地点维',['PK city_key；省、市、映射状态、规范化版本'])
    s.box(830,1050,540,'dim.skill 技能维',['PK skill_key；标准技能名'])
    s.text(40,1205,'图例：PK 主键；FK 外键；UQ 唯一约束；1 : N 一对多。连线表示键关联，不表示 ETL。',20)
    s.text(40,1238,'原始观察、内容版本与构建审计保留在底层；主图聚焦业务分析，不将运行日志拼成业务星座。',20)
    s.save('04_01_岗位日状态星型.svg')

def layers():
    s=Svg(1600,870);s.text(800,48,'图4-2 同一个岗位需求模型如何贯通数据分层',30,'middle')
    s.text(800,91,'实线箭头 = 加工依赖；虚线 = 描述 / 审计支撑；星型是 DWD 与 DIM 的关联结构',22,'middle')
    for a,b in [(290,340),(570,620),(980,1030),(1260,1310)]:s.line([(a,300),(b,300)],arrow=True)
    s.box(40,165,250,'文件接入',['官网列表 / 详情响应','jobs + manifest','请求日志 / SHA-256','原始字段和批次','真实采集，不造历史'],size=18)
    s.box(340,165,230,'ODS 原值',['raw_response','posting_record','保存文件引用 / 原值','一批一来源岗位','守恒及哈希校验'],size=18)
    s.box(620,165,360,'DWD 分析明细',['fact_posting_observation','observation_enrichment / 技能证据','fact_job_daily（日状态主事实）','bridge_daily_city / skill','粒度：release × date × job','正文资格和核心范围'],size=18)
    s.box(1030,165,230,'DWS 主题汇总',['岗位结构 / 门槛','技能分子与正文分母','每日范围完整性','计数按粒度守恒','比率按集合重算'],size=18)
    s.box(1310,165,250,'ADS 业务服务',['岗位 / 技能 / 门槛','证据明细与质量KPI','release_id 固定查询','已发布版本可回查','Power BI 主题分析'],size=18)
    s.box(620,490,360,'DIM 统一分析描述',['日期 / 来源 / 企业 / 岗位方向','学历 / 经验 / 类型 / 岗位身份','地点 / 技能 / 内容版本'],size=18)
    s.line([(800,490),(800,411)],dashed=True)
    s.box(40,685,1520,'AUDIT 与可追溯加工链',[
      '批次 / 输入哈希 / 规则与构建 / release 输入 / 质量门 / 发布指针与历史，为各层提供证据。',
      '例：ImportantItem → ODS 原值 → 三字段正文与 Unity 优先证据 → 技能桥 → 主题覆盖占比 → 岗位原文回查。'],size=21)
    s.line([(800,685),(800,630)],dashed=True)
    s.text(40,838,'星型回答“如何按维度分析事实”；分层回答“如何加工与复用数据”。不是每层复制一套相同表。',22)
    s.save('04_02_分层与分析模型.svg')

if __name__=='__main__':
    information_package();analytical_star();layers();print('Generated 3 editable analysis diagrams')
