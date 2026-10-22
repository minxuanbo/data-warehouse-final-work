"""Download the public Olist archive; verify CRC and extract only expected CSVs."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
import json
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce'
PAGE = 'https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce'
EXPECTED = {
    'olist_orders_dataset.csv', 'olist_order_items_dataset.csv',
    'olist_order_payments_dataset.csv', 'olist_order_reviews_dataset.csv',
    'olist_customers_dataset.csv', 'olist_products_dataset.csv',
    'olist_sellers_dataset.csv', 'olist_geolocation_dataset.csv',
    'product_category_name_translation.csv',
}

def main():
    downloads = ROOT / 'data/downloads'
    raw = ROOT / 'data/raw'
    downloads.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    archive = downloads / 'olist.zip'
    if not archive.exists():
        part = downloads / 'olist.zip.part'
        request = urllib.request.Request(URL, headers={'User-Agent': 'OlistCourseDataAudit/1.0'})
        with urllib.request.urlopen(request, timeout=60) as response, part.open('wb') as f:
            total = 0
            while chunk := response.read(1024 * 1024):
                f.write(chunk)
                total += len(chunk)
                if total // (5 * 1024 * 1024) != (total-len(chunk)) // (5 * 1024 * 1024):
                    print(f'Downloaded {total:,} bytes', flush=True)
        if not zipfile.is_zipfile(part):
            raise RuntimeError('Download is not a ZIP; possible login or gateway response')
        with zipfile.ZipFile(part) as z:
            if z.testzip() is not None:
                raise RuntimeError('ZIP CRC verification failed')
        part.replace(archive)
    with zipfile.ZipFile(archive) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f'ZIP CRC verification failed: {bad}')
        members = [i for i in z.infolist() if not i.is_dir()]
        if {i.filename for i in members} != EXPECTED or len(members) != len(EXPECTED):
            raise RuntimeError('Archive contents differ from the nine expected flat CSV files')
        for info in members:
            target = raw / info.filename
            data = z.read(info)
            if target.exists() and target.read_bytes() != data:
                raise RuntimeError(f'Existing raw file differs; refusing overwrite: {target.name}')
            if not target.exists():
                target.write_bytes(data)
    provenance = ROOT / 'data/source.json'
    if not provenance.exists():
        provenance.write_text(json.dumps({
            'publisher': 'Olist', 'dataset': 'Brazilian E-Commerce Public Dataset by Olist',
            'source_url': PAGE, 'download_url': URL,
            'retrieved_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
            'license': 'CC BY-NC-SA 4.0',
            'license_evidence_url': 'https://www.kaggle.com/olistbr/brazilian-ecommerce/home/',
            'version': 'API latest at retrieval; numeric release version not supplied',
            'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'archive_bytes': archive.stat().st_size,
            'archive_crc_verified': True,
            'files': sorted(EXPECTED),
        }, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        previous = json.loads(provenance.read_text(encoding='utf-8'))
        if previous['archive_sha256'] != hashlib.sha256(archive.read_bytes()).hexdigest():
            raise RuntimeError('Archive differs from recorded provenance')
    print('Verified archive and extracted 9 unchanged source files', flush=True)

if __name__ == '__main__':
    main()
