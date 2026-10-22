"""Back up the development DB, verify a restore in a database created by this script."""
from datetime import datetime
import shutil
import subprocess
from psycopg import sql
import psycopg
from psycopg.rows import dict_row
from warehouse import ROOT,OUT,connect,write_json,sha256

def binary(name):
    local=ROOT/'.runtime/pgsql/bin'/(name+'.exe')
    return str(local) if local.exists() else shutil.which(name) or name

def main():
    target=ROOT/'.local/olist_dw.dump'
    target.parent.mkdir(exist_ok=True)
    name='olist_restore_'+datetime.now().strftime('%Y%m%d%H%M%S')
    with connect() as conn:
        original=conn.execute('SELECT * FROM ads.kpi_overview').fetchone()
        expected_raw=conn.execute('SELECT COUNT(*) AS n FROM ods.geolocation').fetchone()['n']
        subprocess.run([binary('pg_dump'),'--format=custom','--file',str(target)],check=True)
        if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone():
            raise RuntimeError('Refusing to reuse an existing restore database')
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            subprocess.run([binary('pg_restore'),'--exit-on-error','--no-owner','--no-acl','--dbname',name,str(target)],check=True)
            with psycopg.connect(dbname=name,autocommit=True,row_factory=dict_row) as restored:
                if restored.execute('SELECT * FROM ads.kpi_overview').fetchone()!=original:
                    raise AssertionError('Restored KPI mismatch')
                if restored.execute('SELECT COUNT(*) AS n FROM ods.geolocation').fetchone()['n']!=expected_raw:
                    raise AssertionError('Restored ODS mismatch')
        finally:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
    write_json(OUT/'backup_restore.json',{'status':'PASS','format':'pg_dump custom',
        'backup_bytes':target.stat().st_size,'backup_sha256':sha256(target),
        'restored_kpi_matches':True,'restored_geolocation_rows':expected_raw,
        'test_database_removed':True,'backup_location':'ignored .local/olist_dw.dump',
        'scope':'warehouse structure and data; reader login credentials not included'})
    print('Backup and disposable restore verified')

if __name__=='__main__':
    main()
