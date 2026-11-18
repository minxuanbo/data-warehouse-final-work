import copy
import json
import unittest
from pathlib import Path
from scripts.powerbi_contract import validate_model,fix_model


class AnalysisModelTests(unittest.TestCase):
    def setUp(self):
        self.model=json.loads(Path('dashboards/powerbi/Recruitment.SemanticModel/model.bim').read_text(encoding='utf-8'))

    def test_current_model_has_only_explicit_identity_relationships(self):
        self.assertEqual(validate_model(self.model)['status'],'passed')

    def test_repeated_unchanged_body_cannot_be_used_as_unique_relationship_key(self):
        # Same real-world identity may appear on multiple dates with unchanged text.
        m=copy.deepcopy(self.model)
        m['model']['relationships'].append({'fromTable':'SnapshotJobs','fromColumn':'content_json',
            'toTable':'Jobs','toColumn':'content_json','crossFilteringBehavior':'bothDirections'})
        with self.assertRaisesRegex(ValueError,'Unexpected'):validate_model(m)
        self.assertEqual(validate_model(fix_model(m))['status'],'passed')

    def test_source_and_standard_categories_are_separate(self):
        tables={t['name']:t for t in self.model['model']['tables']}
        self.assertIn('source_category_group',{c['name'] for c in tables['Jobs']['columns']})
        self.assertIn('category_group',{c['name'] for c in tables['SnapshotJobs']['columns']})


if __name__=='__main__':unittest.main()
