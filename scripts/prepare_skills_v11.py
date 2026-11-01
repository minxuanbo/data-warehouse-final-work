"""Pin the source of the two-source skills-body-1.1 input."""
import subprocess
from scripts.prepare_cd_input import ROOT, extract_revision

REVISION = '98eb8a2b91a17ab1b33fef4b814977a241317d38'
if __name__ == '__main__':
    if subprocess.run(['git','cat-file','-e',f'{REVISION}^{{commit}}'],cwd=ROOT,capture_output=True).returncode:
        subprocess.run(['git','fetch','origin','refs/pull/3/head'],cwd=ROOT,check=True)
    files = ['etl/skills/dictionary.json']
    for batch in ('tencent_20261031T093102Z_366ad0a4','netease_20261101T044527Z_157cf969'):
        files.extend(f'reports/analysis/{batch}/v1.1/{name}' for name in
                     ('skill_evidence.jsonl','input_provenance.json','reconciliation.json','data_issues.jsonl'))
    extract_revision(REVISION,files,ROOT/'.local/skills_v11')
    print(ROOT/'.local/skills_v11')
