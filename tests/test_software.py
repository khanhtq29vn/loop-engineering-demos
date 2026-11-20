from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from loopeng.demo_se.pipeline import run,validate_candidate,package_file
from loopeng.demo_se.fixtures import CANDIDATES
from loopeng.core import InjectedInterruption
from loopeng.sandbox import verify

class SoftwareTests(unittest.TestCase):
    def test_reference_governed_acceptance(self):
        with TemporaryDirectory() as root:
            _,state=run(Path(root),max_attempts=4)
            self.assertEqual(state['status'],'ACCEPTED')
            self.assertEqual(state['attempts_used'],3)
            self.assertEqual([(a['public_passed'],a['protected_passed']) for a in state['attempt_history']],
                             [(False,None),(True,False),(True,True)])
            self.assertTrue(state['best_candidate'].startswith('ledger_attempt_'))
    def test_feedback_only_false_acceptance(self):
        with TemporaryDirectory() as root:
            _,state=run(Path(root),mode='feedback_only')
            self.assertEqual(state['status'],'ACCEPTED')
            self.assertEqual(state['attempts_used'],2)
            self.assertTrue(state['details']['accepted_using_public_only'])
            self.assertFalse(state['details']['posthoc_protected_audit_passed'])
    def test_single_pass_fails(self):
        with TemporaryDirectory() as root:
            _,state=run(Path(root),mode='single_pass')
            self.assertEqual(state['attempts_used'],1)
            self.assertEqual(state['status'],'SINGLE_PASS_COMPLETE')
            self.assertFalse(state['details']['accepted_using_public_only'])
    def test_circuit_breaker(self):
        with TemporaryDirectory() as root:
            _,state=run(Path(root),max_attempts=2)
            self.assertEqual(state['status'],'BUDGET_EXHAUSTED')
            self.assertEqual(state['attempts_used'],2)
    def test_tamper_blocked(self):
        with TemporaryDirectory() as root:
            _,state=run(Path(root),inject_tamper=True)
            self.assertEqual(state['status'],'ABORTED')
            self.assertEqual(state['attempts_used'],0)
            self.assertEqual(state['details']['stop_reason'],'POLICY_DENIED_TEST_TAMPERING')
    def test_resume_after_staging(self):
        with TemporaryDirectory() as root:
            root=Path(root)
            try:
                run(root,interrupt_on=2)
            except InjectedInterruption:
                pass
            else:
                self.fail('Expected injected interruption')
            items=list(root.glob('se-*/state.json'))
            self.assertEqual(len(items),1)
            run_id=items[0].parent.name
            store,state=run(root,resume_id=run_id)
            self.assertEqual(state['status'],'ACCEPTED')
            self.assertEqual([h['attempt'] for h in state['attempt_history']],[1,2,3])
            self.assertEqual(sum('INJECTED_INTERRUPTION' in s for s in store.events_path.read_text().splitlines()),1)
    def test_resume_terminal_rejected(self):
        with TemporaryDirectory() as root:
            store,state=run(Path(root))
            with self.assertRaises(ValueError):run(Path(root),resume_id=state['run_id'])
    def test_live_model_requires_docker(self):
        with TemporaryDirectory() as root:
            with self.assertRaises(ValueError): run(Path(root),backend='openrouter',sandbox='trusted_local')
    def test_path_and_top_level_policy(self):
        with self.assertRaisesRegex(ValueError,'POLICY_DENIED'):validate_candidate('tests_protected.py','x=1')
        with self.assertRaises(ValueError):validate_candidate('ledger.py','import os\ndef reconcile_ledger(e):return {}')
        with self.assertRaises(ValueError):validate_candidate('ledger.py','__import__("os")\ndef reconcile_ledger(e):return {}')
        validate_candidate('ledger.py',CANDIDATES[2])
    def test_hidden_criteria_and_public_are_different(self):
        with TemporaryDirectory() as root:
            f=Path(root)/'ledger.py'
            f.write_text(CANDIDATES[1])
            public=verify(f,'public','trusted_local')
            protected=verify(f,'acceptance','trusted_local')
            self.assertTrue(public['passed'])
            self.assertFalse(protected['passed'])
            self.assertEqual(public['evaluation_boundary'],'expected_answers_compared_on_host')
