# Power BI 小批联调与扩量准备

2026-11-10。本轮由组长接手 D 的最后一个开发任务，在 `feature/analysis` 完成。张淘然已有的技能提取、抽检和冻结证据继续保留；当前规范化和范围裁定以 C 的 `digital_jobs_cn_core_v1.2` 及数仓接口为准。

## 交付入口与环境

打开 [Recruitment.pbip](../../dashboards/powerbi/Recruitment.pbip)。这是可在 Power BI Desktop 中编辑的真实 Import 模式工程，使用微软公开的 PBIP/PBIR 报表格式和受支持的 TMSL 语义模型定义。项目源码纳入 Git；本机凭据、缓存和 PBIX 导出不纳入 Git。首次克隆只有模型定义，需连接自己的本机数据库后刷新。

本轮环境：Windows、Python 3.12、SQL Server 2025、ODBC Driver 18、锁定的 dbt 依赖、Power BI Desktop 2.159.1231.0。使用 `lpc:localhost` 本机共享内存；Windows 身份由 Power BI 的凭据窗口确认，不在 M 代码或 Git 中写用户名和密码。连接中的自签名证书信任仅适用于本机课程开发。

仓库根目录执行：

```powershell
python -m venv .venv-dbt
.\.venv-dbt\Scripts\python.exe -m pip install -r warehouse/requirements.lock.txt
.\scripts\run_skills_v11.ps1
```

关闭该项目的 Desktop 窗口，然后准备报表和独立对账用例：

```powershell
.\.venv-dbt\Scripts\python.exe -X utf8 -m scripts.prepare_powerbi
.\.venv-dbt\Scripts\python.exe -X utf8 -m scripts.prepare_powerbi_checks
```

前者从 `ads.current_analysis_builds` 查询已选构建，核对当前小批分母和版本，并把实际 build_id 固定到所有导入表。随后打开 `dashboards/powerbi/Recruitment.pbip`，刷新。若提示 ODBC 身份，选 Windows／当前凭据。首次本机身份验证由操作者完成，不需要 Power BI 云端账号。

其他本机实例和开发库可传 `--server`、`--database`；数据库限定为 `recruitment_dw_dev*`。每台电脑的 build_id 可能不同，不照抄 5、6。刷新已固定构建，不会因另一个脚本切换当前构建而混入新旧输入；接入新版数据后先对账，再重新生成固定选择。

`prepare_powerbi.py` 是当前两源小批的复现入口，包含 98/333/334 等验收保护。**扩量后的通用报表构建入口仍需改造，不能删掉保护后直接当作正式多批流水线。**

## 四页内容与指标模型

| 页面 | 功能 |
| --- | --- |
| 01 小批概览 | 来源、城市、经验、源类别、学历筛选；核心岗位、正文分母、岗位×技能、正文覆盖及分布 |
| 02 技能与组合 | 按筛选后的岗位集合计算技能数量、占比及无序技能组合；技能选择保留岗位分母 |
| 03 岗位与证据 | 通过文本岗位 ID 或岗位行联动证据；保留扩展、否定和不确定结果用于审计，不混入有效指标 |
| 04 构建与质量 | 固定批次与版本、范围说明、冲突裁定及对账基线 |

本次 BI 语义模型是目标数仓的分析切片：`Builds→Jobs→SkillJobs/Pairs/Evidence/CityJobs`，共享技能表筛选技能关系和证据。采用单向关系，避免技能反向过滤岗位导致分母缩小；城市桥通过度量值中的 `TREATAS` 返回岗位集合，城市多选按岗位去重。该 BI 模型不代替设计中的完整星座架构。

核心岗位和技能分母来自 Jobs，包含未命中技能的有效正文岗位；技能关系同时筛 `is_core=true`、`eligible_for_metric=true` 后去重。组合从每岗技能集合展开，每个无序组合每岗一次，城市、经验等筛选仍可传播。技能及组合占比为空分母时返回 BLANK，不写成 0%。

城市只统一展示值的“市”后缀，例如北京／北京市同组；未据此宣称已完成行政区划字典。城市冲突仍单列，腾讯确认双工作地分别进入北京、深圳。原值、来源自然键、批次、哈希和证据位置继续保留；岗位 ID 不转换为数字。

本批基线：腾讯／网易原始各 100 岗，核心及正文分母各 98，岗位×技能分别 333／334，有有效技能岗位分别 83／80。网易经验为 12 条冲突和 1 条建议；71196 学历冲突单列。冻结的 D 文件仍保存其当时待确认状态，当前 BI 使用 C 裁定，不覆盖原始证据。

## 独立验收

[DAX 用例](../../reports/analysis/powerbi_dax_cases.json)从固定来源文件、技能证据和 C 范围策略独立生成，不从 SQL 汇总复制期望值。[实测结果](../../reports/analysis/powerbi_validation.json)记录 Power BI 引擎真实执行结果；结果仅对应所列构建及用例哈希。

在 PowerShell 中确定本次 Recruitment 模型端口：

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces" -Recurse -Filter msmdsrv.port.txt |
  ForEach-Object { Get-Content $_.FullName -Encoding Unicode }
.\scripts\check_powerbi.ps1 -Port <本次模型端口>
```

同时开多个报表时有多个端口，先确认 Recruitment 的端口，不凭顺序猜。检查脚本仅连接 localhost，使用 Desktop 自带的官方 ADOMD 库执行只读 DAX；需用 PowerShell 7。用例覆盖两来源基线、各城市/经验/学历组、城市与类别经验组合、技能选择分母、无技能命中岗位、多城市并集、扩展排除、建议与冲突、技能组合及空筛选。

页面操作还需检查切片器、岗位行联动和版本表是否显示正确，结束时清除筛选并保存工程。刷新失败必须修复，不能将空表的 0 当作验收结果。

### 页面检查（2026-11-10）

组长提供的四张实际 Desktop 截图已检查通过，无阻止本轮小批合并的问题。截图记录默认画面；筛选数值的正确性另由上述 49 项真实引擎 DAX 用例验证，两者共同构成本轮验收依据。另在全新开发库完成了固定输入的重建，19 个 dbt 模型、9 项数据检查通过，C/D 40 项离线回归通过，记录见[干净数据库复现](../../reports/analysis/powerbi_reproduction.json)。

| 画面 | 检查结果 |
| --- | --- |
| [01 小批概览](../../reports/analysis/powerbi_screenshots/01_overview.png) | 核心岗位与正文分母均 196，技能对 667、正文覆盖 100%；城市展示已统一，经验及学历冲突单列 |
| [02 技能与组合](../../reports/analysis/powerbi_screenshots/02_skills.png) | C++ 为 63/196=32.1%，Python 为 54/196=27.6%；C++ 与 Python 组合为 26/196=13.3%；数量降序展示 |
| [03 岗位与证据](../../reports/analysis/powerbi_screenshots/03_evidence.png) | 岗位 ID 保留文本、来源链接可见，证据按原字段展示；有效 True 与无效 False 同时保留用于审计 |
| [04 构建与质量](../../reports/analysis/powerbi_screenshots/04_quality.png) | 本机固定腾讯 5、网易 6，各分母 98；正文、词典、规则、范围及冲突裁定与 C 接口一致；长版本字段可横向滚动查看 |

技能表“总计 163 / 83.2%”是**至少命中一种有效技能的不同岗位数及其占比**，不是各技能行计数之和。组合表“总计 139 / 70.9%”是**至少具有一个有效技能组合的不同岗位数及其占比**，也不是各组合行计数之和。两表默认分母均为 196；岗位×技能对数 667 单独显示。

本轮验收限定为小批工程和接口；正式答辩前仍需使用扩量后的实际发布版本刷新、复核并重新截图。

## “打通”与扩量的边界

本轮通过意味着**固定小批的采集交付→ODS/DWD→技能接入→dbt DWS/ADS→Power BI**可以复现和对账。两源观察日不同、覆盖 partial；当前统计是来源岗位样本，不是跨源独立岗位全量或连续日期市场趋势。全项目还需正式多批/多日管道、完整一致性维度、每日快照、调度恢复和最终报告/PPT/录屏。

下一步可启动**受控扩量**，而不是同时无限放开采集：

1. A/B 继续分别负责腾讯、网易，组长负责 C 和本轮 BI；张淘然保留原有 D 成果作者与业务复核职责，有空参与验收和答辩材料。
2. 扩量前登记实际来源、岗位范围、招聘类型、抓取上限、分页规则及请求间隔。保留现有契约和原始响应；遇限制按采集器退出规则停止，不并发冲击站点。
3. 首轮每来源以 300–500 条唯一岗位为计划上限，受官网实际可采数量约束；这是下一轮建议，不是已采到的数量。不足时如实记录覆盖和原因。一个来源先交一个新 batch_id 的完整批次，禁止覆盖 100 岗旧批次或把旧数据改时间充当新采集。
4. 代码和完整批次分别提交到 `collectors/tencent/`、`data/tencent/<batch_id>/` 或 `collectors/netease/`、`data/netease/<batch_id>/`，通过各自分支 PR 交付。manifest、jobs.jsonl、raw、requests 和质量记录须满足既有交付规范。
5. **C 与采集并行**改造固定输入入口，使新批可以按修订与来源参数校验入库、提取技能、建立新构建并发布；验证同批幂等、跨批相同岗位更新、A→B→A 历史及失败回滚。当前报表生成器的固定小批保护也须替换成版本化范围与实际分母检查。
6. 每来源新批验收并完成一次数仓到看板对账后，再提高覆盖上限、加入额外已试采企业或持续每日采集。连续日期变化必须满足完整性与同版本条件；大量 partial 数据不能自动补足这些条件。

扩量原始数据可以先进入 Git 等待接入；“数据已交”“数据已验收”“数据已入仓”“看板已发布”分别记录。调度、备份恢复和多日快照验收后，才进入正式持续采集与趋势发布。

工程格式依据：[微软 PBIP 项目说明](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)、[语义模型文件说明](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset)。
