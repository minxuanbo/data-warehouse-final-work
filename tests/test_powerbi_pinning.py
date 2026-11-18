"""A saved import must survive selection of a newer analysis build."""
import unittest

from scripts.prepare_powerbi import sql_queries


class PinnedImportTests(unittest.TestCase):
    def test_all_queries_use_immutable_builds(self):
        queries = sql_queries([5, 6])
        for name, query in queries.items():
            with self.subTest(table=name):
                self.assertNotIn('current_analysis_builds', query)
                self.assertIn('build_id IN (5,6)', query)
        self.assertIn('FROM ads.cd_overview', queries['Builds'])


if __name__ == '__main__':
    unittest.main()
