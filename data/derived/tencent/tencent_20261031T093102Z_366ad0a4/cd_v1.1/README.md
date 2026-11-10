# C/D 交接 v1.1

2026-11-01，C 已完成已验收批次接入、详情补充字段、核心样本标记、技能证据桥与指标接口。当前数据文件由固定源版本和规则生成，清单保存输入版本和文件哈希。

## 给张淘然

直接下载同目录 `jobs_enriched.jsonl` 与 `manifest.json`。共 100 条岗位，`is_core=true` 为 98 条，另 2 条扩展样本保留原因。自然键仍为 source/source_job_id/batch_id，岗位 ID 保持字符串。

- 将 `additional_requirements_raw` 纳入下一版技能提取。该字段来自详情 ImportantItem，28 岗非空。新增字段用独立 evidence_field 标识，原文偏移按字段自身计算。
- 词典或规则变化时更新版本及正文哈希定义。当前 D 的 body_sha256 为职责和任职要求两项组成的 JSON 数组的 UTF-8 哈希，下一版三字段哈希需明确字段顺序并在 provenance 登记。
- 核心指标筛选 is_core=true，正文分母从筛选后的核心岗位集合重新计算。本批当前核心分母为 98，城市/经验等筛选后继续重算。技能分子只计 eligible_for_metric=true，并按岗位和技能去重。
- `location_conflict=true` 的 9 岗在规范化城市图归入“冲突待确认”。`confirmed_locations` 包含已复核的工作地，1 岗提供北京与深圳两个选择。城市分组计数可以重叠。
- `experience_conflict=true` 的 3 岗在规范化经验图归入“冲突待确认”。原始字段、来源引用与问题原文均保留在交接文件中。
- FDE 售前解决方案岗与游戏趋势研究岗本版归入扩展样本。按新版范围及三字段提取重算后，提交自己的 feature/analysis 分支和 PR，并用新的交叉抽检检验效果。

当前已入库的技能仍为 skills-rules-0.2.0，仅覆盖职责和任职要求。其核心样本有 311 对有效岗位×技能、83 个有有效技能的岗位。三字段新版结果交付后由 C 接入新的构建版本。

## 给钟洋

腾讯首批技术接入已完成。后续采集继续按 v1.0 保存完整原始详情，检查 ImportantItem、PostLightItem 是否保存，遇到字段变化及时登记。当前 28 条补充要求和附加工作地已从既有 raw 完成回补。

额外企业官网先提交入口、分页、详情及字段覆盖的可行性证据。小组联调通过后再按批准范围扩大采集并维护每日批次。新增来源遇到类似补充字段，在来源映射说明中登记，由 C 统一处理。

## C 的查询接口与实测结果

开发库 `recruitment_dw_dev_cd_v1` 的 `ads.cd_overview`、`ads.cd_job_detail`、`ads.cd_skill_evidence`、`ads.cd_skill_demand`、`ads.cd_skill_pair`、`ads.cd_city`、`ads.cd_experience` 已实际创建，查询时固定 build_id，本轮为 1。

- 原始岗位 100，核心岗位 98，补充要求 28，城市冲突 9，经验差异 3。
- 482 条技能证据分组保存到 461 条技能桥项，全部证据片段和偏移可回查。
- 14 项 Python 测试通过，dbt 的 14 个视图和 6 项质量测试通过。
- 独立 Python 与 SQL 的技能、组合、城市计数一致。相同输入重跑返回 unchanged，第 10 条故障注入后构建事务完整回滚。
- ADS 只读角色通过数据库测试用户验证。D 实际 Power BI 连接和三字段新版技能结果仍待联调。

执行说明与本地实例配置见[仓库运行入口](../../../../../warehouse/README.md)。
