"""Explicit-transaction trial loader. Does not approve or publish a batch."""
import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .validate import validate, digest

ROOT = Path(__file__).resolve().parents[1]


def connect(database=None):
    import pyodbc
    database = database or os.getenv('DW_DATABASE', 'recruitment_dw_dev')
    if database != 'master' and not re.fullmatch(r'recruitment_dw_dev(?:_[a-z0-9_]+)?', database):
        raise ValueError('Trial loader only writes recruitment_dw_dev* databases')
    host = os.getenv('DW_SERVER', 'lpc:localhost')
    if any(x in host for x in ';{}'):
        raise ValueError('Invalid server')
    return pyodbc.connect(
        f'DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={host};DATABASE={database};'
        'Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;',
        autocommit=True, timeout=10)


def initialize():
    database = os.getenv('DW_DATABASE', 'recruitment_dw_dev')
    if not re.fullmatch(r'recruitment_dw_dev(?:_[a-z0-9_]+)?', database):
        raise ValueError('Invalid trial database name')
    c = connect('master')
    try:
        if c.execute('SELECT DB_ID(?)', database).fetchval() is None:
            c.execute(f'CREATE DATABASE [{database}]')
    finally:
        c.close()
    c = connect()
    try:
        for name in ('001_trial_schema.sql', '002_cd_schema.sql'):
            c.execute((ROOT / 'sql' / name).read_text(encoding='utf-8'))
    finally:
        c.close()


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def content(row):
    return {k:v for k,v in row.items() if k.endswith('_raw') or k=='source_url'}


def version_action(previous_hash, previous_time, new_hash, new_time):
    """No silent late-arrival rewrite; identical timestamps may only repeat content."""
    if previous_time and (new_time < previous_time or (new_time == previous_time and previous_hash != new_hash)):
        raise ValueError('Late/conflicting observation: explicit history rebuild required')
    return 'reuse' if previous_hash == new_hash else 'new'


def load(path, revision, *, _fail_after=None):
    checked = validate(path)
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Supply full input Git revision')
    m = checked['manifest']
    c = connect()
    try:
        c.execute("SET XACT_ABORT ON; BEGIN TRANSACTION;")
        c.execute("DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource='warehouse_trial_load',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000; IF @r<0 THROW 50001,'load lock timeout',1;")
        old = c.execute('SELECT input_hash FROM audit.collection_batch WHERE batch_id=?',m['batch_id']).fetchone()
        if old:
            if old[0] != checked['input_hash']:
                raise ValueError('Same batch_id has changed content/manifest; refuse overwrite')
            c.execute('COMMIT TRANSACTION;')
            return {'status':'unchanged','batch_id':m['batch_id'],**checked['summary']}
        c.execute('INSERT INTO audit.collection_batch(batch_id,source,scope_version,input_hash,source_revision,manifest_json,coverage_status,acceptance_status,load_mode,record_count) VALUES(?,?,?,?,?,?,?,?,?,?)',
                  m['batch_id'],m['source'],m['scope_version'],checked['input_hash'],revision,dump(m),m['coverage_status'],m['acceptance_status'],'trial',len(checked['jobs']))
        for f in checked['files'].values():
            if f['path'].startswith('raw/'):
                c.execute('INSERT INTO ods.raw_response VALUES(?,?,?,?)',m['batch_id'],f['path'],f['sha256'],f['bytes'])
        for n,issue in enumerate(checked['issues'],1):
            c.execute('INSERT INTO audit.quality_issue VALUES(?,?,?)',m['batch_id'],n,dump(issue))
        for n,row in enumerate(checked['jobs'],1):
            c.execute('INSERT INTO ods.posting_record VALUES(?,?,?)',m['batch_id'],row['source_job_id'],dump(row))
            identity = c.execute('SELECT posting_key FROM dim.posting_identity WHERE source=? AND source_job_id=?',row['source'],row['source_job_id']).fetchone()
            key = identity[0] if identity else c.execute('INSERT INTO dim.posting_identity(source,source_job_id) OUTPUT INSERTED.posting_key VALUES(?,?)',row['source'],row['source_job_id']).fetchval()
            chash = digest(dump(content(row)).encode('utf-8'))
            previous = c.execute('SELECT version_key,content_hash,CONVERT(varchar(40),valid_from_observed,127) FROM dim.posting_version WHERE posting_key=? AND valid_to_observed IS NULL',key).fetchone()
            observed = datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'))
            last = c.execute('SELECT TOP(1) CONVERT(varchar(40),observed_at,127) FROM dwd.fact_posting_observation WHERE posting_key=? ORDER BY observed_at DESC',key).fetchone()
            action = version_action(previous[1] if previous else None,datetime.fromisoformat(last[0].replace('Z','+00:00')) if last else None,chash,observed)
            if action == 'reuse':
                version = previous[0]
            else:
                if previous:
                    c.execute('UPDATE dim.posting_version SET valid_to_observed=? WHERE version_key=?',row['observed_at'],previous[0])
                version = c.execute('INSERT INTO dim.posting_version(posting_key,content_hash,valid_from_observed,payload) OUTPUT INSERTED.version_key VALUES(?,?,?,?)',key,chash,row['observed_at'],dump(content(row))).fetchval()
                for place in sorted(set(row['locations_raw'] or [])):
                    location = c.execute('SELECT location_key FROM dim.location WHERE location_raw=?',place).fetchone()
                    lk = location[0] if location else c.execute('INSERT INTO dim.location(location_raw) OUTPUT INSERTED.location_key VALUES(?)',place).fetchval()
                    c.execute('INSERT INTO dwd.bridge_version_location VALUES(?,?,?)',version,lk,'raw_location_v1')
            date = observed.astimezone(timezone(timedelta(hours=8))).date().isoformat()
            c.execute('INSERT INTO dwd.fact_posting_observation(batch_id,posting_key,version_key,observed_at,analysis_date,title_raw,company_raw,category_raw,experience_raw,education_raw,employment_type_raw,source_url,body_valid) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      m['batch_id'],key,version,row['observed_at'],date,row['title_raw'],row['company_raw'],row['category_raw'],row['experience_raw'],row['education_raw'],row['employment_type_raw'],row['source_url'],bool(row['description_raw'] or row['requirements_raw']))
            if _fail_after == n:
                raise RuntimeError('Injected rollback test failure')
        c.execute('COMMIT TRANSACTION;')
        return {'status':'loaded_trial','batch_id':m['batch_id'],**checked['summary']}
    except Exception:
        c.execute('IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;')
        raise
    finally:
        c.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch')
    parser.add_argument('--revision',required=True)
    parser.add_argument('--init',action='store_true')
    args = parser.parse_args()
    # Validate before even creating the development database.
    validate(args.batch)
    if args.init:
        initialize()
    print(json.dumps(load(args.batch,args.revision),ensure_ascii=False))
