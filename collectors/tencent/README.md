# 腾讯招聘采集器 · 负责人 A

腾讯招聘（careers.tencent.com）公开岗位的小批采集程序。只读取公开列表与详情接口，不登录、不投递、不使用代理轮换。
数据放在 `data/tencent/<batch_id>/`，不放本目录。规范依据见 [提交规范](../../data/README.md) 与 [小组项目说明与采集交付规范](../../docs/小组项目说明与采集交付规范.md)。

## 1. 运行环境

- Python 3.12 及以上（本地实测 3.14），仅使用标准库，无第三方依赖。
- 依赖文件：[requirements.txt](requirements.txt)，安装命令：`python -m pip install -r collectors/tencent/requirements.txt`（空依赖，仅确认环境）。

## 2. 命令与参数

在**仓库根目录**执行。先用初始化脚本建立批次目录，再运行采集器：

```powershell
python scripts/new_collection_batch.py --source tencent --owner A
python -m collectors.tencent --batch-dir data/tencent/<batch_id> --target 100 --max-pages 40
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--batch-dir` | 必填 | `scripts/new_collection_batch.py` 生成的批次目录 |
| `--target` | 100 | 目标不同来源岗位数，达到即停 |
| `--max-pages` | 40 | 列表最多翻页数 |
| `--page-size` | 10 | 接口实测每页 10 条 |
| `--interval` | 3.0 | 请求最小间隔（秒），不得调低 |
| `--retries` | 2 | 网络错误重试次数，退避 4s、8s |
| `--keyword` | 空 | 可选关键词；默认不使用，避免样本偏斜 |

输出：写入 `jobs.jsonl`、`requests.jsonl`、`quality_issues.jsonl`、`raw/`，并更新 `manifest.json`；标准输出打印计数摘要。

退出码：`0` 达到 target；`3` 页数用尽或数量不足；`2` 访问受限、列表业务失败或分页停滞。

## 3. 来源与访问策略

- 列表：`GET https://careers.tencent.com/tencentcareer/api/post/Query`，参数 `pageIndex`、`pageSize`、`language=zh-cn`（可选 `keyword`）。响应 `Code=200` 且 `Data.Posts` 非空才算业务成功。
- 详情：`GET https://careers.tencent.com/tencentcareer/api/post/ByPostId`，参数 `postId`、`language=zh-cn`。`postId` 只取自真实列表，不枚举、不编造。
- 分页：按 `pageIndex` 顺序翻页，以 `Data.Count` 和 `Posts` 长度为准；若整页 ID 与上一页完全相同，判定分页停滞并中止（`quality_issues.jsonl` 记 `pagination_stalled`）。
- 访问规则：单并发、请求间隔 ≥3 秒、最多重试 2 次；HTTP 401/403/418/429 或响应出现登录/验证码提示时立即停止并返回退出码 2。触发受限的那一次请求同样写入 `requests.jsonl`，并登记 `access_restriction`，退出前仍完成 `manifest.json` 更新。遵守网站规则，不做代理轮换、不绕过访问控制。
- 已知限制：接口未披露薪资、招聘人数、发布时间与结构化学历；`OuterPostTypeID` 为未经验证的来源代码，原样保存不译码。

## 4. 字段映射

| 契约字段 | 腾讯来源 | 转换规则 | 缺失与冲突处理 |
| --- | --- | --- | --- |
| `source_job_id` | `PostId` | 强制转字符串，长 ID 不转浮点 | 缺失即解析失败，不输出 |
| `title_raw` | `RecruitPostName` | 原值，去首尾空白 | 空则登记问题 |
| `company_raw` | 固定「腾讯」 | 不推断法律用工主体 | — |
| `locations_raw` | `LocationName` | 按 `、 , ， / \|` 拆成数组，保留多地点 | 为空填 null 并登记 `missing_location` |
| `category_raw` | `CategoryName` | 原值 | 空则登记 `scope_review` |
| `description_raw` | `Responsibility` | 保留原文，不做 HTML 反转义 | 与职责要求同时为空登记 `missing_body` |
| `requirements_raw` | `Requirement`（详情） | 必须来自详情接口 | 缺失登记 `missing_requirements` |
| `experience_raw` | `RequireWorkYearsName` | 原值，不自行分档 | 缺失填 null |
| `education_raw` | 无结构化字段 | 固定 null，学历留待 ETL 从正文提取 | — |
| `employment_type_raw` | `OuterPostTypeID` | 原代码字符串，不译码 | 缺失填 null |
| `salary_raw` / `headcount_raw` | 接口未提供 | 固定 null，不补造 | — |
| `source_published_at_raw` | 无 | 固定 null | — |
| `source_updated_at_raw` | `LastUpdateTime` | 原文本，不当发布时间 | 缺失填 null |
| `source_url` | `PostURL` | 原值 | 缺失填 null |
| `observed_at` | 请求时间 | ISO 8601 UTC（`Z` 结尾） | — |
| `raw_refs` | `raw/list_*.json` + 详情文件 | `path` + 64 位小写 `sha256`，相对批次目录 | 必填非空 |
| `parser_version` | `tencent-collector-1.0.0+<commit>` | 常量加代码 commit | — |

## 5. 岗位范围与异常记录

- 类目白名单：`CategoryName` 含 技术/研发/数据/测试/运维/安全/算法/开发。
- 标题黑名单兜底：策划、美术、原画、动画、视觉设计、销售、商务、售前、产品经理、项目经理、招聘、人力资源、财务、法务、行政。
- 海外及港澳台地点排除；地点为空或类目为空照常输出并标记 `scope_review`，交 C 复核。
- 标题括号内的城市与 `LocationName` 不一致时（仅当括号内容全部是已知城市，避免把 `（U3D方向）` 误判），逐条登记 `location_conflict`，保留源字段原值，不修正、不丢弃。
- 排除项写 `quality_issues.jsonl`（`rule=scope_exclude`，含 ID、原因、原始引用），不写入 `jobs.jsonl`。

## 6. 限速、重跑与日志

- 单并发、间隔 ≥3 秒；网络错误最多重试 2 次（4s、8s 退避）。
- 断点续跑：已存在的 `raw/list_*.json`、`raw/detail_*.json` 直接复用，不覆盖原始字节；`jobs.jsonl` 中已有的 `source_job_id` 不重复写入；已排除、待复核与已登记问题不重复登记。恢复时 `observed_at` 取自 `requests.jsonl` 中该响应文件的 `requested_at`（详情缺失时退到列表响应时刻），不读文件修改时间；日志完全缺失才退化为当前时刻并登记 `observed_at_fallback`。
- 请求日志：一次 HTTP 调用中的**每一次尝试**都单独写 `requests.jsonl`（重试前的失败尝试也留痕），记录 `request_id`、URL、脱敏参数、HTTP 状态、业务成功标记、响应文件、编码、耗时、`attempt` 与错误；不保存 Cookie、Authorization、Token 或登录态。
- 清单计数：`counts.unprocessed_unique_ids` 与 `counts.unprocessed_ids` 明确记录“达到 target 时同页剩余、未输出也未排除”的岗位，便于逐项对账。
