"""Current fixed pilot inputs; historical v1.1 fixtures keep their own entry point."""
import json
from warehouse.load import ROOT


def input_paths():
    config=json.loads((ROOT/'warehouse/pipeline.json').read_text(encoding='utf-8'))
    for item in config['inputs']:
        batch=ROOT/item['batch_path']
        source=json.loads((batch/'manifest.json').read_text(encoding='utf-8'))['source']
        yield source,batch,ROOT/item['analysis_path'],ROOT/item['dictionary_path']
