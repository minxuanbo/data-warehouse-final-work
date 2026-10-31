"""Export local trial interfaces for D without committing duplicate raw data."""
import json
from pathlib import Path
from .load import connect

QUERIES = {
    'overview': 'SELECT * FROM ads.trial_overview ORDER BY batch_id',
    'city': 'SELECT * FROM ads.trial_city ORDER BY batch_id,location_raw',
    'job_detail': 'SELECT * FROM ads.trial_job_detail ORDER BY batch_id,source_job_id',
}

if __name__ == '__main__':
    dest=Path('.local/trial_exports')
    dest.mkdir(parents=True,exist_ok=True)
    c=connect()
    try:
        for name,sql in QUERIES.items():
            cursor=c.execute(sql)
            keys=[col[0] for col in cursor.description]
            rows=[dict(zip(keys,row)) for row in cursor]
            with (dest/f'{name}.jsonl').open('w',encoding='utf-8',newline='\n') as f:
                for row in rows:f.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
            print(f'{name}: {len(rows)} rows -> {dest / (name + ".jsonl")}')
    finally:c.close()
