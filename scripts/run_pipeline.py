"""Generic accepted-batch -> evidence -> dimensions -> tests -> atomic publication."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path

from warehouse.load import ROOT,initialize,load
from warehouse.integrate_analysis import integrate
from warehouse.prepare_analysis import generate
from warehouse.release_build import build_release,publish
from warehouse.validate import validate


def verify_revision(batch,revision):
    if not re.fullmatch(r'[0-9a-f]{40}',revision):raise ValueError('Full input Git revision required')
    m=json.loads((batch/'manifest.json').read_text(encoding='utf-8'))
    for name in ('manifest.json','jobs.jsonl'):
        content=subprocess.run(['git','show',f"{revision}:data/{m['source']}/{m['batch_id']}/{name}"],cwd=ROOT,capture_output=True,check=True).stdout
        if hashlib.sha256(content).digest()!=hashlib.sha256((batch/name).read_bytes()).digest():
            raise ValueError(f'Git input does not match batch: {name}')


def run(config_path,*,dry_run=False):
    config=json.loads(Path(config_path).read_text(encoding='utf-8'))
    database=config['database']
    if not re.fullmatch(r'recruitment_dw_dev(?:_[a-z0-9_]+)?',database):raise ValueError('Dedicated development database required')
    inputs=list(config['inputs']);known={Path(x['batch_path']).name for x in inputs}
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    pending=[]
    for relative in config.get('discover_roots',[]):
        directory=(ROOT/relative).resolve()
        if not directory.is_relative_to(ROOT/'data'):raise ValueError('Discovery must stay inside project data')
        for manifest in sorted(directory.glob('*/manifest.json')):
            m=json.loads(manifest.read_text(encoding='utf-8'))
            if m['batch_id'] in known:continue
            if m.get('acceptance_status')!='accepted':pending.append(m['batch_id']);continue
            inputs.append({'batch_path':str(manifest.parent),'revision':head});known.add(m['batch_id'])
    prepared=[]
    for item in inputs:
        batch=(ROOT/item['batch_path']).resolve();checked=validate(batch)
        if checked['manifest']['acceptance_status']!='accepted':raise ValueError('Configured batch has not passed technical acceptance')
        verify_revision(batch,item['revision'])
        prepared.append((item,batch,checked))
    if dry_run:return {'status':'validated','input_batches':[c['manifest']['batch_id'] for _,_,c in prepared],'pending_batches':pending,'database':database}
    previous=os.environ.get('DW_DATABASE');os.environ['DW_DATABASE']=database
    out=ROOT/'.local/pipeline_runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
    record={'started_at':datetime.now(timezone.utc).isoformat(),'database':database,'pending_batches':pending,'inputs':[]}
    try:
        initialize();build_ids=[]
        for item,batch,checked in prepared:
            loaded=load(batch,item['revision'])
            dictionary=(ROOT/item.get('dictionary_path','etl/skills/dictionary.json')).resolve()
            if item.get('analysis_path'):
                analysis=(ROOT/item['analysis_path']).resolve()
            else:
                # A changed manifest/rule/dictionary gets a fresh output directory, never overwrites prior evidence.
                policy=(ROOT/item.get('policy_path','warehouse/cd_policy_v12.json')).resolve()
                fingerprint=hashlib.sha256((checked['input_hash']+hashlib.sha256(policy.read_bytes()).hexdigest()+
                  hashlib.sha256(dictionary.read_bytes()).hexdigest()+hashlib.sha256((ROOT/'etl/skills/extract.py').read_bytes()).hexdigest()).encode()).hexdigest()[:20]
                analysis=ROOT/'.local/analysis_builds'/batch.name/fingerprint
                generate(batch,analysis,dictionary,policy)
            integrated=integrate(batch,analysis,dictionary)
            build_ids.append(integrated['build_id'])
            record['inputs'].append({'batch_id':batch.name,'load':loaded['status'],'analysis':integrated})
        # Resolve the CLI from the active, pinned Python environment; a clean source
        # checkout may share that environment without sharing any hidden input data.
        dbt=Path(sys.executable).with_name('dbt.exe')
        if not dbt.exists():raise ValueError('Run with the project .venv-dbt Python environment')
        command=[str(dbt),'build','--project-dir',str(ROOT/'dbt'),'--profiles-dir',str(ROOT/'dbt'),
                 '--select','resource_type:model','resource_type:test']
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        (out/'dbt.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError('dbt failed; previous publication preserved. See local dbt.log')
        release=build_release(build_ids,channel=config.get('channel','sample'))
        # New snapshot rows are checked AFTER construction, before any pointer switch.
        from warehouse.load import connect
        c=connect()
        try:
            if c.execute('SELECT COUNT_BIG(*) FROM ads.release_validation WHERE release_id=?',release['release_id']).fetchval():
                raise ValueError('Snapshot validation failed')
        finally:c.close()
        publication=publish(release['release_id'],channel=config.get('channel','sample'))
        record.update(status='passed',release=release,publication=publication)
        return record
    except Exception as exc:
        record.update(status='failed',error=str(exc));raise
    finally:
        record['finished_at']=datetime.now(timezone.utc).isoformat()
        (out/'run.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if previous is None:os.environ.pop('DW_DATABASE',None)
        else:os.environ['DW_DATABASE']=previous


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='warehouse/pipeline.json');p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    try:
        print(json.dumps(run(ROOT/a.config,dry_run=a.dry_run),ensure_ascii=False))
    except Exception as exc:
        # A scheduled pythonw run also needs a visible record when input validation
        # fails before the regular per-run directory was created.
        folder=ROOT/'.local/pipeline_runs';folder.mkdir(parents=True,exist_ok=True)
        name=datetime.now(timezone.utc).strftime('bootstrap_failed_%Y%m%dT%H%M%S%fZ.json')
        (folder/name).write_text(json.dumps({'status':'failed','stage':'entry_or_pipeline','error':str(exc),'config':a.config},ensure_ascii=False,indent=2),encoding='utf-8')
        raise
