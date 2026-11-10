"""Extract the accepted NetEase input by immutable Git revision."""
import subprocess
from scripts.prepare_cd_input import ROOT, extract_revision

REVISION = '0f862031ba07e5f46c3929818873dee7b9e05608'
BATCH_ID = 'netease_20261101T044527Z_157cf969'

if __name__ == '__main__':
    if subprocess.run(['git', 'cat-file', '-e', f'{REVISION}^{{commit}}'], cwd=ROOT, capture_output=True).returncode:
        subprocess.run(['git', 'fetch', 'origin', 'main'], cwd=ROOT, check=True)
    destination = ROOT / '.local/netease_input'
    extract_revision(REVISION, [f'data/netease/{BATCH_ID}'], destination)
    print(destination / 'data/netease' / BATCH_ID)
