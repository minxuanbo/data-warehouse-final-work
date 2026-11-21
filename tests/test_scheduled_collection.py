"""Offline scheduling guards; no real collection is started by these tests."""
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import scheduled_collection as scheduled


class ScheduledCollectionTests(unittest.TestCase):
    def test_configuration_rejects_automatic_approval_and_scope_shrink(self):
        original=scheduled.configuration()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'warehouse').mkdir()
            for mutation in ({'automatic_acceptance':True},{'automatic_publication':True},
                             {'sources':['tencent']},{'max_pages':501}):
                config={**original,**mutation}
                (root/'warehouse/collection_schedule.json').write_text(json.dumps(config))
                with patch.object(scheduled,'ROOT',root):
                    with self.assertRaises(ValueError):scheduled.configuration()

    def test_check_makes_no_network_request_or_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'check.json'
            with (patch('requests.sessions.Session.request',side_effect=AssertionError('Network forbidden')),
                  patch('collectors.daily.Daily',side_effect=AssertionError('Collection forbidden'))):
                self.assertEqual(scheduled.check(output),0)
            result=json.loads(output.read_text(encoding='utf-8'))
            self.assertFalse(result['collection_started'])
            self.assertEqual(result['network_requests'],0)

    @unittest.skipUnless(os.name=='nt','Native Windows file lock')
    def test_existing_actual_day_marker_prevents_duplicate_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            local=Path(tmp);day=datetime.now(scheduled.BEIJING).strftime('%Y%m%d')
            (local/'days').mkdir();(local/'days'/(day+'.json')).write_text('{}')
            with patch.object(scheduled,'LOCAL',local),patch('subprocess.Popen',side_effect=AssertionError('Duplicate launch')):
                self.assertEqual(scheduled.run(),0)


if __name__=='__main__':unittest.main()
