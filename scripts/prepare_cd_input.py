"""Materialize fixed, reviewed Git inputs for the C/D integration."""
import io
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_REVISION = '25b397bf846a8e7c39bbc249e0700428e89bc0c3'
ANALYSIS_REVISION = '0e06c7f9c0eff013f84bce8e5719254174162287'
BATCH_ID = 'tencent_20261031T093102Z_366ad0a4'


def extract_revision(revision, paths, destination):
    archive_bytes = subprocess.check_output(['git','archive','--format=zip',revision,*paths],cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for entry in archive.infolist():
            target = (destination / entry.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError('Unsafe archive path')
            if entry.is_dir():
                target.mkdir(parents=True,exist_ok=True)
                continue
            data = archive.read(entry)
            if target.exists() and target.read_bytes() != data:
                raise ValueError(f'Local input modified: {target}')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)


if __name__ == '__main__':
    for revision,ref in [(DATA_REVISION,'main'),(ANALYSIS_REVISION,'refs/pull/3/head')]:
        if subprocess.run(['git','cat-file','-e',f'{revision}^{{commit}}'],cwd=ROOT,capture_output=True).returncode:
            subprocess.run(['git','fetch','origin',ref],cwd=ROOT,check=True)
    destination = ROOT / '.local/cd_input'
    extract_revision(DATA_REVISION,[f'data/tencent/{BATCH_ID}'],destination)
    paths = [f'reports/analysis/{BATCH_ID}/{name}' for name in
             ('skill_evidence.jsonl','input_provenance.json','data_issues.csv')]
    paths.append('etl/skills/dictionary.json')
    extract_revision(ANALYSIS_REVISION,paths,destination)
    print(destination)
