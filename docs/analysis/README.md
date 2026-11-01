# D：腾讯增强版与网易首批技能分析

2026-11-01。输入为腾讯 C/D 交接 `cd_v1.1` 和最新 main 已验收的网易批次，各 100 岗。仅用 Python 标准库，直接读文件，无需数据库。

| 结果 | 腾讯增强版 | 网易初版 |
| --- | --- | --- |
| 输入 / 核心分母 | 100 / 98（C 已确认） | 100 / 98（D 范围建议，待 C 确认） |
| 全部技能证据 | 552 条，含 36 条附加字段证据 | 515 条 |
| 核心有效岗位×技能 | 333 对、涉及 83 岗 | 334 对、涉及 80 岗 |
| 交叉抽检 | 20 岗、5 城，开发/留出各 10 岗 | 20 岗、4 城，开发/留出各 10 岗 |
| 词典 / 规则 / 正文哈希 | skills-dict-0.2.0 / skills-rules-0.3.0 / skills-body-1.1 | 同左 |

140 项词典包含标准名、别名、类别及实际正文依据；新词只从开发及历史回归正文补充。新版分数与实际差错见[验证说明](验证说明.md)，筛选和 C 接入见[指标与联调](指标与联调.md)。

## 运行

在 `feature/analysis` 仓库根目录执行：

```powershell
git fetch origin main feature/warehouse
python -X utf8 -m unittest discover -s tests -v
python -X utf8 -m etl.skills.run --source tencent
python -X utf8 -m etl.skills.run --source netease
```

腾讯默认从本地 Git 固定 warehouse 提交 `e9c6ba35d3230ffc48e0181b18f3ba6f6cf77cfe` 读取交接文件，不合入 warehouse 代码，不重复提交增强数据。也可把下载的 `jobs_enriched.jsonl`、`manifest.json` 放同一目录：

```powershell
python -X utf8 -m etl.skills.run --source tencent --handoff-dir C:/path/to/cd_v1.1
python -X utf8 -m etl.skills.run --source tencent --city 冲突待确认 --output .local/tencent_city_check
python -X utf8 -m etl.skills.run --source netease --experience 不限 --output .local/netease_experience_check
python -X utf8 -m etl.skills.review score --source netease --output .local/netease_score.json
```

运行前核对原始清单内文件的字节/哈希、身份键、增强清单、原始正文映射和冻结版本；失败即停止。腾讯校验 128 个原始清单文件，网易校验 78 个。输出不能覆盖原始批次、交接目录或其父目录；专用输出中的同名派生结果会重建，是否成功以退出码和本次 provenance 为准。

## 交付文件

腾讯目录：[tencent…/v1.1](../../reports/analysis/tencent_20261031T093102Z_366ad0a4/v1.1/)。网易目录：[netease…/v1.1](../../reports/analysis/netease_20261101T044527Z_157cf969/v1.1/)。两个目录使用同一文件约定：

| 文件 | 用途 |
| --- | --- |
| `skill_evidence.jsonl` | C 接入的完整技能证据，保留全部 100 岗中的命中和 is_core |
| `input_provenance.json` | 输入、增强、词典、代码、参考哈希及正文哈希定义 |
| `reconciliation.json` | 核心/扩展 ID、技能去重数、技能组合、城市经验分组，供 C 对账 |
| `body_audit.csv` / `cross_review_20.csv` | 全批来源字段回查 / 20 岗正文审读、方向和问题 |
| `scope_review.csv` / `data_issues.jsonl` | 全批范围筛查与待确认的维度问题；网易两条人工标注岗列扩展建议 |
| `review_labels.csv` / `validation.json` / `validation_errors.jsonl` | 参考标签、实测分数及差错 |
| `metrics.json` / `dashboard.html` | 当前筛选下的指标和离线看板草图 |

`etl/skills/reviewed_samples_v1_1.json` 保存本版 40 岗参考；历史参考与腾讯目录根层结果仅作旧版记录，当前入口均指向 `v1.1/`。

## 证据契约

自然键为 `source/source_job_id/batch_id`，ID 保持字符串。一行证据粒度为岗位×原文字段×技能×命中位置，同岗同技能可有多行，指标需去重。

- 正文字段顺序固定为 `description_raw`、`requirements_raw`、`additional_requirements_raw`；网易第三项为 null。
- `evidence_field/evidence` 是原字段和原文分句；`raw_ref/raw_sha256/raw_field_name` 定位原始响应及原键。附加正文单独标 `additional_requirements_raw` / `ImportantItem`，不拼接成任职要求。
- `evidence_start/end` 与 `match_start/end` 为该字段内 Python Unicode 字符下标，左闭右开。CRLF 保留，既不是 UTF-8 字节偏移，也不是 JavaScript/SQL 的 UTF-16 偏移。
- 保留 `skill_name/skill_category`、`matched_text/matched_alias`、`requirement_level/context_polarity/alternative_group` 和词典/规则/哈希版本。
- `eligible_for_metric=true` 仅表示正向且强度为必需、优先或提及。否定、备选和其他不确定项保留证据但排除指标；还须筛选 is_core=true。
- `body_sha256 = SHA256(UTF8(json.dumps([job.get(f) for f in FIELDS], ensure_ascii=False)))`，沿用 Python 默认逗号/冒号分隔空格，不归一化换行，缺失为 null。`body_hash_version=skills-body-1.1`，与旧两字段哈希不可混用，也不能代替 C 的 SCD 内容哈希。

CSV 使用 UTF-8 BOM，长 ID 按文本导入；可能被 Excel 当公式的来源文本加单引号保护。机器接入使用 JSONL 原文。
