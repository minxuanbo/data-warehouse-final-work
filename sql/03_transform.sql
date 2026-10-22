-- The orchestrator sets olist.batch_id in this transaction. No input SQL interpolation.
CREATE OR REPLACE FUNCTION pg_temp.date_key(v TEXT) RETURNS INTEGER
LANGUAGE SQL IMMUTABLE AS $$ SELECT COALESCE(to_char(NULLIF(v,'')::TIMESTAMP,'YYYYMMDD')::INTEGER,0) $$;
CREATE OR REPLACE FUNCTION pg_temp.city(v TEXT) RETURNS TEXT
LANGUAGE SQL IMMUTABLE AS $$ SELECT COALESCE(NULLIF(regexp_replace(lower(btrim(v)),'\s+',' ','g'),''),'未知') $$;
CREATE OR REPLACE FUNCTION pg_temp.state(v TEXT) RETURNS TEXT
LANGUAGE SQL IMMUTABLE AS $$ SELECT COALESCE(NULLIF(upper(btrim(v)),''),'??') $$;

CREATE TEMP VIEW src_orders AS SELECT * FROM ods.orders WHERE batch_id=current_setting('olist.batch_id')::BIGINT;
CREATE TEMP VIEW src_customers AS SELECT * FROM ods.customers WHERE batch_id=current_setting('olist.batch_id')::BIGINT;
CREATE TEMP VIEW src_products AS SELECT * FROM ods.products WHERE batch_id=current_setting('olist.batch_id')::BIGINT;
CREATE TEMP VIEW src_sellers AS SELECT * FROM ods.sellers WHERE batch_id=current_setting('olist.batch_id')::BIGINT;
CREATE TEMP VIEW src_items AS SELECT * FROM ods.order_items WHERE batch_id=current_setting('olist.batch_id')::BIGINT;
CREATE TEMP VIEW src_payments AS SELECT * FROM ods.order_payments WHERE batch_id=current_setting('olist.batch_id')::BIGINT;
CREATE TEMP VIEW src_reviews AS SELECT * FROM ods.order_reviews WHERE batch_id=current_setting('olist.batch_id')::BIGINT;
CREATE TEMP VIEW src_geo AS SELECT * FROM ods.geolocation WHERE batch_id=current_setting('olist.batch_id')::BIGINT;
CREATE TEMP VIEW src_translation AS SELECT * FROM ods.category_translation WHERE batch_id=current_setting('olist.batch_id')::BIGINT;

DO $$ BEGIN RAISE NOTICE 'Loading dimensions'; END $$;
INSERT INTO dim.dim_geography(state_code,city_name)
SELECT pg_temp.state(customer_state),pg_temp.city(customer_city) FROM src_customers
UNION SELECT pg_temp.state(seller_state),pg_temp.city(seller_city) FROM src_sellers
ON CONFLICT(state_code,city_name) DO NOTHING;

WITH date_values AS (
 SELECT unnest(ARRAY[order_purchase_timestamp,order_approved_at,order_delivered_carrier_date,
 order_delivered_customer_date,order_estimated_delivery_date]) AS value FROM src_orders
 UNION ALL SELECT shipping_limit_date FROM src_items
 UNION ALL SELECT review_creation_date FROM src_reviews
 UNION ALL SELECT review_answer_timestamp FROM src_reviews
), bounds AS (SELECT MIN(NULLIF(value,'')::TIMESTAMP)::DATE lo,
MAX(NULLIF(value,'')::TIMESTAMP)::DATE hi FROM date_values)
INSERT INTO dim.dim_date(date_key,calendar_date,year_no,quarter_no,month_no,day_no,iso_weekday)
SELECT to_char(d,'YYYYMMDD')::INTEGER,d::DATE,extract(year FROM d),extract(quarter FROM d),
extract(month FROM d),extract(day FROM d),extract(isodow FROM d)
FROM bounds,LATERAL generate_series(lo::TIMESTAMP,hi::TIMESTAMP,interval '1 day') d
ON CONFLICT(date_key) DO NOTHING;

INSERT INTO dim.dim_customer(customer_id,customer_unique_id,zip_prefix)
SELECT btrim(customer_id),NULLIF(btrim(customer_unique_id),''),lpad(customer_zip_code_prefix,5,'0') FROM src_customers
ON CONFLICT(customer_id) DO UPDATE SET customer_unique_id=excluded.customer_unique_id,zip_prefix=excluded.zip_prefix;
INSERT INTO dim.dim_product(product_id,category_name,category_name_english,weight_g,length_cm,height_cm,width_cm)
SELECT p.product_id,COALESCE(NULLIF(p.product_category_name,''),'未知'),
 COALESCE(NULLIF(t.product_category_name_english,''),NULLIF(p.product_category_name,''),'未知'),
 NULLIF(p.product_weight_g,'')::NUMERIC,NULLIF(p.product_length_cm,'')::NUMERIC,
 NULLIF(p.product_height_cm,'')::NUMERIC,NULLIF(p.product_width_cm,'')::NUMERIC
FROM src_products p LEFT JOIN src_translation t USING(product_category_name)
ON CONFLICT(product_id) DO UPDATE SET category_name=excluded.category_name,
category_name_english=excluded.category_name_english,weight_g=excluded.weight_g,
length_cm=excluded.length_cm,height_cm=excluded.height_cm,width_cm=excluded.width_cm;
INSERT INTO dim.dim_seller(seller_id,zip_prefix,seller_geo_key)
SELECT s.seller_id,lpad(s.seller_zip_code_prefix,5,'0'),g.geo_key
FROM src_sellers s JOIN dim.dim_geography g
ON g.state_code=pg_temp.state(s.seller_state) AND g.city_name=pg_temp.city(s.seller_city)
ON CONFLICT(seller_id) DO UPDATE SET zip_prefix=excluded.zip_prefix,seller_geo_key=excluded.seller_geo_key;
INSERT INTO dim.dim_payment_type(payment_type_code,payment_type_name)
SELECT DISTINCT payment_type,payment_type FROM src_payments
ON CONFLICT(payment_type_code) DO NOTHING;

DO $$ BEGIN RAISE NOTICE 'Aggregating postcode coordinates'; END $$;
DELETE FROM dim.dim_zip_coordinates;
WITH valid AS (
 SELECT lpad(geolocation_zip_code_prefix,5,'0') zip,
 geolocation_lat::DOUBLE PRECISION lat,geolocation_lng::DOUBLE PRECISION lng
 FROM src_geo WHERE geolocation_lat::DOUBLE PRECISION BETWEEN -34 AND 6
 AND geolocation_lng::DOUBLE PRECISION BETWEEN -74 AND -34
), counts AS (SELECT zip,COUNT(*) n FROM valid GROUP BY zip), coords AS (SELECT DISTINCT * FROM valid)
INSERT INTO dim.dim_zip_coordinates
SELECT zip,percentile_cont(0.5) WITHIN GROUP (ORDER BY lat),
percentile_cont(0.5) WITHIN GROUP (ORDER BY lng),MAX(n),COUNT(*)
FROM coords JOIN counts USING(zip) GROUP BY zip;

ANALYZE dim.dim_geography;
ANALYZE dim.dim_customer;
ANALYZE dim.dim_product;
ANALYZE dim.dim_seller;
ANALYZE dim.dim_payment_type;
DO $$ BEGIN RAISE NOTICE 'Loading order facts'; END $$;
-- One full snapshot, atomic replacement: no order append and no CASCADE.
TRUNCATE dwd.fact_review,dwd.fact_payment,dwd.fact_order_item,dwd.fact_order;
INSERT INTO dwd.fact_order
SELECT o.order_id,c.customer_key,g.geo_key,
 pg_temp.date_key(o.order_purchase_timestamp),pg_temp.date_key(o.order_approved_at),
 pg_temp.date_key(o.order_delivered_carrier_date),pg_temp.date_key(o.order_delivered_customer_date),
 pg_temp.date_key(o.order_estimated_delivery_date),o.order_status,
 NULLIF(o.order_purchase_timestamp,'')::TIMESTAMP,NULLIF(o.order_approved_at,'')::TIMESTAMP,
 NULLIF(o.order_delivered_carrier_date,'')::TIMESTAMP,NULLIF(o.order_delivered_customer_date,'')::TIMESTAMP,
 NULLIF(o.order_estimated_delivery_date,'')::TIMESTAMP,o.batch_id,o.source_row_no
FROM src_orders o JOIN src_customers sc USING(customer_id)
JOIN dim.dim_customer c USING(customer_id)
JOIN dim.dim_geography g ON g.state_code=pg_temp.state(sc.customer_state) AND g.city_name=pg_temp.city(sc.customer_city);
ANALYZE dwd.fact_order;
DO $$ BEGIN RAISE NOTICE 'Loading item facts'; END $$;
INSERT INTO dwd.fact_order_item
SELECT i.order_id,i.order_item_id::INTEGER,p.product_key,s.seller_key,
 o.purchase_date_key,pg_temp.date_key(i.shipping_limit_date),o.customer_key,o.customer_geo_key,
 NULLIF(i.shipping_limit_date,'')::TIMESTAMP,i.price::NUMERIC,i.freight_value::NUMERIC,i.batch_id,i.source_row_no
FROM src_items i JOIN dwd.fact_order o USING(order_id)
JOIN dim.dim_product p USING(product_id) JOIN dim.dim_seller s USING(seller_id);
DO $$ BEGIN RAISE NOTICE 'Loading payment facts'; END $$;
INSERT INTO dwd.fact_payment
SELECT p.order_id,p.payment_sequential::INTEGER,t.payment_type_key,
 o.purchase_date_key,o.customer_key,o.customer_geo_key,p.payment_value::NUMERIC,
 NULLIF(p.payment_installments,'')::INTEGER,p.batch_id,p.source_row_no
FROM src_payments p JOIN dwd.fact_order o USING(order_id)
JOIN dim.dim_payment_type t ON t.payment_type_code=p.payment_type;
DO $$ BEGIN RAISE NOTICE 'Selecting review facts'; END $$;
WITH ranked AS (
 SELECT r.*,row_number() OVER(PARTITION BY order_id ORDER BY
 NULLIF(review_answer_timestamp,'')::TIMESTAMP DESC NULLS LAST,
 NULLIF(review_creation_date,'')::TIMESTAMP DESC NULLS LAST,
 NULLIF(review_id,'') COLLATE "C" DESC NULLS LAST,source_row_no DESC) rn FROM src_reviews r
)
INSERT INTO dwd.fact_review
SELECT r.order_id,r.review_id,o.purchase_date_key,pg_temp.date_key(r.review_creation_date),
 pg_temp.date_key(r.review_answer_timestamp),o.customer_key,o.customer_geo_key,
 CASE WHEN r.review_score::INTEGER BETWEEN 1 AND 5 THEN r.review_score::SMALLINT END,
 NULLIF(r.review_creation_date,'')::TIMESTAMP,NULLIF(r.review_answer_timestamp,'')::TIMESTAMP,r.batch_id,r.source_row_no
FROM ranked r JOIN dwd.fact_order o USING(order_id) WHERE rn=1;

DO $$ BEGIN RAISE NOTICE 'Refreshing order materialized view'; END $$;
REFRESH MATERIALIZED VIEW dws.order_wide;
INSERT INTO audit.rejected_record(batch_id,file_name,source_row_no,rule_name,raw_record)
SELECT o.batch_id,'olist_orders_dataset.csv',o.source_row_no,'payment_missing',
 jsonb_build_object('order_id',o.order_id,'order_status',o.order_status,'action','retain_order_payment_unknown')
FROM dwd.fact_order o LEFT JOIN dwd.fact_payment p USING(order_id)
WHERE o.order_status='delivered' AND p.order_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO audit.rejected_record(batch_id,file_name,source_row_no,rule_name,raw_record)
SELECT batch_id,'olist_orders_dataset.csv',source_row_no,'delivery_time_missing',
 jsonb_build_object('order_id',order_id,'action','exclude_from_delivery_metrics')
FROM dwd.fact_order WHERE order_status='delivered' AND delivered_ts IS NULL
ON CONFLICT DO NOTHING;
ANALYZE dwd.fact_order;
ANALYZE dwd.fact_order_item;
ANALYZE dwd.fact_payment;
ANALYZE dwd.fact_review;
ANALYZE dws.order_wide;
