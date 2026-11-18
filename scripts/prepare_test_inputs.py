"""Prepare pinned historical test fixtures; never collect data or modify SQL."""
from pathlib import Path
import runpy
from warehouse.load import ROOT

if __name__=='__main__':
    (ROOT/'.local/tests').mkdir(parents=True,exist_ok=True)
    for module in ('scripts.prepare_trial_input','scripts.prepare_cd_input','scripts.prepare_netease_input','scripts.prepare_skills_v11'):
        runpy.run_module(module,run_name='__main__')
    print('Pinned historical fixtures ready; these are separate from current tracked batch inputs.')
