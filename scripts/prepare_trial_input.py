"""Extract the reviewed PR #1 batch without merging or duplicating it in Git."""
import io
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'f6eccadec28a4a1132c5953bbd92470c1d794348'
BATCH = 'tencent_20261031T093102Z_366ad0a4'

if __name__ == '__main__':
    result = subprocess.run(['git','cat-file','-e',f'{REVISION}^{{commit}}'],cwd=ROOT,capture_output=True)
    if result.returncode:
        subprocess.run(['git','fetch','origin','refs/pull/1/head'],cwd=ROOT,check=True)
        subprocess.run(['git','cat-file','-e',f'{REVISION}^{{commit}}'],cwd=ROOT,check=True)
    data = subprocess.check_output(['git','archive','--format=zip',REVISION,f'data/tencent/{BATCH}'],cwd=ROOT)
    destination = ROOT / '.local' / 'pr1_input'
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in archive.infolist():
            target = (destination / item.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError('Unsafe archive entry')
            if item.is_dir():
                target.mkdir(parents=True,exist_ok=True)
            else:
                content = archive.read(item)
                if target.exists() and target.read_bytes()!=content:
                    raise ValueError(f'Existing local input modified: {target}')
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(content)
    print(destination / 'data' / 'tencent' / BATCH)
