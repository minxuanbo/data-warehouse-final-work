"""Immutable dimensional snapshots and checked publication, for real accepted batches."""
import argparse
import hashlib
import json
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

from .load import ROOT,connect,dump
from .normalization import VERSION,MAPPING_VERSION,city,classify


def records(c,sql,*args):
    cursor=c.execute(sql,*args)
    try:
        names=[x[0] for x in cursor.description]
        return [dict(zip(names,row)) for row in cursor.fetchall()]
    finally:cursor.close()


def implementation_hash():
    names=['warehouse/release_build.py','warehouse/normalization.py','warehouse/qualifications.py','sql/004_release_schema.sql','sql/005_qualification_evidence.sql']
    return hashlib.sha256(dump({n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}).encode()).hexdigest()


def choose_inputs(builds,expected_sources,channel):
    """At most one ready accepted source batch per Beijing end-date. No invented days."""
    if not builds:raise ValueError('No ready analysis builds')
    chosen={}
    requested_days=set();query_profiles={}
    versions={(b['scope_version'],b['dictionary_version'],b['rule_version'],b['body_hash_version'],b['skill_text_scope']) for b in builds}
    if len(versions)!=1:raise ValueError('Mixed scope or extraction versions; rebuild inputs under one rule set')
    for b in builds:
        if b['source'] not in expected_sources:raise ValueError('Unexpected source')
        if b['acceptance_status']!='accepted':raise ValueError('Technical acceptance required')
        manifest=json.loads(b['manifest_json'])
        query=manifest.get('query_spec',{})
        profile=dump({'source_scope':manifest.get('scope_version'),
                      'endpoints':sorted(query.get('endpoints',[])),
                      'parameters':query.get('parameters'),
                      'selection_rule':query.get('selection_rule')})
        if b['source'] in query_profiles and query_profiles[b['source']]!=profile:
            raise ValueError('Changed collection query scope within source; do not compare incompatible windows')
        query_profiles[b['source']]=profile
        end=datetime.fromisoformat(manifest['finished_at'].replace('Z','+00:00'))
        if end.tzinfo is None:raise ValueError('Batch end time requires timezone')
        b={**b,'snapshot_date':end.astimezone(timezone(timedelta(hours=8))).date()}
        requested_days.add(b['snapshot_date'])
        key=(b['source'],b['snapshot_date'])
        if channel=='formal' and b['coverage_status']!='complete':continue
        # For a formal day use the latest COMPLETE batch; a later partial scan cannot replace it.
        if key not in chosen or (end,b['build_id'])>(chosen[key]['_ended'],chosen[key]['build_id']):
            chosen[key]={**b,'_ended':end}
    if not chosen:raise ValueError('No eligible complete batches for formal publication')
    days={b['snapshot_date'] for b in chosen.values()}
    if channel=='formal' and days!=requested_days:
        raise ValueError('Some requested dates have no complete source batch')
    if channel=='formal' and any({b['source'] for b in chosen.values() if b['snapshot_date']==d}!=set(expected_sources) for d in days):
        raise ValueError('Missing source for formal snapshot date')
    return sorted(chosen.values(),key=lambda b:(b['snapshot_date'],b['source']))


def dimension(c,table,key,name_col,value,extra=None):
    # All identifiers are internal constants; business values are parameters.
    extra=extra or {}
    where={name_col:value,**extra}
    clauses=' AND '.join(f'[{k}]=?' for k in where)
    old=c.execute(f'SELECT [{key}] FROM {table} WHERE {clauses}',*where.values()).fetchone()
    if old:return old[0]
    cols=','.join(f'[{k}]' for k in where)
    return c.execute(f'INSERT INTO {table}({cols}) OUTPUT INSERTED.[{key}] VALUES({",".join("?" for _ in where)})',*where.values()).fetchval()


def ensure_calendar(c,start,end):
    day=start
    while day<=end:
        dk=int(day.strftime('%Y%m%d'))
        if not c.execute('SELECT 1 FROM dim.calendar_date WHERE date_key=?',dk).fetchone():
            c.execute('INSERT INTO dim.calendar_date VALUES(?,?,?,?,?,?)',dk,day,day.year,(day.month-1)//3+1,day.month,day.day)
        day+=timedelta(days=1)


def build_release(build_ids,*,channel='sample',expected_sources=('tencent','netease'),fail_after=None):
    if channel not in ('sample','formal'):raise ValueError('Unknown publication channel')
    if not build_ids or any(type(x) is not int or x<=0 for x in build_ids):raise ValueError('Positive build IDs required')
    if set(expected_sources)!={'tencent','netease'}:raise ValueError('Freeze both approved sources; do not silently shrink scope')
    c=connect()
    try:
        c.execute((ROOT/'sql/004_release_schema.sql').read_text(encoding='utf-8'))
        c.execute((ROOT/'sql/005_qualification_evidence.sql').read_text(encoding='utf-8'))
        q=','.join('?' for _ in build_ids)
        metadata=records(c,f'''SELECT b.build_id,b.batch_id,b.input_hash,b.scope_version,b.dictionary_version,
          b.rule_version,b.body_hash_version,b.skill_text_scope,a.source,a.coverage_status,a.acceptance_status,a.manifest_json
          FROM audit.analysis_build b JOIN audit.collection_batch a ON a.batch_id=b.batch_id
          WHERE b.status='ready' AND b.build_id IN ({q})''',*build_ids)
        if len(metadata)!=len(set(build_ids)):raise ValueError('Unknown or unready input build')
        selected=choose_inputs(metadata,expected_sources,channel)
        code_hash=implementation_hash()
        fingerprint=hashlib.sha256(dump({'inputs':[(b['build_id'],b['input_hash']) for b in selected],
          'normalization':VERSION,'mapping':MAPPING_VERSION,'channel':channel,'sources':sorted(expected_sources),'code':code_hash,
          'failure_probe':fail_after}).encode()).hexdigest()
        c.execute('SET XACT_ABORT ON; BEGIN TRANSACTION;')
        c.execute("DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource='dimensional_release',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000; IF @r<0 THROW 50005,'release lock timeout',1;")
        old=c.execute('SELECT release_id,status FROM audit.model_build WHERE input_hash=?',fingerprint).fetchone()
        if old:
            if old[1]!='ready':raise ValueError('Existing release is not ready')
            c.execute('COMMIT TRANSACTION;')
            return {'status':'unchanged','release_id':old[0],'channel':channel}
        release_id=c.execute('''INSERT INTO audit.model_build(input_hash,normalization_version,mapping_version,channel,expected_sources_json,status,code_sha256)
          OUTPUT INSERTED.release_id VALUES(?,?,?,?,?,'building',?)''',fingerprint,VERSION,MAPPING_VERSION,channel,dump(sorted(expected_sources)),code_hash).fetchval()
        days=[b['snapshot_date'] for b in selected]
        ensure_calendar(c,min(days),max(days))
        count=0
        for batch in selected:
            source=batch['source'];dk=int(batch['snapshot_date'].strftime('%Y%m%d'))
            source_key=c.execute('SELECT source_key FROM dim.source WHERE source_code=?',source).fetchval()
            if source_key is None:
                source_key=c.execute('INSERT INTO dim.source(source_code,source_name,official_url) OUTPUT INSERTED.source_key VALUES(?,?,?)',
                  source,{'tencent':'腾讯招聘','netease':'网易招聘'}[source],{'tencent':'https://careers.tencent.com','netease':'https://hr.163.com'}[source]).fetchval()
            c.execute('INSERT INTO audit.release_input VALUES(?,?,?,?,?,?,?)',release_id,batch['build_id'],source_key,batch['batch_id'],dk,batch['coverage_status'],batch['acceptance_status'])
            jobs=records(c,'''SELECT j.*,o.posting_key,o.company_raw,o.employment_type_raw,r.payload as original_record_json
              FROM ads.cd_job_detail j JOIN dwd.fact_posting_observation o ON o.observation_key=j.observation_key
              JOIN ods.posting_record r ON r.batch_id=j.batch_id AND r.source_job_id=j.source_job_id WHERE j.build_id=?''',batch['build_id'])
            if not jobs:raise ValueError('Empty input build')
            for job in jobs:
                labels=classify(job)
                keys=[dimension(c,*args) for args in [
                  ('dim.company','company_key','company_name',labels['company']),
                  ('dim.job_category','category_key','category_name',labels['category'],{'normalization_version':VERSION}),
                  ('dim.education','education_key','education_name',labels['education']),
                  ('dim.experience','experience_key','experience_name',labels['experience']),
                  ('dim.employment_type','employment_type_key','employment_type_name',labels['employment_type'])]]
                job_key=c.execute('SELECT job_key FROM dim.job WHERE posting_key=?',job['posting_key']).fetchval()
                if job_key is None:
                    job_key=c.execute("INSERT INTO dim.job(posting_key,creation_method) OUTPUT INSERTED.job_key VALUES(?,'source_identity_only')",job['posting_key']).fetchval()
                if not c.execute('SELECT 1 FROM dwd.posting_job_map WHERE mapping_version=? AND posting_key=?',MAPPING_VERSION,job['posting_key']).fetchone():
                    c.execute("INSERT INTO dwd.posting_job_map VALUES(?,?,?,'source_identity_only')",MAPPING_VERSION,job['posting_key'],job_key)
                c.execute('''INSERT INTO dwd.fact_job_daily(release_id,date_key,job_key,build_id,observation_key,representative_version_key,
                  source_key,company_key,category_key,education_key,experience_key,employment_type_key,is_core,body_valid)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',release_id,dk,job_key,batch['build_id'],job['observation_key'],job['version_key'],source_key,*keys,job['is_core'],job['body_valid'])
                q=labels['qualifications']
                original=json.loads(job['original_record_json'])
                for resolution in q.values():
                    resolution['record_ref']=f"data/{source}/{job['batch_id']}/jobs.jsonl#{job['source_job_id']}"
                    resolution['raw_refs']=original['raw_refs']
                c.execute('INSERT INTO dwd.job_qualification_evidence VALUES(?,?,?,?,?,?)',release_id,dk,job_key,
                          q['education']['rule_version'],dump(q['education']),dump(q['experience']))
                locations=[None] if job['location_conflict'] else json.loads(job['confirmed_locations_json']) or [None]
                city_keys=set()
                for location in locations:
                    loc=city(location,job['location_conflict'])
                    ck=c.execute('SELECT city_key FROM dim.city WHERE normalization_version=? AND city_code=?',VERSION,loc['code']).fetchval()
                    if ck is None:
                        ck=c.execute('''INSERT INTO dim.city(city_code,city_name,province_name,mapping_status,normalization_version)
                          OUTPUT INSERTED.city_key VALUES(?,?,?,?,?)''',loc['code'],loc['name'],loc['province'],loc['mapping_status'],VERSION).fetchval()
                    city_keys.add(ck)
                for ck in city_keys:c.execute('INSERT INTO dwd.bridge_daily_city VALUES(?,?,?,?)',release_id,dk,job_key,ck)
                if job['is_core'] and job['body_valid']:
                    c.execute('''INSERT INTO dwd.bridge_daily_skill SELECT DISTINCT ?,?,?,skill_key
                      FROM dwd.bridge_version_skill WHERE build_id=? AND version_key=? AND eligible_for_metric=1''',release_id,dk,job_key,batch['build_id'],job['version_key'])
                count+=1
                if fail_after==count:raise RuntimeError('Injected snapshot failure')
        if fail_after is not None:raise ValueError('Failure probe threshold exceeds snapshot rows; refuse a ready test build')
        c.execute("UPDATE audit.model_build SET status='ready' WHERE release_id=?",release_id)
        c.execute('COMMIT TRANSACTION;')
        return {'status':'ready','release_id':release_id,'channel':channel,'source_observations':count,'dates':[str(d) for d in sorted(set(days))]}
    except Exception:
        c.execute('IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;');raise
    finally:c.close()


def publish(release_id,*,channel='sample',fail_before_pointer=False):
    """Single short transaction. A failed validation never moves the pointer."""
    c=connect()
    try:
        # Views contain independent FK/grain/metric/readiness checks; require deployment first.
        invalid=c.execute('SELECT COUNT_BIG(*) FROM ads.release_validation WHERE release_id=?',release_id).fetchval()
        if invalid:raise ValueError(f'Release validation failed: {invalid} issues')
        c.execute('SET XACT_ABORT ON; BEGIN TRANSACTION;')
        c.execute("DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource='release_publication',@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=10000; IF @r<0 THROW 50006,'publication lock timeout',1;")
        build=c.execute('SELECT status,channel FROM audit.model_build WHERE release_id=?',release_id).fetchone()
        if not build or tuple(build)!=('ready',channel):raise ValueError('Ready release and channel must match')
        if channel=='formal' and c.execute('SELECT COUNT(*) FROM dws.release_daily_summary WHERE release_id=? AND is_complete=0',release_id).fetchval():
            raise ValueError('Incomplete daily coverage cannot be formally published')
        if c.execute('SELECT COUNT_BIG(*) FROM ads.release_validation WHERE release_id=?',release_id).fetchval():raise ValueError('Release failed final validation')
        old=c.execute('SELECT release_id FROM audit.publication_pointer WHERE channel=?',channel).fetchval()
        if old==release_id:
            c.execute('COMMIT TRANSACTION;');return {'status':'unchanged','release_id':release_id,'channel':channel}
        if fail_before_pointer:raise RuntimeError('Injected publication failure')
        c.execute('''INSERT INTO audit.publication_history(channel,release_id,previous_release_id,validation_json)
          VALUES(?,?,?,?)''',channel,release_id,old,dump({'issues':invalid,'normalization_version':VERSION}))
        c.execute('DELETE FROM audit.publication_pointer WHERE channel=?',channel)
        c.execute('INSERT INTO audit.publication_pointer(channel,release_id) VALUES(?,?)',channel,release_id)
        c.execute('COMMIT TRANSACTION;')
        return {'status':'published','release_id':release_id,'previous_release_id':old,'channel':channel}
    except Exception:
        c.execute('IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;');raise
    finally:c.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build-ids',nargs='+',type=int,required=True)
    p.add_argument('--channel',choices=['sample','formal'],default='sample');p.add_argument('--publish',action='store_true')
    a=p.parse_args();result=build_release(a.build_ids,channel=a.channel)
    if a.publish:result['publication']=publish(result['release_id'],channel=a.channel)
    print(json.dumps(result,ensure_ascii=False))
