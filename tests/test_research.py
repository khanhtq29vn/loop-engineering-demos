from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from loopeng.demo_rd.pipeline import run
from loopeng.demo_rd.model import make_dataset, Config, BASELINE, train, evaluate
from loopeng.core import InjectedInterruption

class ResearchTests(unittest.TestCase):
    def test_dataset_reproducibility(self):
        self.assertEqual(make_dataset(2026)['hash'],make_dataset(2026)['hash'])
        self.assertNotEqual(make_dataset(2026)['hash'],make_dataset(2027)['hash'])
        counts=make_dataset()['counts']
        self.assertEqual(sum(counts.values()),720)
    def test_train_only_normalization(self):
        data=make_dataset()
        model=train(BASELINE,data['sets']['train'])
        self.assertEqual(len(model['center']),2)
        self.assertEqual(evaluate(model,data['sets']['validation'])['n'],counts_or_default(data,'validation'))
    def test_config_restrictions(self):
        with self.assertRaises(ValueError):Config.parse({'feature_map':'os.system','lr':0.1,'l2':0.0,'epochs':100})
        with self.assertRaises(ValueError):Config.parse({'feature_map':'linear','lr':0.1,'l2':0.0,'epochs':True})
        with self.assertRaises(ValueError):Config.parse({'feature_map':'linear','lr':float('nan'),'l2':0.0,'epochs':100})
    def test_governed_research_and_holdout(self):
        with TemporaryDirectory() as root:
            store,state=run(Path(root))
            self.assertEqual(state['status'],'SEARCH_COMPLETE')
            self.assertEqual(state['attempts_used'],5)
            self.assertEqual(state['details']['heldout_access_count'],1)
            self.assertTrue(state['details']['best_validation']['f1']>=state['details']['baseline_validation']['f1'])
            self.assertTrue(any(not h['kept'] for h in state['attempt_history']))
            self.assertTrue((store.directory/'trajectory.svg').exists())
            self.assertTrue((store.directory/'trajectory.csv').exists())
            self.assertEqual([h['best_so_far_f1'] for h in state['attempt_history']],
                             sorted(h['best_so_far_f1'] for h in state['attempt_history']))
    def test_single_pass(self):
        with TemporaryDirectory() as root:
            _,state=run(Path(root),mode='single_pass')
            self.assertEqual(state['attempts_used'],1)
            self.assertEqual(state['details']['heldout_access_count'],1)
            self.assertEqual(state['details']['stop_reason'],'single_pass_limit')
    def test_research_resume_exactly_once_holdout(self):
        with TemporaryDirectory() as root:
            root=Path(root)
            with self.assertRaises(InjectedInterruption):run(root,interrupt_on=2)
            run_id=next(root.glob('rd-*/state.json')).parent.name
            _,state=run(root,resume_id=run_id)
            self.assertEqual([h['attempt'] for h in state['attempt_history']],[1,2,3,4,5])
            self.assertEqual(state['details']['heldout_access_count'],1)
            with self.assertRaises(ValueError):run(root,resume_id=run_id)
    def test_budget_stop(self):
        with TemporaryDirectory() as root:
            _,state=run(Path(root),max_attempts=2)
            self.assertEqual(state['attempts_used'],2)
            self.assertEqual(state['details']['stop_reason'],'max_attempts')
    def test_deterministic_metrics(self):
        with TemporaryDirectory() as root:
            _,a=run(Path(root)); _,b=run(Path(root))
            self.assertEqual(a['details']['best_validation'],b['details']['best_validation'])
            self.assertEqual(a['details']['heldout_report'],b['details']['heldout_report'])

def counts_or_default(data,part):return data['counts'][part]
