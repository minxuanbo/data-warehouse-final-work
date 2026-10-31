# C 分工：腾讯小批试验入库

本轮完成可执行的 **原始批次校验 → SQL Server ODS/DIM/DWD → dbt DWS/ADS 试验接口**。代码位于 `feature/warehouse`；腾讯采集器及原始批次属于 PR #1，不重复提交、不合并它来掩盖待修问题。

默认库为 **recruitment_dw_dev**，不写其他课程库或正式库。输入固定为 PR #1 提交 `f6eccadec28a4a1132c5953bbd92470c1d794348` 的批次 `tencent_20261031T093102Z_366ad0a4`。源验收状态仍为 pending，覆盖仍为 partial。实际验证结果见[小批联调记录](../reports/warehouse/腾讯小批联调.md)。

## 1. 从干净环境复现

前置：Windows、Python 3.12、SQL Server 2025 本机默认实例、ODBC Driver 18、Git。首次初始化需要 Windows 身份具备创建开发库权限；不得在无权限时改用他人密码。以下从仓库根目录运行：

```powershell
python -m venv .venv-dbt
.\.venv-dbt\Scripts\python.exe -m pip install -r warehouse/requirements.lock.txt
.\scripts\run_trial.ps1
```

本轮 C 的入库和 dbt 共用 `.venv-dbt`，锁文件包含 pyodbc；A/B 的采集环境仍独立。锁文件在 Windows/Python 3.12.10 验证，不能据此保证任意系统组合。

默认使用 `lpc:localhost`、Windows 身份、ODBC 18；dbt 的 `port: null` 不拼接端口。这是**同一台 Windows 电脑的共享内存连接**，已真实跑通，不要求开启 TCP 或重启 SQL Server。`trust_cert: true` 仅用于本机开发自签名证书；不能原样作为公网配置。

其他成员使用自己的本机 SQL Server。需要不同本机实例时设置 `DW_SERVER`；需要独立开发库时设置 `DW_DATABASE=recruitment_dw_dev_<成员标识>`。脚本只允许此命名范围。`localhost` 在张淘然电脑上指向他自己的数据库，并不指向组长电脑。

`run_trial.ps1` 会提取固定 PR 数据到 `.local/pr1_input/`，创建缺失的开发库/表、校验入库，再执行 dbt build。首次若缺 Git 对象，会从 origin 获取 PR 引用；不运行钟洋的采集器、不再次访问招聘站、不将腾讯数据加入本分支。已有本地输入与固定提交不同会拒绝覆盖。

若输入为后来另一个已审查批次，显式传入 `-BatchPath` 与对应完整 `-Revision`。不能只改路径却沿用旧 revision。后续 PR 修正若改变同一 batch_id 的清单，当前库会拒绝覆盖；试验阶段可使用新的个人开发库验证修订输入，不能删除旧证据掩盖变化。

## 2. 本轮目录与实现边界

| 位置 | 职责 |
| --- | --- |
| `warehouse/validate.py` | 文件清单/哈希、字段类型、必填值、源 ID 唯一性、带时区时间、原始引用与路径安全校验 |
| `warehouse/load.py` | 专用开发库初始化、ODS 原值入库、身份/内容版本、观察与地点桥、事务与幂等 |
| `sql/001_trial_schema.sql` | 可重复执行的六层 Schema 和持久表、唯一键/外键/检查/索引 |
| `dbt/` | 2 个 DWS、3 个 ADS 试验视图及 4 个质量测试，SQL 使用 T-SQL |
| `scripts/run_trial.ps1` | 单入口，前一步失败即停止，不创建后台定时任务 |
| `tests/`、`scripts/check_trial_db.py` | 离线契约/历史规则测试、真实库幂等/回滚与计数检查 |

raw_response 存 Git 文件相对路径、哈希、字节数；完整响应留在固定 Git 批次，通过 source_revision 可恢复。ODS JSON 保留所有规范字段；147 条源质量记录独立入审计表。SCD2 内容哈希只含岗位属性，不含采集时间和文件引用；A→B→A 生成新区间，迟到或同时间冲突拒绝静默重写，需显式历史重建。当前只验证了单批真实数据，历史变化规则另有离线测试，尚无多日真实样本证据。

这是完整设计的**小批实施切片**：source 保留自然代码，企业/学历/经验/招聘类型保留原值；地点桥使用 `raw_location_v1`，不是完成了行政区划规范化。未实现跨源归并、完整一致性维度、正式每日快照、D 的技能桥和正式发布指针；因此接口统计名称为“来源岗位数”，不冒称跨源独立岗位数。

所有 ADS 接口都以 `trial_` 开头并暴露 pending/partial；没有发布动作，也没有生成正式新增/下架趋势。开发者账号本轮用于复现，正式只读 BI 身份、备份恢复及调度验收留待集成阶段，不宣称已通过。

## 3. 张淘然现在可以接什么

| 视图 | 粒度 | 用途 |
| --- | --- | --- |
| `ads.trial_overview` | 一批次 | 样本量、正文覆盖、缺失数量、源版本及状态 |
| `ads.trial_city` | 一批次×原始地点 | 城市样本分布，岗位地点多值时城市计数不可简单相加 |
| `ads.trial_job_detail` | 一批次×来源岗位 | 标题、原始分类/学历/经验/类型、来源链接、内容版本及正文 JSON |

每张图先固定 batch_id。`content_json` 是完整 Unicode JSON，其中 `description_raw` 和 `requirements_raw` 是技能提取输入；用 Python JSON 或 Power Query JSON 解析，避免 SQL JSON_VALUE 的短字符串限制截断正文。原始地点与标题城市冲突仍保留，不把列出的 5 个城市视为已人工裁定。

```sql
SELECT * FROM ads.trial_overview;
SELECT * FROM ads.trial_city ORDER BY source_posting_count DESC;
SELECT source,source_job_id,batch_id,version_key,title_raw,content_json
FROM ads.trial_job_detail
WHERE batch_id='tencent_20261031T093102Z_366ad0a4';
```

无法立即安装数据库的成员可先读取 PR 原始 jobs.jsonl。组长也可执行 `.\.venv-dbt\Scripts\python.exe -m warehouse.export_trial`，得到 `.local/trial_exports/` 中的三个 JSONL；这些是可再生联调结果，默认不向 Git 重复提交正文，正式 D 输出放其自己的 feature/analysis 分支。

建议 D 交回以 `(source,source_job_id,batch_id)` 定位的技能证据；带词典/提取规则版本、技能标准名、强度、正文片段及所在字段。C 再核对版本键、建技能桥，D 不自行更新仓内事实表。

## 4. 检查命令

```powershell
.\.venv-dbt\Scripts\python.exe -m unittest discover -s tests -v
.\.venv-dbt\Scripts\dbt.exe build --project-dir dbt --profiles-dir dbt
.\.venv-dbt\Scripts\python.exe -X utf8 -m scripts.check_trial_db
```

最后一条额外使用空库 `recruitment_dw_dev_rollbackcheck`：第 10 条后注入失败，所有业务表必须仍为空。若该测试库已有数据则停止，避免影响既有内容；本轮保留空测试库供复验。主开发库重跑必须返回 unchanged，行数不增长。测试修改的文件只存在 `.local/tests/` 临时副本，不混入真实样本。

后续顺序：钟洋修复 PR #1 → 复验接入规范 → 网易小批到齐后复用验证 → 接 D 的技能与人工分类规则 → 完善正式快照、发布、权限及恢复 → 持续采集与正式指标对账。当前成功不等于这些任务已全部完成。
