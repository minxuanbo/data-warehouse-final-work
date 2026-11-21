"""Append accepted observations while keeping the selected analytical release fixed."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from scripts.run_pipeline import verify_revision
from warehouse.load import ROOT, connect, load
from warehouse.validate import validate


def selected_release(database):
    c=connect(database)
    try:
        rid=c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()
        if rid is None: raise ValueError('Existing published sample required')
        return {'release_id':rid,
                'snapshot_rows':c.execute('SELECT COUNT_BIG(*) FROM dwd.fact_job_daily WHERE release_id=?',rid).fetchval(),
                'core_rows':c.execute('SELECT COUNT_BIG(*) FROM dwd.fact_job_daily WHERE release_id=? AND is_core=1',rid).fetchval(),
                'skill_pairs':c.execute('SELECT COUNT_BIG(*) FROM dwd.bridge_daily_skill WHERE release_id=?',rid).fetchval(),
                'release_inputs':[tuple(r) for r in c.execute('SELECT batch_id,build_id FROM audit.release_input WHERE release_id=? ORDER BY batch_id',rid)]}
    finally:c.close()


def ingest(database, batches, revision, output):
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    checked=[]
    for batch in batches:
        item=validate(batch)
        if item['manifest']['acceptance_status']!='accepted':raise ValueError('Accepted immutable batch required')
        verify_revision(item['root'],revision)
        checked.append(item)
    before=selected_release(database)
    previous=os.environ.get('DW_DATABASE');os.environ['DW_DATABASE']=database
    results=[]
    try:
        for item in checked:
            first=load(item['root'],revision)
            repeated=load(item['root'],revision)
            assert repeated['status']=='unchanged'
            c=connect(database)
            try:
                bid=item['manifest']['batch_id']
                ods=c.execute('SELECT COUNT_BIG(*) FROM ods.posting_record WHERE batch_id=?',bid).fetchval()
                observations=c.execute('SELECT COUNT_BIG(*) FROM dwd.fact_posting_observation WHERE batch_id=?',bid).fetchval()
                assert ods==observations==len(item['jobs'])
            finally:c.close()
            results.append({'source':item['manifest']['source'],'batch_id':bid,'first':first['status'],
                            'repeated':repeated['status'],'ods_rows':ods,'observation_rows':observations})
        after=selected_release(database)
        assert before==after,'Published analytical snapshot changed while appending observations'
    finally:
        if previous is None:os.environ.pop('DW_DATABASE',None)
        else:os.environ['DW_DATABASE']=previous
    result={'status':'passed','checked_at_utc':datetime.now(timezone.utc).isoformat(),
            'database':database,'input_revision':revision,'batches':results,
            'selected_release_before':before,'selected_release_after':after,
            'scope':'New source observations in ODS/history only; not an analytical release or market-growth claim'}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('batches',nargs='+',type=Path)
    p.add_argument('--database',required=True);p.add_argument('--revision',required=True);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();print(json.dumps(ingest(a.database,a.batches,a.revision,a.output),ensure_ascii=False))
