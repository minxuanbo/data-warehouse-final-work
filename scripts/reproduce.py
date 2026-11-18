"""Rebuild the reviewed real-data warehouse in a dedicated local development database."""
import argparse
import json
import re
from pathlib import Path
from scripts.run_pipeline import run
from warehouse.load import ROOT,connect
from warehouse.release_build import records


def reproduce(database,prepare_bi=False):
    if not re.fullmatch(r'recruitment_dw_dev(?:_[a-z0-9_]+)?',database):raise ValueError('Dedicated development database required')
    config=json.loads((ROOT/'warehouse/pipeline.json').read_text(encoding='utf-8'));config['database']=database
    # The fixed baseline does not absorb unrelated future batches during reproduction.
    config['discover_roots']=[]
    folder=ROOT/'.local/reproduction'/database;folder.mkdir(parents=True,exist_ok=True)
    path=folder/'pipeline.json';path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    outcome=run(path)
    rid=outcome['release']['release_id']
    c=connect(database)
    try:
        counts=records(c,'''SELECT s.source_code source,COUNT_BIG(*) source_postings,
          SUM(CAST(f.is_core AS bigint)) core_postings,
          SUM(CASE WHEN f.is_core=1 AND f.body_valid=1 THEN 1 ELSE 0 END) body_denominator
          FROM dwd.fact_job_daily f JOIN dim.source s ON s.source_key=f.source_key
          WHERE f.release_id=? GROUP BY s.source_code ORDER BY s.source_code''',rid)
        pairs=records(c,'''SELECT s.source_code source,COUNT_BIG(*) posting_skill_pairs
          FROM dwd.bridge_daily_skill b JOIN dwd.fact_job_daily f
           ON f.release_id=b.release_id AND f.date_key=b.date_key AND f.job_key=b.job_key
          JOIN dim.source s ON s.source_key=f.source_key WHERE b.release_id=?
          GROUP BY s.source_code ORDER BY s.source_code''',rid)
        assert len(counts)==2 and all((x['source_postings'],x['core_postings'],x['body_denominator'])==(100,98,98) for x in counts)
        assert {x['source']:x['posting_skill_pairs'] for x in pairs}=={'netease':334,'tencent':333}
        assert c.execute('SELECT COUNT(*) FROM ads.release_validation WHERE release_id=?',rid).fetchval()==0
        assert c.execute('SELECT COUNT(*) FROM ads.release_observed_change WHERE release_id=? AND is_comparable=1',rid).fetchval()==0
    finally:c.close()
    record={'status':'passed','database':database,'release_id':rid,'source_counts':counts,'posting_skill_pairs':pairs,
      'inputs':'tracked repository files at the pinned source revisions','pipeline':outcome,'powerbi_prepared':False}
    if prepare_bi:
        from scripts.pin_powerbi import pin
        record['powerbi']=pin(database,release_id=rid);record['powerbi_prepared']=True
    (folder/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    return record


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',default='recruitment_dw_dev_reproduction');p.add_argument('--prepare-bi',action='store_true')
    a=p.parse_args();print(json.dumps(reproduce(a.database,a.prepare_bi),ensure_ascii=False,default=str))
