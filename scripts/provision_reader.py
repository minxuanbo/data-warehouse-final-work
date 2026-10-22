"""Create a project ADS-only reader and verify source access is denied."""
import secrets
import psycopg
from psycopg import sql
from warehouse import ROOT,OUT,connect,write_json

def main():
    envfile=ROOT/'.local/reader.env'
    envfile.parent.mkdir(exist_ok=True)
    with connect() as conn:
        exists=conn.execute("SELECT 1 FROM pg_roles WHERE rolname='olist_reader'").fetchone()
        if exists and not envfile.exists():
            raise RuntimeError('Existing reader role without local credentials; refusing password reset')
        if not exists:
            password=secrets.token_urlsafe(32)
            conn.execute(sql.SQL('CREATE ROLE olist_reader LOGIN PASSWORD {}').format(sql.Literal(password)))
            envfile.write_text('PGUSER=olist_reader\nPGPASSWORD='+password+'\n',encoding='utf-8')
        else:
            password=dict(line.split('=',1) for line in envfile.read_text().splitlines())['PGPASSWORD']
        conn.execute('GRANT USAGE ON SCHEMA ads TO olist_reader')
        conn.execute('GRANT SELECT ON ALL TABLES IN SCHEMA ads TO olist_reader')
        conn.execute('ALTER DEFAULT PRIVILEGES IN SCHEMA ads GRANT SELECT ON TABLES TO olist_reader')
    denied=[]
    with psycopg.connect(user='olist_reader',password=password,autocommit=True) as reader:
        reader.execute('SELECT * FROM ads.kpi_overview').fetchone()
        for table in ['ods.orders','dwd.fact_order','audit.source_file']:
            try:
                reader.execute('SELECT 1 FROM '+table+' LIMIT 1')
            except psycopg.errors.InsufficientPrivilege:
                denied.append(table)
            else:
                raise AssertionError('Unexpected reader access to '+table)
    write_json(OUT/'reader_permissions.json',{'status':'PASS','ads_select':True,'denied_tables':denied,
        'credentials':'Stored only in ignored .local/reader.env'})
    print('ADS reader provisioned; source access denied; no credentials printed')

if __name__=='__main__':
    main()
