# netease_20261101T044527Z_157cf969

状态：**程序修复复验通过，数据验收 accepted，可进入联调**。本批为截取样本，不能用于全量变化指标或岗位下架判断。

- 来源：netease（网易社会招聘 https://hr.163.com/）；负责人：B（姓名/学号待填）
- 规范：schema v1.0；范围：digital_jobs_cn_v1；阶段：pilot
- 实际执行命令：`python -m collectors.netease --batch-dir data/netease/netease_20261101T044527Z_157cf969 --target 100 --max-pages 100 --page-size 10 --interval 3.0 --detail-samples 8`
- 依赖：Python 3.12+，仅标准库（`collectors/netease/requirements.txt`）
- 采集版本：`netease-collector-1.0.0`，commit `ef5e57bff710fa60d663339efe0e3c41b30b6d9f`（本批 100 条数据由该版本生成；共享仓库合入前用下方采集版本源码 SHA-256 定位）
- 修复版本：`netease-collector-1.0.1`，commit `fcaeab273cea6722c9556723fa66a7f6ec1d9470`（仅修复访问受限与重试逻辑，未重采数据；PR 合并后回填 squash commit）
- 采集版本源码校验（SHA-256，UTF-8，LF 换行归一化，前 12 位）：`collectors/netease/README.md` `ecfa69e97e67…`；`collectors/netease/__init__.py` `2dcf7550732b…`；`collectors/netease/__main__.py` `ca0fbca93371…`；`collectors/netease/batch.py` `bed856f4f034…`；`collectors/netease/client.py` `5bbcb08c451b…`；`collectors/netease/mapping.py` `a78fef997010…`；`collectors/netease/report.py` `244c8fd25dda…`；`collectors/netease/requirements.txt` `039edf1a7b9b…`
- 修复版本源码校验（SHA-256，UTF-8，LF 换行归一化，前 12 位）：`collectors/netease/README.md` `f48e9d025221…`；`collectors/netease/__init__.py` `1ff34a0d0294…`；`collectors/netease/__main__.py` `49b03b6fa8f6…`；`collectors/netease/batch.py` `4d4cd2f6e3df…`；`collectors/netease/client.py` `5bbcb08c451b…`；`collectors/netease/mapping.py` `a78fef997010…`；`collectors/netease/report.py` `5777aba062cc…`；`collectors/netease/requirements.txt` `039edf1a7b9b…`
- parser_version（数据内）：`netease-collector-1.0.0`
- 来源及字段映射：见 [collectors/netease/README.md](../../../collectors/netease/README.md)

## 1. 实际数量、范围与停止原因

| 项目 | 数值 | 说明 |
| --- | --- | --- |
| 列表页 | 67 页 | currentPage 1—67，pageSize=10，不使用关键词 |
| 列表返回条数 | 670 | 含重复请求；本批跨页重复由 `duplicate_source_id` 登记 |
| 不同来源岗位 ID | 638 | 接口当页返回的岗位对象总数 |
| 输出记录 | 100 | 达到 pilot 目标后停止 |
| 排除 ID | 538 | 类目/标题/地点不在数字技术范围，`quality_issues.jsonl` 逐条含原因 |
| 待复核（已输出） | 1 | 已写入 jobs，同时登记 review 问题 |
| 未处理 | 0 | 达到 target 时同页剩余，未输出也未排除，下一批可继续 |
| 失败请求 | 0 | HTTP 失败或业务状态非成功（含详情重试尝试） |
| 原始响应文件 | 75 | 67 个列表 + 8 个抽查详情 |
| 无法识别 ID | 0 | 列表对象缺少 id 的记录 |

计数核对：638 个不同 ID = 100 输出 + 538 排除 + 0 未处理。

未处理的 ID（下一批可继续采，不在本批 jobs 中）：
无

`coverage_status=partial`，`stop_reason=pilot_limit`：本批到 100 条即停止，属于截取样本。

## 2. 范围与分布（仅描述本批样本，不代表网易全部岗位）

- 类目：游戏程序 46、技术 31、人工智能 13、游戏测试 10
- 城市（`workPlaceNameList` 展开后）：杭州市 47、广州市 35、上海市 16、北京市 2
- 学历原值：本科 62、不限 36、硕士 2
- 经验原值：不限 59、3-5年 29、5-10年 9、0-3年 2、10年以上 1
- `employment_type_raw`（`workType` 原代码，未译码）：0 67、1 33
- 缺失：地点为空 0，职责为空 0，要求为空 0，学历为 null 0，人数为 null 0
- 薪资：接口未披露，100 条 `salary_raw=null`，不补造；`headcount_raw` 保留 `recruitNum` 原值字符串。

## 3. 访问规则与异常说明

- 单并发、请求间隔 ≥3.0 秒；网络失败最多重试 2 次并退避（单次调用合计最多 3 次尝试）。
- 列表与详情均为公开只读接口；未登录、未投递、未使用代理轮换、未绕过访问控制。
- 列表请求 67 页；请求日志共记 0 次失败（含网络重试尝试，逐条见 `requests.jsonl`）。
- 遇到 HTTP 401/403/418/429 或 HTML 登录/验证码页立即停止（本批未触发）。
- 列表已含完整 `description`/`requirement`，未逐条重复请求详情；另抽 8 条详情核对，成功 8 条。
- `updateTime` 为来源毫秒时间戳，`source_updated_at_raw` 原样保存其字符串形式，不代表发布时间。
- 标题括号城市与 `workPlaceNameList` 不一致、结构化学历低于正文“X及以上”时，均保留原值并登记 `quality_issues.jsonl`，不静默修正。

## 4. 自检

- [x] 所有文件是真实采集结果；`collector_commit` 待合并后回填，`collector_source` 已记录源码 SHA-256
- [x] jobs 字段、类型、时区符合 v1.0，同批 `(source, source_job_id)` 唯一
- [x] manifest.files 清单、字节数、SHA-256 全部回读核对一致
- [x] 每条 raw_refs 能定位本批 raw 文件，列表响应哈希为 64 位小写
- [x] 正文未混入弹窗/广告；列表原文与 jobs 字段已逐项回读
- [x] 无凭据、私人联系方式、绝对路径；单文件远小于 50 MiB
- [x] 已按唯一 ID 解释输出、排除、待复核和未处理去向
- [x] 人工抽检 20 条：石雨衡于 2026-11-01 逐条复核，20 条均一致

## 5. 人工抽检（20 条）

抽样方法：固定随机种子 `20261101` 从 100 条中随机抽 20 条；逐条回读 `raw/list_*.json` 原始对象，对照 `jobs.jsonl` 的 ID、标题、地点、类目、学历、经验、职责与要求；并对抽中的详情样本同时核对列表与详情。（自动回读结果已由 B 逐条人工复核）

| 来源岗位 ID | 原始文件及定位 | 标题/地点/正文核对 | 冲突或缺失 | 结果及检查人 |
| --- | --- | --- | --- | --- |
| 53229 | raw/list_000002.json#/data/list/0 | 游戏引擎开发工程师-性能优化（无限大）／杭州市；职责 151 字、要求 219 字 | 无 | 一致 |
| 65340 | raw/list_000004.json#/data/list/9 | 游戏客户端、引擎开发（在研3A射击-极限战场）／上海市；职责 231 字、要求 285 字 | 无；已抽查详情 | 一致 |
| 79290 | raw/list_000005.json#/data/list/3 | 音视频开发工程师／广州市；职责 179 字、要求 529 字 | 无；已抽查详情 | 一致 |
| 79165 | raw/list_000005.json#/data/list/8 | 资深数据平台工程师／广州市；职责 204 字、要求 337 字 | 无；已抽查详情 | 一致 |
| 79627 | raw/list_000007.json#/data/list/3 | 全栈开发工程师（偏ios）／广州市；职责 282 字、要求 402 字 | 无；已抽查详情 | 一致 |
| 79626 | raw/list_000015.json#/data/list/4 | 全栈开发实习生（LiveKit 音频链路构建方向）／广州市；职责 381 字、要求 427 字 | 无；已抽查详情 | 一致 |
| 33992 | raw/list_000017.json#/data/list/2 | 游戏引擎开发工程师／杭州市；职责 29 字、要求 178 字 | 无 | 一致 |
| 79060 | raw/list_000018.json#/data/list/6 | 游戏测试工程师（燕云十六声）／杭州市；职责 124 字、要求 150 字 | 无 | 一致 |
| 76217 | raw/list_000019.json#/data/list/0 | 高级服务端开发工程师（在研项目）／广州市；职责 56 字、要求 215 字 | 无 | 一致 |
| 60238 | raw/list_000030.json#/data/list/2 | 资深服务端开发（社区业务）／杭州市；职责 106 字、要求 453 字 | 无 | 一致 |
| 71014 | raw/list_000033.json#/data/list/8 | 渲染引擎开发实习生／上海市；职责 36 字、要求 196 字 | duplicate_source_id: 第 34 页出现重复来源 ID，已跳过 | 一致 |
| 79053 | raw/list_000038.json#/data/list/6 | 大数据平台研发工程师（实习生）／广州市；职责 182 字、要求 155 字 | 无 | 一致 |
| 79489 | raw/list_000044.json#/data/list/1 | 数据标注实习生（广杭不限）／杭州市；职责 61 字、要求 125 字 | 无；已抽查详情 | 一致 |
| 78287 | raw/list_000048.json#/data/list/9 | 游戏测试实习生（无限大）／杭州市；职责 149 字、要求 236 字 | 无 | 一致 |
| 79596 | raw/list_000049.json#/data/list/6 | 资深全栈开发工程师／杭州市；职责 356 字、要求 506 字 | 无 | 一致 |
| 73898 | raw/list_000055.json#/data/list/4 | AI 应用工程师（知识工程）／广州市；职责 324 字、要求 469 字 | 无 | 一致 |
| 78036 | raw/list_000056.json#/data/list/8 | AI全栈开发工程师（暴雪）／杭州市；职责 652 字、要求 922 字 | 无 | 一致 |
| 79294 | raw/list_000058.json#/data/list/1 | 程序类实习生（天下）／广州市；职责 239 字、要求 253 字 | 无 | 一致 |
| 72961 | raw/list_000063.json#/data/list/0 | 客户端开发工程师（UGC）／杭州市；职责 118 字、要求 194 字 | 无；已抽查详情 | 一致 |
| 74970 | raw/list_000064.json#/data/list/9 | 客户端开发（编辑器方向-蛋仔派对）／杭州市；职责 87 字、要求 212 字 | 无；已抽查详情 | 一致 |

检查人签字：石雨衡　日期：2026.11.1（自动回读结论不能替代人工抽检）

## 6. 详情抽查核对（8 条，成功 8 条）

抽样方法：固定随机种子 `20261101` 抽取，覆盖不同页与类目；比较列表对象与详情对象的标题、类目、地点、学历、经验、职责、要求、招聘人数、招聘类型、更新时间共 10 项。

| 来源岗位 ID | 列表原始文件 | 详情原始文件 | 核对项 | 结果 |
| --- | --- | --- | --- | --- |
| 65340 | raw/list_000004.json | raw/detail_65340.json | 10 项关键字段 | 一致 |
| 72961 | raw/list_000063.json | raw/detail_72961.json | 10 项关键字段 | 一致 |
| 74970 | raw/list_000064.json | raw/detail_74970.json | 10 项关键字段 | 一致 |
| 79165 | raw/list_000005.json | raw/detail_79165.json | 10 项关键字段 | 一致 |
| 79290 | raw/list_000005.json | raw/detail_79290.json | 10 项关键字段 | 一致 |
| 79489 | raw/list_000044.json | raw/detail_79489.json | 10 项关键字段 | 一致 |
| 79626 | raw/list_000015.json | raw/detail_79626.json | 10 项关键字段 | 一致 |
| 79627 | raw/list_000007.json | raw/detail_79627.json | 10 项关键字段 | 一致 |

## 7. 验收

结论：accepted（数据验收通过，可进入联调）；验收人/日期：C 技术复验 2026-11-01，B（石雨衡）人工抽检 20 条签字 2026-11-01。D 指标验收随联调记录，A 交叉抽检另行登记。
数据验收与技术联调分别说明；小批通过不代表全量覆盖，不允许据此计算岗位下架。
问题与修正：评审发现 ①列表 403 后仍请求详情 ②详情 403 仍返回成功 ③详情重试与 Client 重试叠加导致最多 9 次请求。已在 `collectors/netease` 修复为「列表受限即停止、详情受限返回退出码 2、单次调用合计 ≤3 次尝试」，并用离线桩复现验证。本批 100 条记录与原始响应未受影响，未重新采集；修复版本 1.0.1 复验通过，采集版本 1.0.0 与修复版本的 commit 及源码哈希分别记录在清单与本 README 顶部。
