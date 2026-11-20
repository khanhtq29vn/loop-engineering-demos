"""Presentation stays an additive, safe read-only view of recorded evidence."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from loopeng.cli import main
from loopeng.presentation import format_event
from loopeng.report_html import build_html, load_summary, write_html
from loopeng.demo_rd.pipeline import run as run_rd
from loopeng.demo_se.pipeline import run as run_se


class PresentationTests(unittest.TestCase):
    def test_rd_report_contains_actual_metrics_and_run_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, state = run_rd(Path(tmp), backend='offline', max_attempts=5)
            path = write_html(store.directory)
            html = path.read_text(encoding='utf-8')
            self.assertIn('PREAUTHORED OFFLINE CANDIDATES', html)
            self.assertIn('0.8734', html)
            self.assertIn('0.8828', html)
            self.assertIn('SEARCH_COMPLETE', html)
            self.assertIn('not a proof of convergence', html)
            self.assertIn('Candidate validation F1', html)
            self.assertIn('Held-out evaluation', html)
            self.assertIn('Content-Security-Policy', html)
            self.assertNotIn('https://', html)
            self.assertNotIn('OPENROUTER_API_KEY', html)

    def test_se_report_shows_skipped_protected_and_failed_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = run_se(Path(tmp), backend='offline', mode='governed')
            html = write_html(store.directory).read_text(encoding='utf-8')
            self.assertIn('NOT RUN', html)
            self.assertIn('FAIL', html)
            self.assertIn('PASS', html)
            self.assertIn('ACCEPTED', html)
            self.assertIn('not every possible input', html)

    def test_feedback_only_is_not_misrepresented_as_governed_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = run_se(Path(tmp), backend='offline', mode='feedback_only')
            html = write_html(store.directory).read_text(encoding='utf-8')
            self.assertIn('did not pass the independent acceptance checks', html)
            self.assertIn('ACCEPTED', html)

    def test_unknown_proposal_provenance_must_not_claim_live(self):
        summary = dict(demo='rd', run_id='rd-example', mode='governed', status='SEARCH_COMPLETE',
                       details=dict(baseline_validation={'f1': 0.5},best_validation={'f1':0.5}),history=[])
        html = build_html(summary)
        self.assertIn('UNSPECIFIED PROPOSAL SOURCE', html)
        self.assertNotIn('PREAUTHORED OFFLINE CANDIDATES', html)
        self.assertNotIn('LIVE MODEL PROPOSALS', html)

    def test_report_escapes_model_controlled_fields(self):
        summary = dict(demo='rd', run_id='<script>alert(1)</script>', mode='governed',
                       status='SEARCH_COMPLETE', details=dict(demo_kind='LIVE_MODEL_PROPOSALS',
                       baseline_validation={'f1':0.5},best_validation={'f1':0.6},
                       stop_reason='<img src=x onerror=alert(1)>'),
                       history=[dict(attempt=1,config=dict(feature_map='<script>oops</script>'),
                           validation=dict(f1=0.6),kept=True,best_so_far_f1=0.6)])
        html = build_html(summary)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('LIVE MODEL PROPOSALS', html)

    def test_corrupt_and_oversize_summaries_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            (d/'summary.json').write_text('{bad', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_summary(d)
            (d/'summary.json').write_bytes(b' ' * 4_000_001)
            with self.assertRaises(ValueError):
                load_summary(d)

    def test_report_refuses_symlinked_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = run_rd(Path(tmp), backend='offline', max_attempts=1)
            external = Path(tmp)/'important.txt'
            external.write_text('untouched',encoding='utf-8')
            (store.directory/'report.html').symlink_to(external)
            with self.assertRaisesRegex(ValueError,'symlinked'):
                write_html(store.directory)
            self.assertEqual(external.read_text(encoding='utf-8'), 'untouched')

    def test_terminal_no_prompt_or_escape_in_metadata(self):
        line=format_event('MODEL_REQUEST_COMPLETED',dict(attempt=1,model='\x1b[31mevil',
                 input_tokens=20,output_tokens=50,cost_usd_reported=0.01))
        self.assertNotIn('\x1b',line)
        self.assertIn('USD 0.01000',line)
        self.assertNotIn('prompt',line)
        self.assertIsNone(format_event('SECRET_UNRECOGNIZED',{'key':'do-not-display'}))

    def test_terminal_skipped_verifier_result_is_distinct_from_fail(self):
        line=format_event('VERIFIER_RESULT',dict(attempt=1, public_passed=False, protected_passed=None))
        self.assertIn('acceptance=NOT RUN',line)
        self.assertIn('public=FAIL',line)

    def test_report_cli_html_generation_preserves_original_json_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = run_rd(Path(tmp), backend='offline', max_attempts=1)
            with redirect_stdout(StringIO()) as output:
                self.assertEqual(main(['report',str(store.directory),'--html']),0)
            self.assertIn('report.html',output.getvalue())
            with redirect_stdout(StringIO()) as output:
                self.assertEqual(main(['report',str(store.directory)]),0)
            obj=json.loads(output.getvalue())
            self.assertEqual(obj['demo'],'rd')

    def test_presentation_flag_from_cli_generates_report_and_follows_mode(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ,{},clear=False):
            os.environ.pop('LOOPENG_LIVE',None)
            os.environ.pop('LOOPENG_PRESENTATION',None)
            with redirect_stdout(StringIO()) as output:
                rc=main(['rd','--backend','offline','--max-attempts','1',
                         '--out',tmp,'--presentation'])
            self.assertEqual(rc,0)
            self.assertIn('EVALUATE',output.getvalue())
            self.assertIn('Visual report:',output.getvalue())
            self.assertTrue(list(Path(tmp).glob('rd-*/report.html')))

    def test_report_never_reads_events_or_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = run_se(Path(tmp), backend='offline', max_attempts=1)
            (store.directory/'events.jsonl').write_text('INVALID_JSON',encoding='utf-8')
            self.assertIn('<html',write_html(store.directory).read_text(encoding='utf-8'))

    def test_chart_rejects_invalid_nonfinite_metrics(self):
        from loopeng.report_html import _chart
        self.assertIn('Chart unavailable',_chart([dict(validation={'f1':float('nan')},
                                                    best_so_far_f1=0.8)],0.6))


if __name__ == '__main__':
    unittest.main()

class ComparisonTests(unittest.TestCase):
    def test_prepared_policy_comparison_is_factual(self):
        from loopeng.report_html import write_se_comparison
        with tempfile.TemporaryDirectory() as tmp:
            a,_ = run_se(Path(tmp),mode='feedback_only',backend='offline')
            b,_ = run_se(Path(tmp),mode='governed',backend='offline')
            html = write_se_comparison(a.directory,b.directory).read_text(encoding='utf-8')
            self.assertIn('feedback_only',html)
            self.assertIn('governed',html)
            self.assertIn('Accepted using public tests',html)
            self.assertIn('3 verified attempt(s)',html)
            self.assertIn('2 verified attempt(s)',html)
            self.assertIn('illustrative counterexample',html)

    def test_comparison_refuses_unmatched_candidate_histories(self):
        from loopeng.report_html import build_se_comparison
        a = dict(demo='se',run_id='a',mode='feedback_only',status='ACCEPTED',
                 details={'demo_kind':'PREAUTHORED_FIXTURES'},
                 history=[{'candidate_sha256':'abc','public_passed':True,'protected_passed':False}])
        b = dict(demo='se',run_id='b',mode='governed',status='ACCEPTED',
                 details={'demo_kind':'PREAUTHORED_FIXTURES'},
                 history=[{'candidate_sha256':'xyz','public_passed':True,'protected_passed':False}])
        with self.assertRaisesRegex(ValueError,'same candidate'):
            build_se_comparison(a,b)

    def test_live_source_is_not_falsely_compared_as_ablated_policy(self):
        from loopeng.report_html import build_se_comparison
        a = dict(demo='se',run_id='a',mode='feedback_only',status='ACCEPTED',
                 details={'demo_kind':'LIVE_MODEL_PROPOSALS'},
                 history=[{'candidate_sha256':'abc','public_passed':True,'protected_passed':False}])
        with self.assertRaisesRegex(ValueError,'preauthored'):
            build_se_comparison(a,a)
