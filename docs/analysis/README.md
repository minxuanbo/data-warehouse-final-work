# D：腾讯小批技能提取与分析

2026-11-01，基于main `25b397bf846a8e7c39bbc249e0700428e89bc0c3`，分支 `feature/analysis`。直接使用仓库内腾讯100条数据，仅依赖Python3.12标准库。

| 当前五项交付 | 文件 | 结果 |
| --- | --- | --- |
| 正文抽检 | `reports/analysis/<batch>/sample_review_20.csv` | 20岗、5城、不同方向，记录原始详情定位与问题 |
| 技能词典 | `etl/skills/dictionary.json` | 87项，标准名、别名、类别和实际正文依据 |
| 程序及结果 | `etl/skills/extract.py`、`run.py`；`skill_evidence.jsonl` | 100岗运行，482条证据，带身份键、强度、原文及版本 |
| 核对与验证 | `etl/skills/reviewed_samples.json`；`validation.json` | 开发10岗、最终10岗分开；实际差错和分数见[验证说明](验证说明.md) |
| 指标与草图 | `dashboard.html`；[指标与联调](指标与联调.md) | 分母/未知值明确，浏览器可离线筛选、下钻 |

本批结果见[结果目录](../../reports/analysis/tencent_20261031T093102Z_366ad0a4/)，字段与接入方式见[指标与联调](指标与联调.md)。抽检发现的附加要求、城市及经验问题均保留来源原值，未改采集数据。

## 运行

在含腾讯批次的仓库根目录执行，无需安装数据库或pip依赖：

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 -m etl.skills.run
python -X utf8 -m etl.skills.run --output .local/analysis_check
```

默认输入 `data/tencent/tencent_20261031T093102Z_366ad0a4/`，输出 `reports/analysis/<batch>/`。运行前校验128个清单文件字节/哈希、身份键、原文引用和冻结版本，失败停止。输出目录不得覆盖输入或其父目录；专用输出中的同名派生结果会重建。判断是否本轮成功应看退出状态及provenance，不能用失败后残留的旧文件代替。

输入为accepted/pilot_technical且coverage_status=partial，属于采集技术接入状态，不表示所有业务口径均已验收。换批次或调整规则后，原参考与分数不会自动适用。

## 结果契约

一行JSONL是一处岗位×字段×技能×位置的证据。同岗同技能可有多行，指标先去重。

| 字段 | 含义 |
| --- | --- |
| `source, source_job_id, batch_id` | 来源身份键；ID始终是字符串 |
| `skill_name, skill_category` | 标准技能及类别 |
| `requirement_level` | 必需/优先/提及/不确定 |
| `context_polarity` | positive/negated/alternative/uncertain |
| `evidence_field, evidence` | 原文字段与完整所在分句 |
| `evidence_start/end, match_start/end` | Python Unicode字符下标，左闭右开；不是UTF-8字节或JS UTF-16偏移 |
| `matched_text, matched_alias` | 原始命中及词典别名 |
| `alternative_group` | 备选条件所在分句；不表示每项同时必需 |
| `dictionary_version, rule_version` | skills-dict-0.1.0 / skills-rules-0.2.0 |
| `eligible_for_metric` | 仅positive且强度必需/优先/提及时为true |
| `body_sha256` | JSON([description_raw,requirements_raw],ensure_ascii=False)的UTF-8 SHA-256；只标识D输入正文，不代替C的内容哈希 |

标题不参与技能提取。程序处理边界、最长别名、否定及局部优先；备选组保守排除出默认指标。当前仍有别名及语境范围问题，已按真实结果记入验证说明。

CSV为UTF-8 BOM查看副本，ID列应按文本导入Excel；来源文本以=、+、-、@开头时加前导单引号避免被当公式。机器接入使用JSONL，原文不作此改写。

`etl/skills/review.py`按冻结参考计算验证结果，由主运行器调用。完整Power BI、数据库执行与交叉审阅在后续联调进行。
