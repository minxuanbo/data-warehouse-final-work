-- Run after ETL. All monetary values are BRL; ratios are numeric 0..1.
SELECT * FROM ads.kpi_overview;

-- Suggested comparison window excludes sparse historical boundary months.
SELECT * FROM ads.trade_month
WHERE make_date(year_no,month_no,1) BETWEEN DATE '2017-02-01' AND DATE '2018-08-01'
ORDER BY year_no,month_no;

SELECT * FROM ads.fulfillment_state ORDER BY late_rate DESC NULLS LAST;
SELECT * FROM ads.category_ranking ORDER BY item_amount DESC LIMIT 10;
SELECT * FROM ads.seller_ranking ORDER BY item_amount DESC LIMIT 10;
SELECT * FROM ads.delivery_review_comparison ORDER BY is_late;

-- Correct aggregation: sum numerators / sum denominators, never average daily rates.
SELECT d.year_no,d.month_no,
       SUM(f.late_order_count)::NUMERIC / NULLIF(SUM(f.valid_late_count),0) AS late_rate
FROM dws.fulfillment_day_geo f JOIN dim.dim_date d ON f.purchase_date_key=d.date_key
GROUP BY d.year_no,d.month_no ORDER BY d.year_no,d.month_no;

-- Trace the missing payment without creating or inventing a payment record.
SELECT * FROM ads.payment_quality WHERE payment_missing;
SELECT run_id,batch_id,status,elapsed_seconds,error_message
FROM audit.pipeline_run ORDER BY run_id DESC;
