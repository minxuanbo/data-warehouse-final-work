"""Offline contract regressions using the reviewed real batch in local storage."""
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from warehouse.validate import validate, safe_path, digest
from warehouse.load import version_action

SOURCE = Path('.local/pr1_input/data/tencent/tencent_20261031T093102Z_366ad0a4')


class ContractTests(unittest.TestCase):
    def setUp(self):
        Path(".local/tests").mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=".local/tests")
        self.root = Path(self.temp.name)/SOURCE.name
        shutil.copytree(SOURCE,self.root)

    def tearDown(self):
        self.temp.cleanup()

    def rewrite_jobs(self, change):
        p=self.root/'jobs.jsonl'
        rows=[json.loads(s) for s in p.read_text(encoding='utf-8').splitlines()]
        change(rows)
        p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8',newline='\n')
        m=json.loads((self.root/'manifest.json').read_text(encoding='utf-8'))
        for f in m['files']:
            if f['path']=='jobs.jsonl':
                f.update(bytes=p.stat().st_size,sha256=digest(p.read_bytes()),records=len(rows))
        (self.root/'manifest.json').write_text(json.dumps(m),encoding='utf-8')

    def test_real_batch_retains_pending(self):
        result=validate(self.root)
        self.assertEqual(result['summary']['jobs'],100)
        self.assertEqual(result['manifest']['acceptance_status'],'pending')

    def test_changed_bytes_rejected(self):
        with (self.root/'jobs.jsonl').open('ab') as f:f.write(b' ')
        with self.assertRaisesRegex(ValueError,'Hash/size'):validate(self.root)

    def test_duplicate_even_with_updated_hash_rejected(self):
        self.rewrite_jobs(lambda rows:rows.append(rows[0]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):validate(self.root)

    def test_numeric_long_id_rejected(self):
        self.rewrite_jobs(lambda rows:rows[0].update(source_job_id=1234567890123456789))
        with self.assertRaisesRegex(ValueError,'required string'):validate(self.root)

    def test_unzoned_time_rejected(self):
        self.rewrite_jobs(lambda rows:rows[0].update(observed_at='2026-10-31T09:32:00'))
        with self.assertRaisesRegex(ValueError,'Observation'):validate(self.root)

    def test_path_escape_rejected(self):
        for value in ('../outside','C:/outside','/outside','raw/../../outside'):
            with self.assertRaises(ValueError):safe_path(self.root,value)

    def test_missing_required_field_rejected(self):
        self.rewrite_jobs(lambda rows:rows[0].pop('requirements_raw'))
        with self.assertRaisesRegex(ValueError,'fields'):validate(self.root)


class HistoryTests(unittest.TestCase):
    def test_a_b_a_is_three_intervals(self):
        t=datetime(2026,10,31,tzinfo=timezone.utc)
        self.assertEqual(version_action(None,None,'A',t),'new')
        self.assertEqual(version_action('A',t,'B',t+timedelta(days=1)),'new')
        self.assertEqual(version_action('B',t+timedelta(days=1),'A',t+timedelta(days=2)),'new')

    def test_identical_content_reuses(self):
        t=datetime.now(timezone.utc)
        self.assertEqual(version_action('A',t,'A',t),'reuse')

    def test_out_of_order_and_tied_conflict_rejected(self):
        t=datetime.now(timezone.utc)
        for dt in (t,t-timedelta(days=1)):
            with self.assertRaises(ValueError):version_action('A',t,'B',dt)


if __name__=='__main__':unittest.main()
