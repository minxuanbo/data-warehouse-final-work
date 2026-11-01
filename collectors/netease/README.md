# 网易社会招聘采集器 · 负责人 B

网易社会招聘（hr.163.com）公开岗位的小批采集程序。只读取公开列表与详情接口，不登录、不投递、不使用代理轮换。
数据放在 `data/netease/<batch_id>/`，不放本目录。规范依据见 [提交规范](../../data/README.md) 与 [小组项目说明与采集交付规范](../../docs/小组项目说明与采集交付规范.md)。

## 1. 运行环境

- Python 3.12 及以上（本地实测 3.14），仅使用标准库，无第三方依赖。
- 依赖文件：[requirements.txt](requirements.txt)，安装命令：`python -m pip install -r collectors/netease/requirements.txt`（空依赖，仅确认环境）。

## 2. 命令与参数

在**仓库根目录**执行。先用初始化脚本建立批次目录，再运行采集器：

```bash
python scripts/new_collection_batch.py --source netease --owner B
python -m collectors.netease --batch-dir data/netease/<batch_id> --target 100 --max-pages 100
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--batch-dir` | 必填 | `scripts/new_collection_batch.py` 生成的批次目录 |
| `--target` | 100 | 目标不同来源岗位数，达到即停 |
| `--max-pages` | 100 | 列表最多翻页数；技术类岗位约占返回量的 1/4，跨页重复会拉低有效产出 |
| `--page-size` | 10 | 接口实测每页 10 条 |
| `--interval` | 3.0 | 请求最小间隔（秒），不得调低 |
| `--retries` | 2 | 网络错误重试次数，退避 4s、8s |
| `--detail-samples` | 8 | 抽查详情条数，契约要求 ≥5 |
| `--sample-seed` | 20261101 | 详情与人工抽检的固定随机种子，保证可复现 |
| `--collector-commit` | pending | 生成数据的代码 commit；补丁提交后回填 |

输出：写入 `jobs.jsonl`、`requests.jsonl`、`quality_issues.jsonl`、`raw/`，更新 `manifest.json`，并重新生成批次 `README.md`（含抽检表）；标准输出打印计数摘要。

退出码：`0` 达到 target；`3` 页数用尽或数量不足；`2` 访问受限、列表业务失败、分页停滞或找不到原始响应的请求时间。

## 3. 来源与访问策略

- 列表：`POST https://hr.163.com/api/hr163/position/queryPage`，JSON 体 `{"currentPage": N, "pageSize": 10}`。响应 `code=200` 且 `data.list` 为数组才算业务成功；`data.pages`、`data.total` 只用于记录，不作为翻页依据。
- 详情：`GET https://hr.163.com/api/hr163/position/query?id=<id>`，`id` 只取自真实列表，不枚举、不编造。
- 分页：按 `currentPage` 顺序翻页，不跳页、不反复回扫；整页 ID 与上一页完全相同即判定分页停滞并中止（`quality_issues.jsonl` 记 `pagination_stalled`）。
- 详情策略：列表对象已含完整 `description` 与 `requirement`，因此不逐条重复请求详情；按固定种子随机抽 8 条详情，对比列表与详情 10 项关键字段，差异登记 `detail_mismatch` 并交 C 复核。这样既满足“详情抽查 ≥5 条”，也不为凑请求量额外增加来源压力。
- 访问规则：单并发、请求间隔 ≥3 秒；网络错误与详情业务失败最多重试 2 次（4s、8s 退避）；HTTP 401/403/418/429 或 HTML 响应出现登录/验证码提示时立即停止并返回退出码 2（JSON 正文不参与该判定，避免岗位描述含“登录”字样时误停）。触发受限的那一次请求同样写入 `requests.jsonl`，并登记 `access_restriction`，退出前仍完成 `manifest.json` 更新。遵守网站规则，不做代理轮换、不绕过访问控制。
- 已知限制：接口不披露薪资与发布时间；`workType`、`updateTime` 为未经验证的来源代码/毫秒时间戳，原样保存不译码。

## 4. 字段映射

| 契约字段 | 网易来源 | 转换规则 | 缺失与冲突处理 |
| --- | --- | --- | --- |
| `source_job_id` | `id` | 强制转字符串，不转浮点 | 缺失即无法定位，登记 `unidentified_record`，不输出 |
| `title_raw` | `name` | 原值，去首尾空白 | 空则不通过必填校验 |
| `company_raw` | 固定「网易」 | 不推断法律用工主体 | — |
| `locations_raw` | `workPlaceNameList` | 字符串数组原样保留（如“杭州市”），多地点不拆成重复岗位 | 为空填 null 并登记 `missing_location` |
| `category_raw` | `firstPostTypeName` | 原值 | 空则登记 `scope_review` |
| `description_raw` | `description` | 保留原文，不做 HTML 反转义 | 与任职要求同时为空登记 `missing_body` |
| `requirements_raw` | `requirement` | 保留原文 | 缺失登记 `missing_requirements` |
| `education_raw` | `reqEducationName` | 原值（如“本科”“不限”），不自行分档 | 结构化学历低于正文“X及以上”时登记 `education_conflict`，两个原值都保留 |
| `experience_raw` | `reqWorkYearsName` | 原值，不自行分档 | 缺失填 null |
| `employment_type_raw` | `workType` | 原代码字符串，不译码 | 缺失填 null |
| `headcount_raw` | `recruitNum` | 转字符串 | 缺失填 null |
| `salary_raw` / `source_published_at_raw` | 接口未提供 | 固定 null，不补造 | — |
| `source_updated_at_raw` | `updateTime` | 毫秒时间戳原样保存为字符串，不代表发布时间 | 缺失填 null |
| `source_url` | 无岗位网页字段 | 由 `id` 拼接详情接口 URL，不编造网页地址 | — |
| `observed_at` | 请求时间 | ISO 8601 UTC（`Z` 结尾） | 复用原始响应时只取 `requests.jsonl` 中该响应的 `requested_at` |
| `raw_refs` | `raw/list_*.json`（+ 详情抽查文件） | `path` + 64 位小写 `sha256`，相对批次目录 | 必填非空，`validate_job` 逐项校验路径与前缀 |
| `parser_version` | 常量 `netease-collector-1.0.0` | 不含 commit，避免伪造提交号 | — |

## 5. 岗位范围与异常记录

- 类目白名单：`firstPostTypeName` 含 技术/游戏程序/人工智能/数据/测试/运维/安全/研发/算法/开发。网易的类目是粗粒度分类（如“游戏程序”“技术”“人工智能”），不按岗位标题做关键词筛选。
- 标题黑名单兜底：策划、美术、原画、动画、视觉设计、UI设计、交互设计、销售、商务、售前、产品经理、项目经理、招聘、人力资源、财务、法务、行政、市场、营销、运营、品牌、公关、客服、采购。
- 海外及港澳台地点排除；地点为空或类目为空照常输出并标记 `scope_review`，交 C 复核。
- 标题括号内的城市与 `workPlaceNameList` 不一致时（仅当括号内容全部是已知城市，避免把 `（U3D方向）` 误判；比对时忽略“市”后缀），逐条登记 `location_conflict`，保留源字段原值，不修正、不丢弃。
- 排除项写 `quality_issues.jsonl`（`rule=scope_exclude`，含 ID、原因、原始引用），不写入 `jobs.jsonl`。

## 6. 限速、重跑与日志

- 单并发、间隔 ≥3 秒；网络错误与详情业务失败最多重试 2 次（4s、8s 退避），每次尝试都写入 `requests.jsonl`。
- 断点续跑：已存在的 `raw/list_*.json`、`raw/detail_*.json` 直接复用，不覆盖原始字节（`save_raw` 遇同名文件直接报错）；若 `jobs.jsonl` 已有记录则拒绝重跑，必须新建批次。已排除、待复核与已登记问题不重复登记。
- 恢复时 `observed_at` 只取 `requests.jsonl` 中对应响应文件的 `requested_at`；取不到则停止并登记 `observed_at_missing`，不用其他请求或当前时刻代替。
- 请求日志：一次 HTTP 调用中的**每一次尝试**都单独写 `requests.jsonl`（重试链路上的失败尝试同样留痕），记录 `request_id`、方法、URL、参数、HTTP 状态、业务成功标记、响应文件、编码、耗时、`attempt` 与错误；不保存 Cookie、Authorization、Token 或登录态。
- `request_id` 形如 `req_0001`，续跑时从 `requests.jsonl` 已有最大编号之后继续，同一批次内不重复。
- 清单计数：`counts.unprocessed_unique_ids` 与 `counts.unprocessed_ids` 明确记录“达到 target 时同页剩余、未输出也未排除”的岗位，便于逐项对账。
