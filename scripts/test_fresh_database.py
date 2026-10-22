"""Run the entire pipeline on a new disposable database, then remove only that database."""
from datetime import datetime
import os
import subprocess
import sys
from psycopg import sql
from warehouse import connect, ROOT, read_json, write_json, OUT

def main():
    name='olist_test_'+datetime.now().strftime('%Y%m%d%H%M%S')
    dest=ROOT/'.local/fresh-evidence'
    with connect() as conn:
        if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone():
            raise RuntimeError('Test database name already exists; refusing reuse')
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            env={**os.environ,'PGDATABASE':name,'OLIST_REPORT_DIR':str(dest)}
            subprocess.run([sys.executable,str(ROOT/'scripts/warehouse.py'),'run'],env=env,check=True)
            result=read_json(dest/'last_run.json')
            if result['ods_reused']:
                raise AssertionError('Fresh test unexpectedly reused ODS')
            baseline=read_json(OUT/'export_hashes.json')
            if result['exports_sha256']!=baseline:
                raise AssertionError('Fresh build differs from established KPI exports')
            result['verification']='PASS'
            result['test_database_removed']=True
        finally:
            # Only the unique database created above is removed; never a configured user DB.
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        write_json(OUT/'fresh_database.json',result)
        print('Fresh database build and KPI comparison passed')

if __name__=='__main__':
    main()
