"""Native scheduled collection: bounded runtime, real timestamps, pending review, no publication."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
LOCAL=ROOT/'.local/scheduled_collection'
BEIJING=timezone(timedelta(hours=8))


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp.'+str(os.getpid()))
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    os.replace(temporary,path)


def configuration():
    config=json.loads((ROOT/'warehouse/collection_schedule.json').read_text(encoding='utf-8'))
    if len(config['sources'])!=4 or set(config['sources'])!={'tencent','netease','xiaomi','jd'}:
        raise ValueError('Exactly four approved sources required')
    if config.get('automatic_acceptance') or config.get('automatic_publication'):
        raise ValueError('Scheduled collection may not approve or publish inputs')
    if not 1<=config['max_pages']<=500 or not 1<=config['max_runtime_minutes']<=100:
        raise ValueError('Invalid finite collection limits')
    return config


def check(output):
    config=configuration()
    if importlib.util.find_spec('requests') is None:raise ValueError('Project requests dependency missing')
    from collectors.daily import Daily
    from warehouse.validate import validate
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    LOCAL.mkdir(parents=True,exist_ok=True)
    record={'status':'ready','checked_at':datetime.now(BEIJING).isoformat(),'python':sys.executable,
            'working_directory':str(Path.cwd()),'project_root':str(ROOT),'revision':revision,
            'config':config,'network_requests':0,'collection_started':False}
    write(output,record)
    return 0


def worker(source,folder):
    from collectors.daily import Daily
    from warehouse.validate import validate
    config=configuration()
    collector=Daily(source,config['target_if_bounded'],config['max_pages'],config['until_exhausted'])
    stamp=datetime.now(BEIJING).isoformat()
    status={'source':source,'batch_path':str(collector.path),'started_at':stamp,'status':'running'}
    write(folder/(source+'.json'),status)
    try:
        code=collector.run()
        path=collector.path/'manifest.json'
        m=json.loads(path.read_text(encoding='utf-8'))
        # This is a new pending batch, before review/hash pinning; old batches are never edited.
        if m['acceptance_status']!='pending':raise ValueError('Fresh pending batch required')
        m['collection_window']='scheduled-four-source-'+folder.name
        m['execution_actor']='User-authorized Windows scheduled collection; no human review or automatic approval'
        m['scheduled_collection']={'runner_version':config['version'],'scheduled_time_beijing':config['daily_time'],
                                   'actual_started_at':stamp,'run_id':folder.name}
        for name in ('scripts/scheduled_collection.py','warehouse/collection_schedule.json'):
            m['collector_source'].append({'path':name,'sha256':hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),'newline':'LF'})
        if config['until_exhausted']:
            m['query_spec']['parameters'].pop('target',None)
        write(path,m)
        verified=validate(collector.path)
        status.update(status='collected_pending_review' if code==0 else 'partial_error_pending_review',
                      coverage_status=m['coverage_status'],source_postings=len(verified['jobs']),
                      requests=m['counts']['requests'],stop_reason=m['stop_reason'],collector_exit_code=code)
        return code
    except Exception as exc:
        status.update(status='failed',error=str(exc),traceback=traceback.format_exc())
        return 2
    finally:
        status['finished_at']=datetime.now(BEIJING).isoformat()
        write(folder/(source+'.json'),status)


def run():
    import msvcrt
    config=configuration();LOCAL.mkdir(parents=True,exist_ok=True)
    # The lock also blocks overlapping manual starts; Windows releases it on process exit.
    with (LOCAL/'collector.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:return 0
        try:
            stamp=datetime.now(BEIJING)
            day=stamp.strftime('%Y%m%d')
            marker=LOCAL/'days'/(day+'.json')
            if marker.exists():return 0  # One automatic run per actual Beijing day.
            folder=LOCAL/'runs'/stamp.strftime('%Y%m%dT%H%M%S%f')
            folder.mkdir(parents=True,exist_ok=False)
            write(marker,{'actual_date':day,'run_directory':str(folder),'started_at':stamp.isoformat()})
            summary={'status':'running','started_at':stamp.isoformat(),'run_directory':str(folder),'config':config}
            write(LOCAL/'latest.json',summary)
            children=[]
            try:
                for source in config['sources']:
                    log=(folder/(source+'.log')).open('wb')
                    worker_python=Path(sys.executable).with_name('python.exe')
                    if not worker_python.exists():raise ValueError('Project console Python missing for captured worker logs')
                    command=[str(worker_python),'-X','utf8','-m','scripts.scheduled_collection','--worker',source,'--run-dir',str(folder)]
                    process=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    log.close();children.append((source,process))
                deadline=time.monotonic()+config['max_runtime_minutes']*60
                while any(p.poll() is None for _,p in children) and time.monotonic()<deadline:time.sleep(1)
                timed_out=[]
                for source,p in children:
                    if p.poll() is None:
                        p.kill();p.wait();timed_out.append(source)
                summary['sources']=[]
                for source,p in children:
                    path=folder/(source+'.json')
                    item=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'source':source,'status':'failed_to_start'}
                    if source in timed_out:item.update(status='timeout_unfinished_batch',exit_code=p.returncode)
                    else:item['exit_code']=p.returncode
                    summary['sources'].append(item)
                failed=any(s['exit_code']!=0 or s['status']!='collected_pending_review' for s in summary['sources'])
                summary.update(status='needs_attention' if failed else 'collected_pending_review',
                               finished_at=datetime.now(BEIJING).isoformat(),timed_out_sources=timed_out)
                write(folder/'summary.json',summary);write(LOCAL/'latest.json',summary)
                return 2 if failed else 0
            finally:
                for _,p in children:
                    if p.poll() is None:p.kill();p.wait()
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',type=Path)
    p.add_argument('--worker',choices=['tencent','netease','xiaomi','jd']);p.add_argument('--run-dir',type=Path)
    a=p.parse_args()
    try:
        result=check(a.check) if a.check else worker(a.worker,a.run_dir) if a.worker else run()
    except Exception as exc:
        LOCAL.mkdir(parents=True,exist_ok=True)
        failure={'status':'failed','error':str(exc),'traceback':traceback.format_exc(),
                 'at':datetime.now(BEIJING).isoformat()}
        write(LOCAL/'entry_failure.json',failure)
        if not a.check and not a.worker:write(LOCAL/'latest.json',failure)
        result=2
    raise SystemExit(result)
