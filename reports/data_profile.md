# Olist 数据验收报告

验收时间：2026-10-22T22:31:54.381835+08:00（北京时间）。结论：**文件与结构验收通过；支付完整性未通过，限制完整支付金额指标发布**。

本次实际下载并逐表读取了 9 个 CSV，未改写原始数据。共执行 156 项检查，1 项阻断失败，22 项需按规则处理或披露的告警。此结论是源数据可用性验收，不表示数仓已建成或全部数据无异常；不存在已执行的数据库对账。

数据可以按原样进入 ODS，并继续开发交易、履约和评价模型。支付完整性失败不会通过补造支付记录解决：保留缺失标记，暂不把已记录支付金额表述为全量应有支付金额。脚本对未关闭的阻断项返回非零退出码，这是预期的质量检查结果。

## 1 来源与完整性

发布者：Olist。数据集：Brazilian E-Commerce Public Dataset by Olist。

发布页：https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce 。下载接口：https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce 。许可：CC BY-NC-SA 4.0；发布页许可信息已核对。下载时间：2026-10-22T22:19:01.486550+08:00。

API 使用下载时的最新包，未声称取得数值版本号；以 ZIP SHA-256 固定此次内容版本：`967e41e04fc306fe604e2a693f488995a8b41e5047418f8a5c8e4abd6deca784`。压缩包 CRC 检查通过，解压文件哈希与压缩包内成员一致。UTF-8 解码成功，CSV 字段数符合契约。翻译文件带 BOM，读取必须使用 `utf-8-sig`。

| 文件 | 数据行数 | 字段数 | 字节数 | 完全重复多余行 |
| --- | --- | --- | --- | --- |
| olist_orders_dataset.csv | 99,441 | 8 | 17,654,914 | 0 |
| olist_order_items_dataset.csv | 112,650 | 7 | 15,438,671 | 0 |
| olist_order_payments_dataset.csv | 103,886 | 5 | 5,777,138 | 0 |
| olist_order_reviews_dataset.csv | 99,224 | 7 | 14,451,670 | 0 |
| olist_customers_dataset.csv | 99,441 | 5 | 9,033,957 | 0 |
| olist_products_dataset.csv | 32,951 | 9 | 2,379,446 | 0 |
| olist_sellers_dataset.csv | 3,095 | 4 | 174,703 | 0 |
| olist_geolocation_dataset.csv | 1,000,163 | 5 | 61,273,883 | 261831 |
| product_category_name_translation.csv | 71 | 2 | 2,613 | 0 |

行数按 CSV 逻辑记录计算，排除表头；评价文本包含换行，不能用文本文件物理行数代替。每文件 SHA-256、来源和下载时间见 `data/manifest.csv`。

## 2 主键与关联

| 表 | 候选键或诊断键 | 不同键数 | 重复多余行 | 冲突行 |
| --- | --- | --- | --- | --- |
| orders | order_id | 99441 | 0 | 0 |
| items | order_id+order_item_id | 112650 | 0 | 0 |
| payments | order_id+payment_sequential | 103886 | 0 | 0 |
| customers | customer_id | 99441 | 0 | 0 |
| products | product_id | 32951 | 0 | 0 |
| sellers | seller_id | 3095 | 0 | 0 |
| translation | product_category_name | 71 | 0 | 0 |
| reviews | review_id | 98410 | 814 | not_a_primary_key |
| reviews | order_id | 98673 | 551 | not_a_primary_key |
| geolocation | geolocation_zip_code_prefix | 19015 | 981148 | not_a_primary_key |

`review_id`、评价表的 `order_id`、地理位置表的邮编前缀均不视为主键。评价保留全部原始行，后续每订单按回复时间、创建时间、review_id 和来源记录号降序选择一条代表评价。当前 547 个订单有多条评价，选择后 98,673 行，551 行不进入代表评价事实，仍保留在 ODS。选择结果见 `selected_review_keys.csv`。

| 子表 | 关联字段 | 父表 | 子表行数 | 孤立行 |
| --- | --- | --- | --- | --- |
| orders | customer_id | customers | 99441 | 0 |
| items | order_id | orders | 112650 | 0 |
| items | product_id | products | 112650 | 0 |
| items | seller_id | sellers | 112650 | 0 |
| payments | order_id | orders | 103886 | 0 |
| reviews | order_id | orders | 99224 | 0 |

客户记录有 99,441 条，独立购买者为 96,096 人；已送达订单对应 93,358 名独立购买者。这三个数量不可混用。

## 3 缺失值与异常

下表只列出有缺失的字段，完整字段清单及类型检查见 `field_profile.csv`。

| 表 | 字段 | 空值数 | 空值比例 |
| --- | --- | --- | --- |
| orders | order_approved_at | 160 | 0.1609% |
| orders | order_delivered_carrier_date | 1783 | 1.793% |
| orders | order_delivered_customer_date | 2965 | 2.9817% |
| reviews | review_comment_title | 87658 | 88.3435% |
| reviews | review_comment_message | 58274 | 58.7297% |
| products | product_category_name | 610 | 1.8512% |
| products | product_name_lenght | 610 | 1.8512% |
| products | product_description_lenght | 610 | 1.8512% |
| products | product_photos_qty | 610 | 1.8512% |
| products | product_weight_g | 2 | 0.0061% |
| products | product_length_cm | 2 | 0.0061% |
| products | product_height_cm | 2 | 0.0061% |
| products | product_width_cm | 2 | 0.0061% |

评价标题和正文缺失不影响评分分析，不补造文本。商品属性或品类缺失保留未知值。缺少翻译的原品类为 pc_gamer, portateis_cozinha_e_preparadores_de_alimentos，保留葡语原名，不丢弃商品。邮编在 DIM 中补齐至五位，不能覆盖 ODS 原值。地理坐标需去重、筛查，再按邮编聚合；原始地理表不能直接连接订单。

## 4 时间与状态

下单时间实际范围：2016-09-04 21:15:19 至 2018-10-17 17:30:18。月度覆盖及观察到的首末日期见 `monthly_coverage.csv`；边界月份和稀疏月份需单独标记，不能自动当作完整月份计算环比。

时间范围内没有观察到订单记录的月份：2016-11。2016 年及 2018 年 9—10 月记录稀疏，建议主趋势图先使用 2017 年 2 月至 2018 年 8 月，并另行展示全时段覆盖情况；这一选取是分析范围建议，不证明这段期间包含平台全部真实订单。

| 订单状态 | 订单数 |
| --- | --- |
| approved | 2 |
| canceled | 625 |
| created | 5 |
| delivered | 96478 |
| invoiced | 314 |
| processing | 301 |
| shipped | 1107 |
| unavailable | 609 |

| 时间检查 | 异常订单数 |
| --- | --- |
| delivered_missing_arrival | 8 |
| delivered_missing_approval | 14 |
| delivered_missing_carrier | 2 |
| arrival_before_purchase | 0 |
| approval_before_purchase | 0 |
| carrier_before_purchase | 166 |
| carrier_before_approval | 1359 |
| arrival_before_carrier | 23 |
| estimate_before_purchase_date | 0 |
| not_delivered_with_arrival | 6 |

完整异常订单及来源记录号见 `time_anomalies.csv`。按已冻结口径，下单到到货有效的已送达订单为 96,470 笔；可判断是否逾期的订单为 96,470 笔。审批或交运节点异常不自动排除下单到到货指标，若单独分析这些环节，应重新定义相应有效样本。源时间不含时区，不转换为中国时间。

## 5 金额核对

所有金额以整数分比较，显示单位为 BRL。以下是原始明细直接求和与先按订单聚合的独立口径核对；它不是尚未建设的 ODS/DWD 层间对账。

| 订单集合 | 金额项 | 原始记录合计 BRL | 订单聚合合计 BRL | 差额 分 |
| --- | --- | --- | --- | --- |
| all | item | 13,591,643.70 | 13,591,643.70 | 0 |
| all | freight | 2,251,909.54 | 2,251,909.54 | 0 |
| all | payment | 16,008,872.12 | 16,008,872.12 | 0 |
| delivered | item | 13,221,498.11 | 13,221,498.11 | 0 |
| delivered | freight | 2,198,275.64 | 2,198,275.64 | 0 |
| delivered | payment | 15,422,461.77 | 15,422,461.77 | 0 |

共有 98,665 笔订单同时具备商品明细与支付记录，其中 576 笔的支付金额不等于商品金额加运费；已送达集合内有 569 笔不等，所有集合内绝对差额为 1 分的有 273 笔。完整明细见 `order_amount_exceptions.csv`。不擅自改写金额或将差额判为退款；分别保留商品销售金额、运费和记录支付金额。缺少子记录的金额保持空值，不补零。

缺失支付的已送达订单：bfbd0f9bdef84302105ad712db648a6c。该订单商品与运费仍计入各自口径，支付为未知。上表支付合计仅是当前文件中已记录支付的合计，不能视为支付完整性通过。

## 6 后续 ETL 的核对基准

以下是原始数据上按设计口径计算的验收基准，不是已发布看板结果。

| 指标 | 结果 | 口径 |
| --- | --- | --- |
| 全部订单数 | 99,441 | 全部状态 |
| 已送达订单数 | 96,478 | delivered |
| 已送达商品金额 | 13,221,498.11 BRL | 不含运费 |
| 平均配送耗时 | 12.5582 天 | 有效样本 96,470 |
| 到货逾期率 | 6.7731% | 6,534 / 96,470；按自然日比较 |
| 已送达平均评分 | 4.155908 | 代表评价样本 95,832 |
| 已送达低分率 | 12.8068% | 代表评价评分1或2 |
| 逾期组低分率 | 62.4197% | 逾期且有代表评价 6,381 |
| 未逾期组低分率 | 9.2674% | 未逾期且有代表评价 89,443 |

两组评分只能用于相关性分析，不能据此声称配送延迟导致低分。

## 7 处理要求与验收边界

1. 原始文件只读保留，按 manifest 固定本批数据；ODS 使用文本列和来源记录号。
2. 代表评价严格使用约定排序；不以 review_id 建唯一约束，不对原始评价直接按订单连接金额。
3. 邮编补齐在 DIM 完成；地理数据先去重和汇总；品类缺失与翻译缺失分别处理。
4. 无到货时间、生命周期时间逆序等异常保留并登记，按具体指标排除无效样本。
5. 商品金额和支付金额分别与源数据对账，不强行消除二者业务差额；禁止直接连接商品和支付明细后求和。
6. 下一阶段需要真实执行 ODS/DWD 导入、层间对账、重跑一致性与数据库性能检查。本次没有完成这些实施验收项。

## 8 全部未通过项

| 规则 | 表 | 级别 | 影响数量 | 说明 |
| --- | --- | --- | --- | --- |
| zero_freight_value | items | WARN | 383 | 零值本身允许，不能视为缺失 |
| zero_payment_value | payments | WARN | 9 | 零值本身允许，不能视为缺失 |
| exact_duplicate_extra_rows | geolocation | WARN | 261831 | 多出的完全重复行；地理表保留原值，建映射时去重/汇总 |
| order_without_items | orders | WARN | 775 |  |
| order_without_payments | orders | WARN | 1 |  |
| order_without_reviews | orders | WARN | 768 |  |
| delivered_without_payments | orders | FAIL | 1 |  |
| missing_category | products | WARN | 610 |  |
| untranslated_category | products | WARN | 13 |  |
| zip_without_coordinates | customers | WARN | 278 |  |
| zip_without_coordinates | sellers | WARN | 7 |  |
| outside_brazil_approx_bbox | geolocation | WARN | 42 | 近似包围盒仅作地图异常筛查，不是国界或地址真伪判定 |
| multiple_reviews_per_order | reviews | WARN | 547 | 受影响订单数；按既定规则选代表评价 |
| review_id_not_unique | reviews | WARN | 814 | 多出的行数，review_id不能单独作为源主键 |
| delivered_missing_arrival | orders | WARN | 8 |  |
| delivered_missing_approval | orders | WARN | 14 |  |
| delivered_missing_carrier | orders | WARN | 2 |  |
| carrier_before_purchase | orders | WARN | 166 |  |
| carrier_before_approval | orders | WARN | 1359 |  |
| arrival_before_carrier | orders | WARN | 23 |  |
| not_delivered_with_arrival | orders | WARN | 6 |  |
| payment_item_difference | orders | WARN | 576 | 支付与商品加运费不等；属于源记录差异，不代表ETL重复。比较精度为1分 |
| months_without_purchase_records | orders | WARN | 1 | 2016-11；未观察到源记录，不证明当月业务为零 |

规则完整结果见 `checks.csv`；`issue_examples.csv` 每条规则至多记录 30 条标识符样例，不能把样例条数当作全部异常数。时间异常和金额差异文件为完整记录集。字段清单记录来源字段，不把推断的业务含义冒充源数据定义。

## 9 复现

在项目根目录执行 `python scripts/audit_olist.py`。依赖 Python 与 pandas；本次 pandas 3.0.1。脚本 SHA-256：`7fbca686d8667772ef6d3c41cf32974f0642e4653cd0ab763708e9cf63355a0c`。所有 CSV 输出采用 UTF-8 BOM 以便 Excel 打开；原始文件保持原字节。执行脚本不会修改数据库或原始 CSV。
