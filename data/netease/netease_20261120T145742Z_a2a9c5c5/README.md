# netease_20261120T145742Z_a2a9c5c5

状态：**小批采集完成，技术接入与数据验收待 C/D 完成**。本批为截取样本，不能用于全量变化指标或岗位下架判断。

- 来源：netease（网易社会招聘 https://hr.163.com/）；负责人：B（姓名/学号待填）
- 规范：schema v1.0；范围：digital_jobs_cn_v1；阶段：pilot
- 实际执行命令：`python -m collectors.netease --batch-dir data/netease/netease_20261120T145742Z_a2a9c5c5 --target 500 --max-pages 400 --page-size 10 --interval 3.0 --detail-samples 8`
- 依赖：Python 3.12+，仅标准库（`collectors/netease/requirements.txt`）
- 采集版本：`netease-collector-1.1.0`，commit `865771aa0607678abc1e1c46797a3faec705300a`（本批数据由该版本生成）
- 采集版本源码校验（SHA-256，UTF-8，LF 换行归一化，前 12 位）：`collectors/coverage.py` `cbaff3073063…`；`collectors/netease/__init__.py` `e2387e2406bd…`；`collectors/netease/__main__.py` `f900e8a07346…`；`collectors/netease/batch.py` `0664efb1b538…`；`collectors/netease/client.py` `5bbcb08c451b…`；`collectors/netease/mapping.py` `a78fef997010…`；`collectors/netease/README.md` `a8bc886ff1ea…`；`collectors/netease/report.py` `ab27157b695d…`；`collectors/netease/requirements.txt` `039edf1a7b9b…`
- parser_version（数据内）：`netease-collector-1.1.0`
- 来源及字段映射：见 [collectors/netease/README.md](../../../collectors/netease/README.md)

## 1. 实际数量、范围与停止原因

| 项目 | 数值 | 说明 |
| --- | --- | --- |
| 列表页 | 262 页 | currentPage 1—262，pageSize=10，不使用关键词 |
| 列表返回条数 | 2602 | 含重复请求；本批跨页重复由 `duplicate_source_id` 登记 |
| 不同来源岗位 ID | 2568 | 接口当页返回的岗位对象总数 |
| 输出记录 | 448 | 翻满页数仍未达到 pilot 目标 |
| 排除 ID | 2120 | 类目/标题/地点不在数字技术范围，`quality_issues.jsonl` 逐条含原因 |
| 待复核（已输出） | 5 | 已写入 jobs，同时登记 review 问题 |
| 未处理 | 0 | 达到 target 时同页剩余，未输出也未排除，下一批可继续 |
| 失败请求 | 14 | HTTP 失败或业务状态非成功（含详情重试尝试） |
| 原始响应文件 | 270 | 262 个列表 + 8 个抽查详情 |
| 无法识别 ID | 0 | 列表对象缺少 id 的记录 |

计数核对：2568 个不同 ID = 448 输出 + 2120 排除 + 0 未处理。

未处理的 ID（下一批可继续采，不在本批 jobs 中）：
无

`coverage_status=partial`，`stop_reason=source_exhausted`：本批翻满 262 页仍未达到 500 条目标，属于截取样本。

## 2. 范围与分布（仅描述本批样本，不代表网易全部岗位）

- 类目：游戏程序 217、技术 123、游戏测试 58、人工智能 50
- 城市（`workPlaceNameList` 展开后）：杭州市 259、广州市 89、上海市 83、北京市 11、安顺市 4、成都市 2
- 学历原值：本科 293、不限 141、硕士 14
- 经验原值：不限 201、3-5年 159、5-10年 61、0-3年 23、10年以上 4
- `employment_type_raw`（`workType` 原代码，未译码）：0 383、1 62、2 3
- 缺失：地点为空 0，职责为空 0，要求为空 0，学历为 null 0，人数为 null 0
- 薪资：接口未披露，448 条 `salary_raw=null`，不补造；`headcount_raw` 保留 `recruitNum` 原值字符串。

## 3. 访问规则与异常说明

- 单并发、请求间隔 ≥3.0 秒；网络失败最多重试 2 次并退避（单次调用合计最多 3 次尝试）。
- 列表与详情均为公开只读接口；未登录、未投递、未使用代理轮换、未绕过访问控制。
- 列表请求 262 页；请求日志共记 14 次失败（含网络重试尝试，逐条见 `requests.jsonl`）。
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
- [ ] 人工抽检 20 条：下表为脚本回读结果，待 B 逐条浏览签字

## 5. 人工抽检（20 条）

抽样方法：固定随机种子 `20261101` 从 448 条中随机抽 20 条；逐条回读 `raw/list_*.json` 原始对象，对照 `jobs.jsonl` 的 ID、标题、地点、类目、学历、经验、职责与要求；并对抽中的详情样本同时核对列表与详情。（自动回读；人工复核由 B 签字）

| 来源岗位 ID | 原始文件及定位 | 标题/地点/正文核对 | 冲突或缺失 | 结果及检查人 |
| --- | --- | --- | --- | --- |
| 65809 | raw/list_000020.json#/data/list/5 | 游戏测试实习生（烈酷工作室）／杭州市；职责 134 字、要求 168 字 | 无 | 回读一致（待人工复核） |
| 79013 | raw/list_000021.json#/data/list/7 | 平台测试实习生／杭州市；职责 131 字、要求 304 字 | 无 | 回读一致（待人工复核） |
| 69373 | raw/list_000026.json#/data/list/5 | 广告算法工程师／北京市；职责 222 字、要求 233 字 | 无 | 回读一致（待人工复核） |
| 79200 | raw/list_000032.json#/data/list/6 | 资深渲染开发工程师-在研项目／上海市；职责 135 字、要求 356 字 | 无 | 回读一致（待人工复核） |
| 79773 | raw/list_000044.json#/data/list/4 | 资深服务端开发工程师／广州市；职责 101 字、要求 282 字 | 无 | 回读一致（待人工复核） |
| 77062 | raw/list_000046.json#/data/list/3 | 游戏测试工程师（射击类-1）／广州市；职责 230 字、要求 277 字 | 无 | 回读一致（待人工复核） |
| 74090 | raw/list_000054.json#/data/list/7 | 大模型标注实习生（文本标注）／杭州市；职责 215 字、要求 403 字 | 无 | 回读一致（待人工复核） |
| 78046 | raw/list_000069.json#/data/list/4 | 资深服务端测试工程师（七日世界）／上海市；职责 146 字、要求 162 字 | 无 | 回读一致（待人工复核） |
| 76458 | raw/list_000075.json#/data/list/9 | 资深大模型算法工程师（NLP/LLM）／杭州市；职责 466 字、要求 475 字 | 无 | 回读一致（待人工复核） |
| 79036 | raw/list_000092.json#/data/list/2 | 游戏图形算法工程师（实习生）／杭州市；职责 304 字、要求 771 字 | duplicate_source_id: 第 93 页出现重复来源 ID，已跳过 | 回读一致（待人工复核） |
| 78750 | raw/list_000115.json#/data/list/2 | 软件集成开发工程师（工程机械智能化）／杭州市；职责 194 字、要求 451 字 | 无 | 回读一致（待人工复核） |
| 77950 | raw/list_000134.json#/data/list/1 | 客户端开发工程师（编辑器及玩法）／杭州市；职责 112 字、要求 267 字 | 无 | 回读一致（待人工复核） |
| 77390 | raw/list_000147.json#/data/list/7 | 客户端开发工程师（战斗3C）／上海市；职责 93 字、要求 210 字 | 无 | 回读一致（待人工复核） |
| 75754 | raw/list_000166.json#/data/list/9 | 游戏测试工程师（明日之后）／上海市；职责 228 字、要求 193 字 | 无 | 回读一致（待人工复核） |
| 62064 | raw/list_000197.json#/data/list/0 | 引擎开发-渲染向-杭州／杭州市；职责 122 字、要求 333 字 | 无 | 回读一致（待人工复核） |
| 72396 | raw/list_000210.json#/data/list/5 | 资深游戏客户端（在研体育竞技）／杭州市；职责 130 字、要求 219 字 | 无 | 回读一致（待人工复核） |
| 76079 | raw/list_000223.json#/data/list/6 | 游戏引擎开发工程师（移动端性能优化）／杭州市；职责 415 字、要求 437 字 | 无 | 回读一致（待人工复核） |
| 41871 | raw/list_000248.json#/data/list/8 | 客户端引擎开发专家（无限大）／杭州市；职责 123 字、要求 201 字 | 无 | 回读一致（待人工复核） |
| 56889 | raw/list_000250.json#/data/list/0 | AI程序员／杭州市；职责 109 字、要求 213 字 | 无 | 回读一致（待人工复核） |
| 71526 | raw/list_000250.json#/data/list/4 | 高级游戏服务端开发工程师- 系统/架构 (无限大）／杭州市；职责 287 字、要求 299 字 | 无 | 回读一致（待人工复核） |

检查人签字：__________　日期：__________（自动回读结论不能替代人工抽检）

## 6. 详情抽查核对（8 条，成功 8 条）

抽样方法：固定随机种子 `20261101` 抽取，覆盖不同页与类目；比较列表对象与详情对象的标题、类目、地点、学历、经验、职责、要求、招聘人数、招聘类型、更新时间共 10 项。

| 来源岗位 ID | 列表原始文件 | 详情原始文件 | 核对项 | 结果 |
| --- | --- | --- | --- | --- |
| 59893 | raw/list_000216.json | raw/detail_59893.json | 10 项关键字段 | 一致 |
| 64141 | raw/list_000174.json | raw/detail_64141.json | 10 项关键字段 | 一致 |
| 69390 | raw/list_000114.json | raw/detail_69390.json | 10 项关键字段 | 一致 |
| 75663 | raw/list_000155.json | raw/detail_75663.json | 10 项关键字段 | 一致 |
| 77449 | raw/list_000218.json | raw/detail_77449.json | 10 项关键字段 | 一致 |
| 77476 | raw/list_000134.json | raw/detail_77476.json | 10 项关键字段 | 一致 |
| 79019 | raw/list_000069.json | raw/detail_79019.json | 10 项关键字段 | 一致 |
| 79807 | raw/list_000079.json | raw/detail_79807.json | 10 项关键字段 | 一致 |

## 7. 验收

结论：pending；验收人/日期：待 C 复核格式、哈希、去重与入库，D 抽检正文与指标字段，A 交叉抽检原文。
数据验收与技术联调分别说明；小批通过不代表全量覆盖，不允许据此计算岗位下架。
问题、修正 commit、复验结果：待填。
