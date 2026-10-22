"""Fetch EDB PostgreSQL Windows binaries into this project only."""
from pathlib import Path
import hashlib
import json
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://get.enterprisedb.com/postgresql/postgresql-17.6-1-windows-x64-binaries.zip'

def main():
    dest = ROOT/'.runtime'
    dest.mkdir(exist_ok=True)
    archive = dest/'postgresql-17.6.zip'
    if not archive.exists():
        part = archive.with_suffix('.part')
        with urllib.request.urlopen(URL, timeout=90) as r, part.open('wb') as f:
            total=0
            while chunk := r.read(4*1024*1024):
                f.write(chunk)
                total+=len(chunk)
                if total//(32*1024*1024)!=(total-len(chunk))//(32*1024*1024):
                    print(f'Downloaded {total//1024//1024} MiB',flush=True)
        with zipfile.ZipFile(part) as z:
            if z.testzip():
                raise RuntimeError('PostgreSQL archive CRC failure')
        part.replace(archive)
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            if not item.filename.startswith(('pgsql/bin/','pgsql/lib/','pgsql/share/')):
                continue
            path=(dest/item.filename).resolve()
            if not path.is_relative_to(dest.resolve()):
                raise RuntimeError('Unsafe archive path')
            if item.is_dir():
                path.mkdir(parents=True,exist_ok=True)
            else:
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(z.read(item))
    (dest/'postgres-source.json').write_text(json.dumps({'url':URL,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2),encoding='utf-8')
    print('PostgreSQL binaries ready',flush=True)

if __name__=='__main__':
    main()
