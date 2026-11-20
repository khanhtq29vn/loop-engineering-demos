from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from loopeng.core import Budget, RunStore, write_json_atomic

class CoreTests(unittest.TestCase):
    def test_budget_limits(self):
        b=Budget(max_attempts=3,max_elapsed_seconds=1,max_api_calls=2,max_recorded_tokens=10)
        state={'attempts_used':3,'elapsed_seconds':0,'api_calls':0,'tokens_used':0}
        self.assertEqual(b.exhausted(state),'max_attempts')
        state['attempts_used']=0; state['elapsed_seconds']=2
        self.assertEqual(b.exhausted(state),'max_elapsed_seconds')
    def test_bad_budget_rejected(self):
        with self.assertRaises(ValueError): Budget(max_attempts=0)
        with self.assertRaises(ValueError): Budget(max_elapsed_seconds=0)
    def test_runid_sanitized(self):
        with TemporaryDirectory() as p:
            for bad in ('../oops','x/y','','x\\y'):
                with self.assertRaises(ValueError): RunStore(Path(p),bad)
    def test_atomic_checkpoint_and_journal(self):
        with TemporaryDirectory() as p:
            store,state=RunStore.new(Path(p),'test','governed',Budget(),{})
            state['attempts_used']=2
            store.save(state)
            store.event('OBSERVED',{'i':2})
            self.assertEqual(store.load()['attempts_used'],2)
            self.assertEqual(json.loads(store.events_path.read_text().splitlines()[-1])['event'],'OBSERVED')
            self.assertEqual(len(list(store.directory.glob('*.tmp*'))),0)
