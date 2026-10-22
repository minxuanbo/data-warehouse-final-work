"""Read-only audit of the nine source CSVs. All money comparisons use integer cents.

Run: python scripts/audit_olist.py
Exit 0: source accepted with possible warnings. Exit 2: blocking checks failed.
Original CSV files are never rewritten. CSV output row numbers count data records,
starting at 1, rather than physical lines (review text may contain newlines).
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import argparse
import csv
import hashlib
import json
import re
import sys
import zipfile
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
 'orders': ('olist_orders_dataset.csv', 'order_id customer_id order_status order_purchase_timestamp order_approved_at order_delivered_carrier_date order_delivered_customer_date order_estimated_delivery_date', ['order_id']),
 'items': ('olist_order_items_dataset.csv', 'order_id order_item_id product_id seller_id shipping_limit_date price freight_value', ['order_id','order_item_id']),
 'payments': ('olist_order_payments_dataset.csv', 'order_id payment_sequential payment_type payment_installments payment_value', ['order_id','payment_sequential']),
 'reviews': ('olist_order_reviews_dataset.csv', 'review_id order_id review_score review_comment_title review_comment_message review_creation_date review_answer_timestamp', []),
 'customers': ('olist_customers_dataset.csv', 'customer_id customer_unique_id customer_zip_code_prefix customer_city customer_state', ['customer_id']),
 'products': ('olist_products_dataset.csv', 'product_id product_category_name product_name_lenght product_description_lenght product_photos_qty product_weight_g product_length_cm product_height_cm product_width_cm', ['product_id']),
 'sellers': ('olist_sellers_dataset.csv', 'seller_id seller_zip_code_prefix seller_city seller_state', ['seller_id']),
 'geolocation': ('olist_geolocation_dataset.csv', 'geolocation_zip_code_prefix geolocation_lat geolocation_lng geolocation_city geolocation_state', []),
 'translation': ('product_category_name_translation.csv', 'product_category_name product_category_name_english', ['product_category_name']),
}
DATE_COLUMNS = {
 'orders': ['order_purchase_timestamp','order_approved_at','order_delivered_carrier_date','order_delivered_customer_date','order_estimated_delivery_date'],
 'items': ['shipping_limit_date'],
 'reviews': ['review_creation_date','review_answer_timestamp'],
}
STATES = set('AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split())

def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(1024*1024):
            h.update(chunk)
    return h.hexdigest()

def cents(value):
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', value):
        raise ValueError(f'Not a nonnegative amount with at most 2 decimals: {value!r}')
    return int(Decimal(value)*100)

def money(value):
    return f'{int(value)/100:,.2f}'

def choose_reviews(df):
    """Choose before filtering score, retaining a stable source-row tie breaker."""
    result = df.copy()
    result['_answer'] = pd.to_datetime(result.review_answer_timestamp, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    result['_creation'] = pd.to_datetime(result.review_creation_date, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    result['_review_sort'] = result.review_id.replace('', pd.NA)
    return result.sort_values(['_answer','_creation','_review_sort','_source_row'],
        ascending=False, na_position='last', kind='stable').drop_duplicates('order_id')

def markdown_table(headers, rows):
    def cell(x):
        return str(x).replace('|','/').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |'] +
                     ['| '+' | '.join(cell(x) for x in row)+' |' for row in rows])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    raw, out = root/'data/raw', root/'reports/data_acceptance'
    out.mkdir(parents=True, exist_ok=True)
    checks, examples, fields, manifests, key_stats, dates = [], [], [], [], [], []
    frames = {}
    source = json.loads((root/'data/source.json').read_text(encoding='utf-8'))

    def check(rule, table, count, severity='warning', note='', df=None, mask=None, keys=None):
        count = int(count)
        checks.append(dict(rule=rule, table=table, severity=severity,
            status='PASS' if count == 0 else ('FAIL' if severity=='error' else 'WARN'),
            affected_count=count, note=note))
        if count and df is not None and mask is not None:
            # Examples contain identifiers only, never free-text reviews.
            selected = df.loc[mask]
            for _, row in selected.head(30).iterrows():
                examples.append(dict(rule=rule, table=table,
                    source_record_no=int(row['_source_row']) if '_source_row' in row else '',
                    key=json.dumps({k:str(row[k]) for k in (keys or [])}, ensure_ascii=False)))

    names = {spec[0] for spec in SCHEMAS.values()}
    check('required_files', 'all', len(names-{p.name for p in raw.glob('*.csv')}), 'error')
    if checks[-1]['affected_count']:
        raise RuntimeError('Missing source CSV files; download first')
    archive = root/'data/downloads/olist.zip'
    archive_hash = sha256(archive)
    check('archive_sha256', 'all', archive_hash != source['archive_sha256'], 'error')
    with zipfile.ZipFile(archive) as z:
        check('archive_crc', 'all', z.testzip() is not None, 'error')
        check('archive_members', 'all', set(z.namelist()) != names, 'error')
        for table, (filename, contract, pk) in SCHEMAS.items():
            path = raw/filename
            digest = sha256(path)
            check('raw_matches_archive', table, digest != hashlib.sha256(z.read(filename)).hexdigest(), 'error')
            bad_width = 0
            record_count = 0
            with path.open(encoding='utf-8-sig', newline='') as stream:
                reader = csv.reader(stream, strict=True)
                header = next(reader)
                for record in reader:
                    record_count += 1
                    bad_width += len(record) != len(header)
            check('field_contract', table, header != contract.split(), 'error', '字段名及顺序；去除UTF-8 BOM后比较')
            check('csv_record_width', table, bad_width, 'error')
            if header != contract.split() or bad_width:
                raise RuntimeError(f'{filename}: invalid CSV structure')
            df = pd.read_csv(path, dtype=str, encoding='utf-8-sig', keep_default_na=False, na_filter=False)
            check('parser_row_count', table, len(df) != record_count, 'error')
            df['_source_row'] = range(1, len(df)+1)
            frames[table] = df
            duplicate_extra = int(df.duplicated(subset=header).sum())
            manifest = dict(table=table, file_name=filename, rows=len(df), columns=len(header),
                bytes=path.stat().st_size, sha256=digest,
                utf8_bom=path.read_bytes()[:3] == b'\xef\xbb\xbf',
                source_url=source['source_url'], download_url=source['download_url'],
                retrieved_at=source['retrieved_at'], license=source['license'],
                exact_duplicate_extra_rows=duplicate_extra)
            manifests.append(manifest)
            check('exact_duplicate_extra_rows', table, duplicate_extra, 'warning',
                  '多出的完全重复行；地理表保留原值，建映射时去重/汇总')
            if pk:
                dup_mask = df.duplicated(pk, keep=False)
                unique_rows = df.drop_duplicates(header)
                conflicts = unique_rows.duplicated(pk, keep=False)
                missing_mask = df[pk].apply(lambda s:s.str.strip().eq('')).any(axis=1)
                key_stats.append(dict(table=table, key='+'.join(pk), distinct_keys=len(df.drop_duplicates(pk)),
                    duplicate_extra_rows=int(df.duplicated(pk).sum()), conflicting_rows=int(conflicts.sum())))
                check('primary_key_empty', table, missing_mask.sum(), 'error', df=df, mask=missing_mask, keys=pk)
                check('primary_key_conflict', table, conflicts.sum(), 'error', '同键不同值；不能任意取一条')
                check('primary_key_duplicate_extra', table, df.duplicated(pk).sum(), 'warning', df=df, mask=dup_mask, keys=pk)
            for col in header:
                s = df[col]
                empty = s.str.strip().eq('')
                nonempty = s[~empty]
                row = dict(table=table, column=col, total_rows=len(df), empty_count=int(empty.sum()),
                    empty_pct=round(float(empty.mean()*100),6), distinct_nonempty=int(nonempty.nunique()),
                    max_text_length=int(s.str.len().max()), invalid_type_count=0,
                    observed_min='', observed_max='')
                if col.endswith('_id') and col != 'order_item_id':
                    invalid = ~s.str.fullmatch('[0-9a-f]{32}')
                    row['invalid_type_count'] = int(invalid.sum())
                    check('id_format_'+col, table, invalid.sum(), 'error', df=df, mask=invalid, keys=[col])
                elif col.endswith('_zip_code_prefix'):
                    invalid = ~s.str.fullmatch('[0-9]{1,5}')
                    row['invalid_type_count'] = int(invalid.sum())
                    check('zip_format', table, invalid.sum(), 'warning', df=df, mask=invalid, keys=[col])
                    check('zip_needs_left_padding', table, (s.str.len()<5).sum(), 'warning', '源值保留；DIM按五位字符串补前导零')
                elif col.endswith('_state'):
                    check('state_code', table, (~s.isin(STATES)).sum(), 'warning')
                if col in DATE_COLUMNS.get(table, []):
                    parsed = pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce')
                    invalid = ~empty & parsed.isna()
                    row['invalid_type_count'] = int(invalid.sum())
                    row['observed_min'] = str(parsed.min())
                    row['observed_max'] = str(parsed.max())
                    dates.append(dict(table=table,column=col,missing=int(empty.sum()),invalid=int(invalid.sum()),
                        min=str(parsed.min()),max=str(parsed.max())))
                    check('date_parse_'+col, table, invalid.sum(), 'error', df=df, mask=invalid, keys=['order_id'])
                if col in ['price','freight_value','payment_value']:
                    invalid = ~s.str.fullmatch(r'\d+(?:\.\d{1,2})?')
                    row['invalid_type_count'] = int(invalid.sum())
                    check('amount_parse_'+col, table, invalid.sum(), 'error', df=df, mask=invalid, keys=['order_id'])
                    if not invalid.any():
                        df[col+'_cents'] = s.map(cents).astype('int64')
                        row['observed_min'], row['observed_max'] = money(df[col+'_cents'].min()), money(df[col+'_cents'].max())
                        check('zero_'+col, table, (df[col+'_cents']==0).sum(), 'warning', '零值本身允许，不能视为缺失')
                if col in ['order_item_id','payment_sequential','payment_installments','review_score'] or col.startswith('product_') and col not in ['product_id','product_category_name','product_category_name_english']:
                    num = pd.to_numeric(s, errors='coerce')
                    invalid = ~empty & (num.isna() | (num<0) | (num%1!=0))
                    if col in ['order_item_id','payment_sequential']:
                        invalid |= empty | (num<1)
                    if col=='review_score':
                        invalid |= empty | ~num.between(1,5)
                    if col=='payment_installments':
                        invalid |= empty
                    row['invalid_type_count'] = int(invalid.sum())
                    row['observed_min'],row['observed_max'] = str(num.min()),str(num.max())
                    check('numeric_'+col, table, invalid.sum(), 'error' if table in ['items','payments','reviews'] else 'warning')
                fields.append(row)
            print(f'Profiled {filename}: {len(df):,} rows', flush=True)

    if any(c['status']=='FAIL' for c in checks):
        pd.DataFrame(checks).to_csv(out/'checks.csv',index=False,encoding='utf-8-sig')
        raise RuntimeError('Blocking source checks failed; inspect checks.csv before cross-table audit')
    o,i,p,r,c,pr,s,g,t = [frames[n] for n in ['orders','items','payments','reviews','customers','products','sellers','geolocation','translation']]
    relations = []
    for child,col,parent,parent_col in [
        ('orders','customer_id','customers','customer_id'),('items','order_id','orders','order_id'),
        ('items','product_id','products','product_id'),('items','seller_id','sellers','seller_id'),
        ('payments','order_id','orders','order_id'),('reviews','order_id','orders','order_id')]:
        df = frames[child]
        bad = ~df[col].isin(frames[parent][parent_col])
        relations.append(dict(child=child,field=col,parent=parent,rows=len(df),orphan_rows=int(bad.sum())))
        check('foreign_key_'+col,child,bad.sum(),'error',df=df,mask=bad,keys=[col])
    for name,df in [('items',i),('payments',p),('reviews',r)]:
        missing = ~o.order_id.isin(df.order_id)
        check('order_without_'+name,'orders',missing.sum(),'warning',df=o,mask=missing,keys=['order_id','order_status'])
    delivered = o.order_status.eq('delivered')
    states = o.order_status.value_counts().sort_index()
    check('unknown_order_status','orders',(~o.order_status.isin('created approved invoiced processing shipped delivered unavailable canceled'.split())).sum(),'error')
    for name,df in [('items',i),('payments',p)]:
        mask = delivered & ~o.order_id.isin(df.order_id)
        check('delivered_without_'+name,'orders',mask.sum(),'error',df=o,mask=mask,keys=['order_id'])
    missing_category = pr.product_category_name.eq('')
    unmapped = ~missing_category & ~pr.product_category_name.isin(t.product_category_name)
    check('missing_category','products',missing_category.sum(),'warning',df=pr,mask=missing_category,keys=['product_id'])
    check('untranslated_category','products',unmapped.sum(),'warning',df=pr,mask=unmapped,keys=['product_id','product_category_name'])
    for table,df,col in [('customers',c,'customer_zip_code_prefix'),('sellers',s,'seller_zip_code_prefix')]:
        mask = ~df[col].str.zfill(5).isin(g.geolocation_zip_code_prefix.str.zfill(5))
        check('zip_without_coordinates',table,mask.sum(),'warning',df=df,mask=mask,keys=[col])
    lat = pd.to_numeric(g.geolocation_lat,errors='coerce')
    lng = pd.to_numeric(g.geolocation_lng,errors='coerce')
    global_invalid = ~lat.between(-90,90) | ~lng.between(-180,180)
    check('invalid_coordinate_range','geolocation',global_invalid.sum(),'warning')
    outside_bbox = ~lat.between(-34,6) | ~lng.between(-74,-34)
    check('outside_brazil_approx_bbox','geolocation',outside_bbox.sum(),'warning',
        '近似包围盒仅作地图异常筛查，不是国界或地址真伪判定',df=g,mask=outside_bbox,keys=['geolocation_zip_code_prefix','geolocation_lat','geolocation_lng'])
    for name,df,col in [('reviews',r,'review_id'),('reviews',r,'order_id'),('geolocation',g,'geolocation_zip_code_prefix')]:
        key_stats.append(dict(table=name,key=col,distinct_keys=df[col].nunique(),duplicate_extra_rows=int(df.duplicated(col).sum()),conflicting_rows='not_a_primary_key'))
    review_groups = r.groupby('order_id').size()
    check('multiple_reviews_per_order','reviews',(review_groups>1).sum(),'warning','受影响订单数；按既定规则选代表评价')
    check('review_id_not_unique','reviews',r.duplicated('review_id').sum(),'warning','多出的行数，review_id不能单独作为源主键')
    selected = choose_reviews(r)
    selected[['order_id','review_id','_source_row']].sort_values('order_id').to_csv(out/'selected_review_keys.csv',index=False,encoding='utf-8-sig')

    d = {col:pd.to_datetime(o[col],format='%Y-%m-%d %H:%M:%S',errors='coerce') for col in DATE_COLUMNS['orders']}
    purchase,approved,carrier,arrival,estimate = [d[col] for col in DATE_COLUMNS['orders']]
    check('missing_purchase','orders',purchase.isna().sum(),'error')
    time_flags = {
        'delivered_missing_arrival': delivered & arrival.isna(),
        'delivered_missing_approval': delivered & approved.isna(),
        'delivered_missing_carrier': delivered & carrier.isna(),
        'arrival_before_purchase': arrival.notna() & purchase.notna() & (arrival<purchase),
        'approval_before_purchase': approved.notna() & purchase.notna() & (approved<purchase),
        'carrier_before_purchase': carrier.notna() & purchase.notna() & (carrier<purchase),
        'carrier_before_approval': carrier.notna() & approved.notna() & (carrier<approved),
        'arrival_before_carrier': arrival.notna() & carrier.notna() & (arrival<carrier),
        'estimate_before_purchase_date': estimate.notna() & purchase.notna() & (estimate.dt.normalize()<purchase.dt.normalize()),
        'not_delivered_with_arrival': ~delivered & arrival.notna(),
    }
    time_records = []
    for rule,mask in time_flags.items():
        check(rule,'orders',mask.sum(),'warning',df=o,mask=mask,keys=['order_id','order_status'])
        part = o.loc[mask,['order_id','order_status','_source_row']+DATE_COLUMNS['orders']].copy()
        part.insert(0,'rule',rule)
        time_records.append(part)
    pd.concat(time_records,ignore_index=True).to_csv(out/'time_anomalies.csv',index=False,encoding='utf-8-sig')

    # Preserve missing child records as NA, never silently zero-fill before accounting.
    ia = i.groupby('order_id')[['price_cents','freight_value_cents']].sum()
    pa = p.groupby('order_id').payment_value_cents.sum()
    wide = o[['order_id','order_status']].set_index('order_id').join(ia.astype('Int64')).join(pa.astype('Int64'))
    wide['item_plus_freight_cents'] = wide.price_cents+wide.freight_value_cents
    wide['difference_cents'] = wide.payment_value_cents-wide.item_plus_freight_cents
    complete = wide.item_plus_freight_cents.notna() & wide.payment_value_cents.notna()
    difference = complete & wide.difference_cents.ne(0).fillna(False)
    check('payment_item_difference','orders',difference.sum(),'warning',
          '支付与商品加运费不等；属于源记录差异，不代表ETL重复。比较精度为1分')
    wide.loc[difference | ~complete].reset_index().to_csv(out/'order_amount_exceptions.csv',index=False,encoding='utf-8-sig')
    # Independent total: source rows vs separately aggregated one-row-per-order view.
    balances=[]
    delivered_ids = set(o.loc[delivered,'order_id'])
    for scope,ids in [('all',set(o.order_id)),('delivered',delivered_ids)]:
        subset = wide.loc[wide.index.isin(ids)]
        for label,df,col in [('item',i,'price_cents'),('freight',i,'freight_value_cents'),('payment',p,'payment_value_cents')]:
            src = int(df.loc[df.order_id.isin(ids),col].sum())
            grouped = int(subset[col].sum())
            balances.append(dict(scope=scope,measure=label,source_cents=src,order_aggregate_cents=grouped,difference_cents=grouped-src))
            check('aggregation_balance_'+scope+'_'+label,'orders',grouped!=src,'error')
    check('order_wide_grain','orders',len(wide)!=len(o),'error')
    review_scores = selected.set_index('order_id').review_score.astype(int)
    valid_delivery = delivered & purchase.notna() & arrival.notna() & (arrival>=purchase)
    valid_late = valid_delivery & estimate.notna() & (estimate.dt.normalize()>=purchase.dt.normalize())
    late = valid_late & (arrival.dt.normalize()>estimate.dt.normalize())
    valid_review = delivered & o.order_id.isin(review_scores.index)
    scores = o.order_id.map(review_scores)
    paired = valid_late & scores.notna()
    late_days = (arrival.dt.normalize()-estimate.dt.normalize()).dt.days
    metrics = {
        'all_orders':len(o),'delivered_orders':int(delivered.sum()),
        'all_distinct_customer_records':c.customer_id.nunique(),
        'all_distinct_buyers':c.customer_unique_id.nunique(),
        'delivered_distinct_buyers':c.loc[c.customer_id.isin(o.loc[delivered,'customer_id']),'customer_unique_id'].nunique(),
        'purchase_min':str(purchase.min()),'purchase_max':str(purchase.max()),
        'delivery_valid_orders':int(valid_delivery.sum()), 'late_eligible_orders':int(valid_late.sum()),
        'late_orders':int(late.sum()), 'late_rate':float(late.sum()/valid_late.sum()),
        'average_delivery_days':float((arrival-purchase)[valid_delivery].dt.total_seconds().mean()/86400),
        'average_late_days':float(late_days[late].mean()),
        'delivered_reviewed_orders':int(valid_review.sum()),
        'delivered_average_score':float(scores[valid_review].mean()),
        'delivered_low_score_orders':int((valid_review & scores.isin([1,2])).sum()),
        'delivered_low_score_rate':float(scores[valid_review].isin([1,2]).mean()),
        'multiple_review_orders':int((review_groups>1).sum()),
        'selected_reviews':len(selected),'review_rows_not_selected':len(r)-len(selected),
        'payment_difference_orders':int(difference.sum()),
        'delivered_payment_difference_orders':int((difference & wide.order_status.eq('delivered')).sum()),
        'difference_within_one_cent_orders':int((difference & wide.difference_cents.abs().le(1)).sum()),
        'complete_amount_comparison_orders':int(complete.sum()),
        'distinct_geo_zip_prefixes':g.geolocation_zip_code_prefix.nunique(),
        'untranslated_categories':sorted(pr.loc[unmapped,'product_category_name'].unique().tolist()),
    }
    for flag,label in [(True,'late'),(False,'on_time')]:
        mask = paired & (late if flag else ~late)
        metrics[label+'_review_sample']=int(mask.sum())
        metrics[label+'_low_score_rate']=float(scores[mask].isin([1,2]).mean())
    for bal in balances:
        metrics[bal['scope']+'_'+bal['measure']+'_cents']=bal['source_cents']
    # The following monthly profile is coverage evidence, not a claim of complete months.
    monthly = o[['order_id','order_status']].copy()
    monthly['purchase_month']=purchase.dt.strftime('%Y-%m')
    monthly['purchase_date']=purchase.dt.date.astype(str)
    month_rows=[]
    empty_months=[]
    for period in pd.period_range(purchase.min(),purchase.max(),freq='M'):
        month=str(period)
        group=monthly.loc[monthly.purchase_month.eq(month)]
        ids=set(group.order_id)
        sold=wide.loc[wide.index.isin(ids) & wide.order_status.eq('delivered')]
        if group.empty:
            empty_months.append(month)
        month_rows.append(dict(month=month,all_orders=len(group),delivered_orders=len(sold),
            first_observed_date=group.purchase_date.min() if not group.empty else '',
            last_observed_date=group.purchase_date.max() if not group.empty else '',
            observed_purchase_days=group.purchase_date.nunique(),
            has_source_records=not group.empty,
            item_amount_cents=int(sold.price_cents.sum()) if not group.empty else None))
    check('months_without_purchase_records','orders',len(empty_months),'warning',
          ', '.join(empty_months)+'；未观察到源记录，不证明当月业务为零')

    pd.DataFrame(manifests).to_csv(root/'data/manifest.csv',index=False,encoding='utf-8-sig')
    outputs={'field_profile':fields,'key_profile':key_stats,'foreign_keys':relations,'date_profile':dates,
             'checks':checks,'issue_examples':examples,'amount_reconciliation':balances,'monthly_coverage':month_rows}
    for filename,rows in outputs.items():
        pd.DataFrame(rows).to_csv(out/(filename+'.csv'),index=False,encoding='utf-8-sig')
    states.rename_axis('order_status').rename('orders').to_csv(out/'order_status.csv',encoding='utf-8-sig')
    now=datetime.now(timezone(timedelta(hours=8))).isoformat()
    fail=[x for x in checks if x['status']=='FAIL']
    warnings=[x for x in checks if x['status']=='WARN']
    result={'audited_at':now,'source_archive_sha256':archive_hash,
        'script_sha256':sha256(Path(__file__)),'pandas_version':pd.__version__,
        'status':'BLOCKED' if fail else 'ACCEPTED_WITH_CONDITIONS' if warnings else 'ACCEPTED',
        'error_checks':len(fail),'warning_checks':len(warnings),'check_count':len(checks),
        'metrics':metrics,'time_anomalies':{k:int(v.sum()) for k,v in time_flags.items()}}
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    only_missing_payment = bool(fail) and all(x['rule']=='delivered_without_payments' for x in fail)
    verdict=('文件与结构验收通过；支付完整性未通过，限制完整支付金额指标发布' if only_missing_payment
             else '暂不通过：存在阻断项' if fail
             else '原始数据验收有条件通过，可以进入 ODS 和 ETL 开发')
    report=f'''# Olist 数据验收报告

验收时间：{now}（北京时间）。结论：**{verdict}**。

本次实际下载并逐表读取了 9 个 CSV，未改写原始数据。共执行 {len(checks)} 项检查，{len(fail)} 项阻断失败，{len(warnings)} 项需按规则处理或披露的告警。此结论是源数据可用性验收，不表示数仓已建成或全部数据无异常；不存在已执行的数据库对账。

数据可以按原样进入 ODS，并继续开发交易、履约和评价模型。支付完整性失败不会通过补造支付记录解决：保留缺失标记，暂不把已记录支付金额表述为全量应有支付金额。脚本对未关闭的阻断项返回非零退出码，这是预期的质量检查结果。

## 1 来源与完整性

发布者：Olist。数据集：Brazilian E-Commerce Public Dataset by Olist。

发布页：{source['source_url']} 。下载接口：{source['download_url']} 。许可：{source['license']}；发布页许可信息已核对。下载时间：{source['retrieved_at']}。

API 使用下载时的最新包，未声称取得数值版本号；以 ZIP SHA-256 固定此次内容版本：`{archive_hash}`。压缩包 CRC 检查通过，解压文件哈希与压缩包内成员一致。UTF-8 解码成功，CSV 字段数符合契约。翻译文件带 BOM，读取必须使用 `utf-8-sig`。

{markdown_table(['文件','数据行数','字段数','字节数','完全重复多余行'],[[m['file_name'],f"{m['rows']:,}",m['columns'],f"{m['bytes']:,}",m['exact_duplicate_extra_rows']] for m in manifests])}

行数按 CSV 逻辑记录计算，排除表头；评价文本包含换行，不能用文本文件物理行数代替。每文件 SHA-256、来源和下载时间见 `data/manifest.csv`。

## 2 主键与关联

{markdown_table(['表','候选键或诊断键','不同键数','重复多余行','冲突行'],[[k['table'],k['key'],k['distinct_keys'],k['duplicate_extra_rows'],k['conflicting_rows']] for k in key_stats])}

`review_id`、评价表的 `order_id`、地理位置表的邮编前缀均不视为主键。评价保留全部原始行，后续每订单按回复时间、创建时间、review_id 和来源记录号降序选择一条代表评价。当前 {metrics['multiple_review_orders']:,} 个订单有多条评价，选择后 {metrics['selected_reviews']:,} 行，{metrics['review_rows_not_selected']:,} 行不进入代表评价事实，仍保留在 ODS。选择结果见 `selected_review_keys.csv`。

{markdown_table(['子表','关联字段','父表','子表行数','孤立行'],[[x['child'],x['field'],x['parent'],x['rows'],x['orphan_rows']] for x in relations])}

客户记录有 {len(c):,} 条，独立购买者为 {metrics['all_distinct_buyers']:,} 人；已送达订单对应 {metrics['delivered_distinct_buyers']:,} 名独立购买者。这三个数量不可混用。

## 3 缺失值与异常

下表只列出有缺失的字段，完整字段清单及类型检查见 `field_profile.csv`。

{markdown_table(['表','字段','空值数','空值比例'],[[x['table'],x['column'],x['empty_count'],str(round(x['empty_pct'],4))+'%'] for x in fields if x['empty_count']])}

评价标题和正文缺失不影响评分分析，不补造文本。商品属性或品类缺失保留未知值。缺少翻译的原品类为 {', '.join(metrics['untranslated_categories']) or '无'}，保留葡语原名，不丢弃商品。邮编在 DIM 中补齐至五位，不能覆盖 ODS 原值。地理坐标需去重、筛查，再按邮编聚合；原始地理表不能直接连接订单。

## 4 时间与状态

下单时间实际范围：{metrics['purchase_min']} 至 {metrics['purchase_max']}。月度覆盖及观察到的首末日期见 `monthly_coverage.csv`；边界月份和稀疏月份需单独标记，不能自动当作完整月份计算环比。

时间范围内没有观察到订单记录的月份：{', '.join(empty_months) or '无'}。2016 年及 2018 年 9—10 月记录稀疏，建议主趋势图先使用 2017 年 2 月至 2018 年 8 月，并另行展示全时段覆盖情况；这一选取是分析范围建议，不证明这段期间包含平台全部真实订单。

{markdown_table(['订单状态','订单数'],[[status,int(count)] for status,count in states.items()])}

{markdown_table(['时间检查','异常订单数'],[[k,int(v.sum())] for k,v in time_flags.items()])}

完整异常订单及来源记录号见 `time_anomalies.csv`。按已冻结口径，下单到到货有效的已送达订单为 {metrics['delivery_valid_orders']:,} 笔；可判断是否逾期的订单为 {metrics['late_eligible_orders']:,} 笔。审批或交运节点异常不自动排除下单到到货指标，若单独分析这些环节，应重新定义相应有效样本。源时间不含时区，不转换为中国时间。

## 5 金额核对

所有金额以整数分比较，显示单位为 BRL。以下是原始明细直接求和与先按订单聚合的独立口径核对；它不是尚未建设的 ODS/DWD 层间对账。

{markdown_table(['订单集合','金额项','原始记录合计 BRL','订单聚合合计 BRL','差额 分'],[[x['scope'],x['measure'],money(x['source_cents']),money(x['order_aggregate_cents']),x['difference_cents']] for x in balances])}

共有 {metrics['complete_amount_comparison_orders']:,} 笔订单同时具备商品明细与支付记录，其中 {metrics['payment_difference_orders']:,} 笔的支付金额不等于商品金额加运费；已送达集合内有 {metrics['delivered_payment_difference_orders']:,} 笔不等，所有集合内绝对差额为 1 分的有 {metrics['difference_within_one_cent_orders']:,} 笔。完整明细见 `order_amount_exceptions.csv`。不擅自改写金额或将差额判为退款；分别保留商品销售金额、运费和记录支付金额。缺少子记录的金额保持空值，不补零。

缺失支付的已送达订单：{', '.join(wide.index[wide.order_status.eq('delivered') & wide.payment_value_cents.isna()].tolist()) or '无'}。该订单商品与运费仍计入各自口径，支付为未知。上表支付合计仅是当前文件中已记录支付的合计，不能视为支付完整性通过。

## 6 后续 ETL 的核对基准

以下是原始数据上按设计口径计算的验收基准，不是已发布看板结果。

{markdown_table(['指标','结果','口径'],[
 ['全部订单数',f"{len(o):,}",'全部状态'],
 ['已送达订单数',f"{metrics['delivered_orders']:,}",'delivered'],
 ['已送达商品金额',money(metrics['delivered_item_cents'])+' BRL','不含运费'],
 ['平均配送耗时',f"{metrics['average_delivery_days']:.4f} 天",f"有效样本 {metrics['delivery_valid_orders']:,}"],
 ['到货逾期率',f"{metrics['late_rate']:.4%}",f"{metrics['late_orders']:,} / {metrics['late_eligible_orders']:,}；按自然日比较"],
 ['已送达平均评分',f"{metrics['delivered_average_score']:.6f}",f"代表评价样本 {metrics['delivered_reviewed_orders']:,}"],
 ['已送达低分率',f"{metrics['delivered_low_score_rate']:.4%}",'代表评价评分1或2'],
 ['逾期组低分率',f"{metrics['late_low_score_rate']:.4%}",f"逾期且有代表评价 {metrics['late_review_sample']:,}"],
 ['未逾期组低分率',f"{metrics['on_time_low_score_rate']:.4%}",f"未逾期且有代表评价 {metrics['on_time_review_sample']:,}"],
 ])}

两组评分只能用于相关性分析，不能据此声称配送延迟导致低分。

## 7 处理要求与验收边界

1. 原始文件只读保留，按 manifest 固定本批数据；ODS 使用文本列和来源记录号。
2. 代表评价严格使用约定排序；不以 review_id 建唯一约束，不对原始评价直接按订单连接金额。
3. 邮编补齐在 DIM 完成；地理数据先去重和汇总；品类缺失与翻译缺失分别处理。
4. 无到货时间、生命周期时间逆序等异常保留并登记，按具体指标排除无效样本。
5. 商品金额和支付金额分别与源数据对账，不强行消除二者业务差额；禁止直接连接商品和支付明细后求和。
6. 下一阶段需要真实执行 ODS/DWD 导入、层间对账、重跑一致性与数据库性能检查。本次没有完成这些实施验收项。

## 8 全部未通过项

{markdown_table(['规则','表','级别','影响数量','说明'],[[x['rule'],x['table'],x['status'],x['affected_count'],x['note']] for x in checks if x['status']!='PASS'])}

规则完整结果见 `checks.csv`；`issue_examples.csv` 每条规则至多记录 30 条标识符样例，不能把样例条数当作全部异常数。时间异常和金额差异文件为完整记录集。字段清单记录来源字段，不把推断的业务含义冒充源数据定义。

## 9 复现

在项目根目录执行 `python scripts/audit_olist.py`。依赖 Python 与 pandas；本次 pandas {pd.__version__}。脚本 SHA-256：`{result['script_sha256']}`。所有 CSV 输出采用 UTF-8 BOM 以便 Excel 打开；原始文件保持原字节。执行脚本不会修改数据库或原始 CSV。
'''
    (root/'reports/data_profile.md').write_text(report,encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return 2 if fail else 0

if __name__=='__main__':
    sys.exit(main())
