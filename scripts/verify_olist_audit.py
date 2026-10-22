"""Independent verification using csv, Decimal, datetime and dicts, without pandas.

Checks final audit artifacts against source CSVs; never rewrites sources.
"""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import csv
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT/'data/raw'
OUT = ROOT/'reports/data_acceptance'

def rows(name):
    with (RAW/name).open(encoding='utf-8-sig',newline='') as f:
        yield from csv.DictReader(f)

def dt(value):
    return datetime.strptime(value,'%Y-%m-%d %H:%M:%S') if value else None

def main():
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
    m=summary['metrics']
    with (ROOT/'data/manifest.csv').open(encoding='utf-8-sig',newline='') as f:
        manifest=list(csv.DictReader(f))
    for file in manifest:
        assert sum(1 for _ in rows(file['file_name'])) == int(file['rows'])
        assert hashlib.sha256((RAW/file['file_name']).read_bytes()).hexdigest() == file['sha256']
    orders={r['order_id']:r for r in rows('olist_orders_dataset.csv')}
    delivered={oid for oid,r in orders.items() if r['order_status']=='delivered'}
    assert len(orders)==m['all_orders']
    assert len(delivered)==m['delivered_orders']
    customers={r['customer_id']:r['customer_unique_id'] for r in rows('olist_customers_dataset.csv')}
    assert len(set(customers.values()))==m['all_distinct_buyers']
    assert len({customers[orders[oid]['customer_id']] for oid in delivered})==m['delivered_distinct_buyers']
    amounts={}
    for name,file,col in [('item','olist_order_items_dataset.csv','price'),
                          ('freight','olist_order_items_dataset.csv','freight_value'),
                          ('payment','olist_order_payments_dataset.csv','payment_value')]:
        aggregate=defaultdict(lambda:Decimal('0'))
        for r in rows(file):
            aggregate[r['order_id']]+=Decimal(r[col])
        amounts[name]=aggregate
        assert int(sum(aggregate.values())*100)==m['all_'+name+'_cents']
        assert int(sum(v for oid,v in aggregate.items() if oid in delivered)*100)==m['delivered_'+name+'_cents']
    complete=set(amounts['item']) & set(amounts['payment'])
    differs={oid for oid in complete if amounts['item'][oid]+amounts['freight'][oid]!=amounts['payment'][oid]}
    assert len(complete)==m['complete_amount_comparison_orders']
    assert len(differs)==m['payment_difference_orders']
    assert len(differs & delivered)==m['delivered_payment_difference_orders']
    selected={}
    counts=Counter()
    for number,r in enumerate(rows('olist_order_reviews_dataset.csv'),1):
        oid=r['order_id']
        counts[oid]+=1
        key=(dt(r['review_answer_timestamp']) or datetime.min,
             dt(r['review_creation_date']) or datetime.min,r['review_id'],number)
        if oid not in selected or key>selected[oid][0]:
            selected[oid]=(key,r)
    assert sum(v>1 for v in counts.values())==m['multiple_review_orders']
    with (OUT/'selected_review_keys.csv').open(encoding='utf-8-sig',newline='') as f:
        exported=list(csv.DictReader(f))
    assert len(exported)==len(selected)
    for r in exported:
        key,source=selected[r['order_id']]
        assert r['review_id']==source['review_id'] and int(r['_source_row'])==key[-1]
    eligible=[]
    valid_delivery=[]
    late=set()
    seconds=0
    for oid in delivered:
        r=orders[oid]
        purchase,arrival,expected=(dt(r[k]) for k in ['order_purchase_timestamp','order_delivered_customer_date','order_estimated_delivery_date'])
        if purchase and arrival and arrival>=purchase:
            valid_delivery.append(oid)
            seconds+=(arrival-purchase).total_seconds()
            if expected and expected.date()>=purchase.date():
                eligible.append(oid)
                if arrival.date()>expected.date():
                    late.add(oid)
    assert len(valid_delivery)==m['delivery_valid_orders']
    assert len(eligible)==m['late_eligible_orders']
    assert len(late)==m['late_orders']
    assert abs(seconds/len(valid_delivery)/86400-m['average_delivery_days'])<1e-10
    scored=delivered & set(selected)
    score_total=sum(int(selected[oid][1]['review_score']) for oid in scored)
    low=sum(int(selected[oid][1]['review_score'])<=2 for oid in scored)
    assert len(scored)==m['delivered_reviewed_orders']
    assert low==m['delivered_low_score_orders']
    assert abs(score_total/len(scored)-m['delivered_average_score'])<1e-12
    for label,subset in [('late',late),('on_time',set(eligible)-late)]:
        scored_group=subset & set(selected)
        assert len(scored_group)==m[label+'_review_sample']
        low=sum(int(selected[oid][1]['review_score'])<=2 for oid in scored_group)
        assert abs(low/len(scored_group)-m[label+'_low_score_rate'])<1e-12
    with (OUT/'checks.csv').open(encoding='utf-8-sig',newline='') as f:
        checks=list(csv.DictReader(f))
    assert len(checks)==summary['check_count']
    assert sum(x['status']=='FAIL' for x in checks)==summary['error_checks']
    missing_pay=delivered-set(amounts['payment'])
    check=next(x for x in checks if x['rule']=='delivered_without_payments')
    assert len(missing_pay)==int(check['affected_count'])
    result={
        'verification':'PASS',
        'method':'Python standard library csv + Decimal + datetime; independent of pandas audit',
        'verified':'9 file row counts/hashes, exact monetary totals/differences, customer counts, every selected review, delivery/late/score metrics, failure count',
        'missing_payment_delivered_order_ids':sorted(missing_pay),
        'source_archive_sha256':summary['source_archive_sha256'],
        'audit_script_sha256':summary['script_sha256'],
        'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (OUT/'independent_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
