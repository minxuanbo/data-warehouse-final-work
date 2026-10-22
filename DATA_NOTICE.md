# 数据来源与使用说明

项目使用 Olist 发布的 [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)。

数据许可为 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)。使用、分享原始数据和衍生统计时应保留 Olist 署名及来源，限非商业使用，按相同许可分享适用的改编内容。仓库中的数据剖析结果、汇总 CSV 和指标输出注明为该数据的课程项目衍生结果，沿用上述数据许可。本说明不另行授予项目代码许可证。

原始 CSV 和下载包不上传 GitHub。请通过 `scripts/download_olist.py` 获取并校验；数据版本以 `data/source.json` 的归档哈希和 `data/manifest.csv` 的逐文件哈希固定。

本项目不修改原始文件。ETL 对缺失维度、代表评价、时间有效性和邮编映射进行派生处理，详细规则见设计报告与系统实现文档。原始数据包含缺失值和不一致记录，不能将其解释为真实完整的财务账本。
