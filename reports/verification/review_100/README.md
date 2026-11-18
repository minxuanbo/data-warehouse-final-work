# 100 个岗位的独立复核包

本包将原需求中含糊的“100 条”明确为 **100 个不同来源岗位**，每来源 50 个。原有 40 岗冻结参考和留出集继续保留；额外抽取 60 岗，不能用 323 个证据锚点或程序回查数冒充 100 岗人工复核。

`blinded_jobs.jsonl` 仅含真实原文、输入哈希和原始引用，不包含提取候选答案。`plan.json` 记录样本与规则哈希。生成包不等于已经核对完成，当前状态为 `pending_human_review`。

复核成员复制为 `submission.jsonl` 后逐岗阅读，填写真实 `reviewer`、`note`、`reviewed=true`，逐项填写 `labels`：`skill` 为标准技能名、`field` 为原文字段、`level` 为必需/优先/提及/不确定/否定，`evidence` 从原文逐字复制。确实未发现技能时填写空数组并设置 `no_skills=true`。不要修改原文、身份或哈希。

执行 `.\.venv-dbt\Scripts\python.exe -X utf8 -m scripts.prepare_review_100 --submission <实际提交文件路径>` 核验；任一岗位未复核时，整体精确率/召回率留空。结果是额外审计，不能替代原有独立留出评估，也不代表全国招聘文本的准确率。
