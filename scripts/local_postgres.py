"""Manage a project-local PostgreSQL instance on Windows, no system service."""
from pathlib import Path
import argparse
import os
import secrets
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
BIN=ROOT/'.runtime/pgsql/bin'
LOCAL=ROOT/'.local'

def run(name,*args,check=True):
    result=subprocess.run([str(BIN/(name+'.exe')),*map(str,args)],check=check,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    return result.returncode

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['start','stop','status'])
    args=parser.parse_args()
    if not (BIN/'pg_ctl.exe').exists():
        raise SystemExit('Run python scripts/fetch_postgres.py first')
    LOCAL.mkdir(exist_ok=True)
    data=LOCAL/'pgdata'
    if args.action in ['stop','status']:
        return run('pg_ctl','-D',data,args.action,check=False)
    envfile=ROOT/'.env'
    if not (data/'PG_VERSION').exists():
        if envfile.exists():
            raise SystemExit('Existing .env found: use your existing PostgreSQL, or move it aside before local bootstrap')
        password=secrets.token_urlsafe(32)
        pw=LOCAL/'init-password.tmp'
        pw.write_text(password,encoding='utf-8')
        try:
            run('initdb','-D',data,'-U','olist_admin','--pwfile',pw,
                '--auth=scram-sha-256','--encoding=UTF8','--locale=C')
        finally:
            pw.unlink(missing_ok=True)
        with (data/'postgresql.conf').open('a',encoding='utf-8') as f:
            f.write("\nlisten_addresses = '127.0.0.1'\nport = 55432\nshared_buffers = '128MB'\n")
        envfile.write_text(f'PGHOST=127.0.0.1\nPGPORT=55432\nPGUSER=olist_admin\nPGPASSWORD={password}\nPGDATABASE=olist_dw\n',encoding='utf-8')
    if run('pg_ctl','-D',data,'status',check=False)!=0:
        run('pg_ctl','-D',data,'-l',LOCAL/'postgres.log','-w','start')
    # Read credentials without displaying them.
    for line in envfile.read_text(encoding='utf-8').splitlines():
        if '=' in line:
            k,v=line.split('=',1)
            os.environ[k]=v
    import psycopg
    with psycopg.connect(dbname='postgres',autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname='olist_dw'").fetchone():
            conn.execute('CREATE DATABASE olist_dw')
    print('Local PostgreSQL ready at 127.0.0.1:55432 / olist_dw; credentials are in ignored .env')
    return 0

if __name__=='__main__':
    sys.exit(main())
