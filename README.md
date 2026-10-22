# 电商交易与履约分析数仓系统

数据仓库课程期末项目。使用 Olist 真实公开电商数据，已实现可重复运行的 PostgreSQL 离线数仓，包括原始数据验收、分层 ETL、质量检查和交易、履约、评价 KPI。

**组员先看：第六章已经有实际代码、数据库运行结果和测试证据；第七章的交互看板与最终答辩材料仍需完成。**

## 当前进度

| 工作项 | 状态 | 查看位置 |
| --- | --- | --- |
| 项目背景、需求、概念、逻辑、物理设计 | 已完成初稿，需最终统一排版 | [前五章](docs/01_项目设计报告_前五章.md) |
| 真实数据获取与验收 | 9 个 CSV 已验收，异常有记录 | [验收报告](reports/data_profile.md) |
| PostgreSQL 建库及 ODS 导入 | 已实际运行 | `sql/01_warehouse_schema.sql`、`scripts/warehouse.py` |
| DIM、DWD、DWS、ADS | 已实现并通过层间核对 | `sql/02_runtime_and_marts.sql`、`sql/03_transform.sql` |
| KPI 与查询结果导出 | 7 类查询已实现 | [结果目录](reports/system/) |
| 重跑、回滚、从空库重建 | 已测试 | [集成测试](reports/system/integration_tests.json)、[空库测试](reports/system/fresh_database.json) |
| 只读账号、备份恢复 | 已提供脚本及实际验证证据 | `scripts/provision_reader.py`、`scripts/test_backup_restore.py` |
| 第六章系统实现文档 | 已完成 | [第六章](docs/04_系统实现_第六章.md) |
| Superset 交互看板、第七章 | 待完成；已有可直接连接的 ADS 视图 | 交易、履约、用户评价三个看板 |
| 全文 Word、PPT、录屏、彩排 | 待组员整合 | [实施路线](docs/02_实施路线与验收清单.md) |

当前实现使用 **Python + PostgreSQL + SQL**。前期方案中的 dbt 和 Superset 尚未接入，不把配置计划写成已完成的功能。Python 管理批次和事务，SQL 管理转换及指标，依赖和执行顺序在仓库中明确保存。

## 重要数据口径

- 全部订单 99,441 笔，其中已送达 96,478 笔。交易核心指标使用 `delivered` 状态，按下单日期归属。
- 商品销售金额为 **13,221,498.11 BRL**，不含运费。不能称为利润或退款后的净收入。
- 有 **1 笔已送达订单缺少支付记录**。系统保留订单，不补造支付。`recorded_payment_amount` 是已记录金额；`complete_payment_amount` 在缺失时为 NULL，并同时展示缺失数和覆盖率。
- 有效配送样本 96,470 笔。逾期按实际到货日期大于预计到货日期判断，同一天到货不算逾期。
- 每订单按固定规则保留一条代表评价，全部原始评价仍保留于 ODS。无评分不按零分处理。
- 日逾期率不能直接平均成月逾期率。品类或卖家的订单数也不能跨组相加得到全局订单数。
- 原始文件不上传 GitHub。数据及适用衍生结果的来源、署名和许可见 [DATA_NOTICE.md](DATA_NOTICE.md)。

## 项目结构

```text
data/source.json                 数据发布源、归档哈希与许可
data/manifest.csv                逐文件行数、字段数、大小与哈希
data/raw/                       原始 CSV，本机生成，Git 忽略
scripts/download_olist.py        下载并验证真实源数据
scripts/audit_olist.py           源数据验收
scripts/verify_olist_audit.py    标准库独立核验
scripts/warehouse.py             建库、ETL、核对、导出、性能测试
scripts/local_postgres.py        Windows 独立数据库启动与停止
scripts/test_system.py           重跑、回滚、指标规则测试
scripts/test_fresh_database.py   空库完整流程测试
sql/                            表结构、加工 SQL、分析查询示例
docs/                           设计与实现报告
reports/data_acceptance/         源验收汇总；行级明细在本机生成
reports/system/                  数据库运行和测试证据、KPI CSV
.local/                         数据库文件、备份、只读密码，Git 忽略
.runtime/                       Windows PostgreSQL 程序，Git 忽略
```

## Windows 快速启动

需要 Git、Python 3.12、联网下载能力及约 2 GB 可用空间。本机已验证 Python 3.12.10、PostgreSQL 17.6。以下命令在 PowerShell 执行。每一步若出现未说明的错误，先停止并检查，不能跳过错误继续提交结果。

### 1 克隆并创建虚拟环境

```powershell
git clone https://github.com/minxuanbo/data-warehouse-final-work.git
cd data-warehouse-final-work
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

### 2 准备 PostgreSQL

```powershell
.\.venv\Scripts\python.exe scripts/fetch_postgres.py
.\.venv\Scripts\python.exe scripts/local_postgres.py start
```

脚本将 EDB 分发的 PostgreSQL 17.6 程序下载到 `.runtime/`，将数据库放入 `.local/pgdata/`，只监听 `127.0.0.1:55432`，不安装系统服务。首次启动会生成随机密码并写入 `.env`。**选择这个方式时不要预先复制 `.env.example`**，否则脚本会保护现有配置并拒绝覆盖。不要把 `.env` 发到群里或提交 Git。

再次开机后只需运行 `local_postgres.py start`。停止项目数据库用：

```powershell
.\.venv\Scripts\python.exe scripts/local_postgres.py stop
```

如果使用已有 PostgreSQL 或 Docker，请跳过上面两条安装命令，复制 `.env.example` 为 `.env`，填写自己的主机、账号、密码及已创建的空数据库。Docker 示例为 `docker compose up -d`，默认映射本机 5432；需先填写 `.env` 中的 `PGPASSWORD`。**Docker 配置已提供，但本机实际验证使用 Windows 独立数据库，未执行 Docker 部署测试。**

### 3 获取并验收真实数据

```powershell
.\.venv\Scripts\python.exe scripts/download_olist.py
.\.venv\Scripts\python.exe scripts/audit_olist.py
```

当前固定源数据存在上述 1 笔缺失支付，验收脚本会返回退出码 2，这是已记录的质量结果。读取 `reports/data_profile.md` 后继续：

```powershell
.\.venv\Scripts\python.exe scripts/verify_olist_audit.py
```

独立核验应返回 0。不要把所有非零退出码都当成可忽略：后续 ETL 只允许已声明的支付完整性问题，文件哈希、字段、主键等其他阻断问题会停止执行。下载脚本使用发布接口，下载时的包若与已固定归档哈希不同，会报错；应重新验收版本差异，不能直接覆盖清单。

### 4 运行数仓

```powershell
.\.venv\Scripts\python.exe scripts/warehouse.py run
.\.venv\Scripts\python.exe scripts/warehouse.py verify
.\.venv\Scripts\python.exe scripts/warehouse.py export
```

`run` 会初始化空库、装载或复用 ODS 批次、维护维度、在同一事务内替换事实及刷新宽表，核对成功后导出结果。相同输入再次执行会复用原始层，不重复导入。`passed_with_warnings` 表示限定口径的数仓处理成功，**不表示原始支付完整性问题已被修复**。

只创建结构可以运行 `warehouse.py init`。不要另外手工执行初始化 SQL 后再运行 CLI，以免生成缺少版本记录的半套结构。已存在且未受本项目版本管理的表结构不会被脚本自动删除。

`warehouse.py run --strict-payment` 会把缺失支付视为整个批次的阻断项。对当前数据，该命令应失败，并保留此前已发布快照。

## 组员如何查看结果

无需启动看板即可先查看 [KPI 概览](reports/system/kpi_overview.csv)、[月度交易](reports/system/trade_month.csv)、[地区履约](reports/system/fulfillment_state.csv) 和 [配送评分对比](reports/system/delivery_review_comparison.csv)。CSV 中空白表示 NULL，比例数值为 0 到 1，金额单位为 BRL。仓库保存的是本次实测快照，自己运行后会更新本机输出。

使用 pgAdmin、DBeaver 或其他 PostgreSQL 客户端连接 `.env` 所配置的数据库，执行：

```sql
SELECT * FROM ads.kpi_overview;
SELECT * FROM ads.trade_month ORDER BY year_no, month_no;
SELECT * FROM ads.fulfillment_state ORDER BY late_rate DESC;
SELECT * FROM ads.delivery_review_comparison;
```

完整示例在 [分析 SQL](sql/04_analysis_examples.sql)。数据库中可以查询 `audit.pipeline_run`、`audit.quality_result` 查看运行状态。故意注入失败及严格支付测试会产生 `failed` 日志，这是测试证据；结合 `error_message` 判断原因。

## 验证与维护

```powershell
.\.venv\Scripts\python.exe scripts/test_system.py
.\.venv\Scripts\python.exe scripts/test_fresh_database.py
.\.venv\Scripts\python.exe scripts/warehouse.py benchmark
.\.venv\Scripts\python.exe scripts/provision_reader.py
.\.venv\Scripts\python.exe scripts/test_backup_restore.py
```

集成测试会重建当前项目快照，并执行两次预期失败。空库与恢复测试会临时创建一个新数据库，在验证结束后只删除该测试数据库，需要开发账号有建库权限。不要针对生产数据库运行本课程测试。

只读账号 `olist_reader` 的密码保存在本机 `.local/reader.env`，可查询 ADS，但不可直接读取 ODS、DWD 和审计表。备份保存在 `.local/olist_dw.dump`，不含登录角色密码。恢复到其他机器时应重新配置账号权限。

实测：空库导入与转换约 **32.716 秒**，复用 ODS 后转换约 **25.366 秒**；7 类查询各预热一次再执行三次，最大耗时约 **207.167 毫秒**。这是 i7-14650HX、约 16 GB 内存 Windows 环境的单机测试，不是并发吞吐能力承诺。

GitHub Actions 提供手动触发的 `Full warehouse verification` 工作流，使用 PostgreSQL 服务运行验收和测试。提交代码不自动触发下载大数据；本次本地验证不等于该远程工作流已经执行。

## 接下来谁做什么

| 模块 | 已有基础 | 下一项工作 |
| --- | --- | --- |
| 数据与 ETL | 下载、验收、COPY、批次、转换全部可运行 | 复现一遍，整理 ETL 操作截图与录屏 |
| 建模与质量 | 维度事实表、约束、对账、失败回滚 | 审核指标口径，补充字段字典说明与模型展示 |
| 分析与可视化 | ADS 和 7 类查询结果 | 接 Superset，完成交易、履约、评价三个交互看板和第七章 |
| 文档与答辩 | 前五章、第六章、测试证据、README | 填写真实姓名学号，整合 Word、PPT、录屏及结语 |

代码改动建议先建分支，运行相关验证后提交；不要修改原始 CSV 来让测试“通过”。组员均应能讲清楚订单与明细的粒度差别、支付缺失处理、代表评价选择和防止金额放大的方法。
