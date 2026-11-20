# 小批最终证据索引

当前主库sample release8、build10/11、分析输入v1.3。`evidence_audit.json`、`qualification_conflict_dispositions.jsonl`、`primary_direction_review.jsonl`和`ai_skill_evidence_audit.jsonl`为当前规则的AI辅助审计，human字段为null。

`clean_first_run.json`保留首轮真实流水线日志，外层人口检查取相同输入的复跑结果；`clean_second_run.json`证明同一release1与build1/2重跑unchanged。`clean_source_hashes.json`列出复现时精确复制的实现和v1.3输入。`dbt_checks.json`为复跑的37模型/16检查实际状态。共享本机固定Python环境及只读Git对象，没有声称跨人/跨机验收。

主题对账在本目录。最终SQL训练案例对账和26个交叉主方向候选包在`release8-sql-final/`；三个正文与全部200个固定输入逐项一致。`release8/`是补充字段修复前的中间导出；`release8-final/`为修复后的文件独立复算。本目录顶层同名训练候选包为release7中间导出，保留历史，不作为当前人工裁定；全部200岗AI方向审计另见当前文件。新候选包字段reviewer=null、reviewed=false是未填写的人工模板，不能据此否定已完成的AI技术审计，也不能把AI技术审计称为人工签字。

旧review_100包及其人工状态未改动。本轮不报告人工precision/recall，扩量需新留出样本。

最终状态见`closeout_summary.json`；`powerbi_validation.json`是Desktop保存并按LF规范后绑定当前模型/用例哈希的93项通过记录；before_save为同一已刷新模型保存前检查。`ui_validation.json`及7张ui_*.png为实际操作证据，截图未编辑。
