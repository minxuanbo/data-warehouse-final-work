# 数仓运行与交接说明

本页是 C 的当前操作入口，2026-11-18 更新。先读[逻辑模型](../docs/design/04_逻辑设计.md)理解分析事实；业务分析见[主题报告](../reports/analysis/岗位需求主题分析.md)。历史 trial/CD 脚本仍保留供追溯，新成员不必逐个猜测运行顺序。

## 1 环境准备

前置：Windows、Python 3.12、Git、SQL Server 2025 默认本机实例、ODBC Driver 18；首次创建专用开发库需要相应 Windows 权限。Power BI Desktop 只在查看报表时需要。不要使用其他组员的口令。

在仓库根目录执行：

```powershell
py -3.12 -m venv .venv-dbt
.\.venv-dbt\Scripts\python.exe -m pip install -r warehouse/requirements.lock.txt
```

已有该环境无需重建。默认 `lpc:localhost` 使用本机共享内存和当前 Windows 身份；其他实例通过 `DW_SERVER` 设置。localhost 指操作者自己的电脑，不是组长电脑。

## 2 从干净仓库重建固定真实基线

```powershell
.\.venv-dbt\Scripts\python.exe -X utf8 -m scripts.reproduce --database recruitment_dw_dev_reproduction
```

脚本校验固定 Git 修订下的仓库内 `data/`、`reports/analysis/<batch>/v1.1/` 和 `etl/skills/dictionary.json`，创建缺失的专用开发库，运行加载、提取接入、维度/日状态、dbt 模型和质量门，发布 sample 并对账。**不依赖组长电脑原有的 .local 输入目录**。Git 若缺固定修订，先获取完整 main 历史；不要绕过输入修订校验。

预期：两来源各 100 原始/98 核心/98 正文，腾讯 333、网易 334 对有效岗位技能；两日不完整，变化不可比较。各机器 build_id/release_id 可以不同。重复运行应 unchanged，不重复入账；不删除已有数据库来让测试通过。

运行结果在 `.local/reproduction/<库名>/result.json`；逐次 dbt 日志和运行记录在 `.local/pipeline_runs/`。错误时保留日志，不改原批次哈希/验收状态掩盖原因。可用 `--prepare-bi` 同时将当前报表固定到本次库；改报表连接前关闭 Desktop 工程。

## 3 检查主题接口和文档

```powershell
.\.venv-dbt\Scripts\python.exe -X utf8 -m scripts.check_subjects --database recruitment_dw_dev_reproduction
.\.venv-dbt\Scripts\python.exe -X utf8 -m scripts.document_warehouse --database recruitment_dw_dev_reproduction
```

第一条按固定发布读取真实明细，独立聚合核对岗位结构、门槛人口和技能分子/分母，生成主题分析。第二条从实际元数据生成对象字典及完整的新增 dbt 模型/字段说明。生成结果会标记本机库与发布号，不把代理键写死为其他机器的数字。

完整离线回归使用单独的历史夹具（其中有故意保留 pending 的旧批次，用于拒绝非法提升等测试），准备及运行：

```powershell
.\.venv-dbt\Scripts\python.exe -X utf8 -m scripts.prepare_test_inputs
.\.venv-dbt\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

这些历史夹具与当前接入基线分开，不加入正式业务样本。当前模型在 `dbt` 下可执行 build/test/docs generate，先设置 `DW_DATABASE` 为自己的专用库；不要忘记环境变量而误以为 dbt 读取了新库。

## 4 Power BI 固定版本与验收

关闭 Recruitment 后执行：

```powershell
.\.venv-dbt\Scripts\python.exe -X utf8 -m scripts.pin_powerbi --database recruitment_dw_dev_reproduction
```

它只读选取已发布 sample，固定日分析 release 和每来源最新的 CD 输入，保留现有页面布局，设置显式关系与中文标题/版本提示。随后打开 `dashboards/powerbi/Recruitment.pbip`，应用外部更改并刷新。

**首次在每台电脑检查：文件 → 选项和设置 → 选项 → 当前文件 → 数据加载 → 关系，关闭“加载数据后自动检测新关系”。**该设置不能只靠模型字段名或代码删除一次关系代替。刷新保存后运行静态契约，若 Desktop 又添加关系必须处理，不忽略失败：

```powershell
.\.venv-dbt\Scripts\python.exe -X utf8 -m unittest tests.test_powerbi_contract -v
```

第 06 页按年/季度/月/日、省/市展开，类别总计右键钻取第 07 页，点岗位联动证据，Ctrl+单击返回。基线未筛选为 196 核心岗；FALSE 为保留的审计证据，不进入技能指标。第 01—03 页类别是来源原类别，第 06—07 页为标准方向，不混用。

真实 DAX 验收使用 `scripts/check_powerbi.ps1` 对指定 Desktop 引擎端口执行，先校验已加载查询、度量和关系与文件相同，再运行用例；不据 SQL 测试或旧模型哈希宣称报表通过。日后改连接/构建或模型后必须重新生成相应期望和绑定当前哈希的验收记录。

## 5 接新批与定时加工

采集成员提交 `data/<source>/<新batch_id>/`，按[采集规范](../docs/小组项目说明与采集交付规范.md)技术验收；accepted 与 complete 两个状态分开。新增来源和范围变化先审核设计，不直接混入趋势。

`warehouse/pipeline.json` 的 discover_roots 发现两个来源目录中的已验收批次，校验输入确已存在于 Git，自动生成单独分析证据并处理；pending 批次只列待办，不自动批准。

```powershell
.\.venv-dbt\Scripts\python.exe -X utf8 -m scripts.run_pipeline --dry-run
.\.venv-dbt\Scripts\python.exe -X utf8 -m scripts.run_pipeline
```

本流水线处理已验收批次，**不调用采集器、不自动 git pull、不生成新一天观察、不刷新 Power BI**。注册日 22:30 计划任务见 `scripts/register_pipeline_task.ps1`；须用户登录且机器可运行，是否注册/试跑以带日期实测为准。

## 6 接口与排错

- B01：`ads.release_job_structure`；B02：`ads.release_skill_profile`；B03：`ads.release_entry_profile`。先查发布指针选定 release，再按该版本查询；历史发布可以回读，不累加多个 release。
- 原文：岗位明细→batch/source_revision→raw_ref/哈希→证据字段与 Unicode 字符位置。正文载荷不是关系键。
- 同 batch_id 内容变化拒绝覆盖；迟到/同刻冲突拒绝静默改历史；应保留证据、修版本或在另一个专用库重建。
- 发布失败保留上一指针。正式 formal 必须批准来源集合各日完整；当前 partial 禁止提高标志绕过质量门。
- 2026-11-17 已有备份/恢复与回滚记录；本版从原始批次重建是另一个复现验证，不能互相替代。

规范字段和实际对象见[字典](../docs/reference/仓内对象字典.md)。当前课程整改状态统一见[验收表](../docs/verification/课程整改与答辩逐项核查.md)，不要从旧 trial 报告推断当前能力。

## 7 门槛字段修正与复验

腾讯不需要为本次问题重采：原经验和正文已存在，修的是 ETL。当前规范化为 conformed-cn-1.1；学历由结构化值及任职/补充正文带证据派生，不把缺失当不限，不把优先当必需。来源/正文不一致单列冲突，原始采集文件及旧 release 均保留。

第01—03页的门槛字段通过固定 qualification_release_id 关联新派生；第06—07页同一release。第07页新增学历与经验原文依据。`python -X utf8 -m scripts.check_qualifications` 可只读核对分组、逐字位置和旧版本。

本批网易新增标出结构化学历与正文不一致的问题，当前核心25岗进入学历冲突组（含原1岗）。这是保留冲突，不是将这些岗位移出核心或采集失败；具体两边原文在门槛核查记录中，后续人工复核再裁定。
