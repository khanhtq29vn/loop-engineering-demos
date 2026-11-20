"""SE loop with offline baseline/ablation, protected tests, resume and fault injection."""
from __future__ import annotations

import ast
from dataclasses import asdict
import difflib
import importlib.resources
import json
from pathlib import Path
import platform
import sys
import time

from loopeng.backends import make_backend, BackendError, SE_SCHEMA
from loopeng.core import Budget, RunStore, InjectedInterruption, add_elapsed, sha256_file
from loopeng.demo_se.fixtures import CANDIDATES, TAMPER_PROPOSAL
from loopeng.demo_se.task import BASELINE, SPEC
from loopeng.sandbox import verify, ExecutionError


def package_file(name: str) -> Path:
    return Path(__file__).parent / name


def validate_candidate(path: str, source: str):
    # Only allow replacement of the target source file, not acceptance criteria.
    if path != 'ledger.py':
        raise ValueError('POLICY_DENIED: only ledger.py may be changed')
    if not isinstance(source, str) or len(source.encode('utf-8')) > 18000:
        raise ValueError('POLICY_DENIED: invalid or oversized source')
    parsed = ast.parse(source)
    if len(parsed.body) < 1:
        raise ValueError('Candidate is empty')
    functions = [node for node in parsed.body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != 'reconcile_ledger':
        raise ValueError('Exactly one function named reconcile_ledger is required')
    for node in parsed.body:
        if isinstance(node, ast.ImportFrom):
            if node.module != 'decimal' or node.level != 0:
                raise ValueError('Imports restricted to the decimal module')
        elif isinstance(node, ast.Import):
            if any(alias.name != 'decimal' for alias in node.names):
                raise ValueError('Imports restricted to the decimal module')
        elif isinstance(node, ast.FunctionDef):
            if node.decorator_list:
                raise ValueError('Decorators are not allowed in demo candidates')
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            pass
        else:
            raise ValueError('Disallowed top-level statement')
    # AST validation is NOT a Python sandbox. All model code must run in Docker.


def _propose(backend: str, attempt_index: int, state: dict, previous: str) -> tuple[dict, dict]:
    if backend == 'offline':
        if attempt_index >= len(CANDIDATES):
            # Exhausted prepared candidates, repeat last and stop on attempt budget.
            return {'path':'ledger.py', 'source': CANDIDATES[-1]}, {'input_tokens':0,'output_tokens':0,'model':'offline-fixture'}
        return {'path':'ledger.py', 'source':CANDIDATES[attempt_index]}, {'input_tokens':0,'output_tokens':0,'model':'offline-fixture'}
    # Only PUBLIC evidence goes to the model; protected test contents are never passed.
    public_path = package_file('tests_public.py')
    public_tests = public_path.read_text(encoding='utf-8')
    last_report = state['attempt_history'][-1].get('public_feedback', '') if state['attempt_history'] else ''
    protected_flag = state['attempt_history'][-1].get('protected_feedback', '') if state['attempt_history'] else ''
    prompt = f'''TASK CONTRACT:\n{SPEC}\nPUBLIC TESTS:\n{public_tests}\nPREVIOUS CANDIDATE:\n{previous}\nPUBLIC FEEDBACK:\n{last_report}\nPROTECTED RESULT (NO TEST DETAILS):\n{protected_flag}\nRespond with one JSON object with exactly keys "path":"ledger.py" and "source": a full Python source-file string. No markdown.'''
    client = make_backend(backend)
    return client.ask_json('You are a Python engineer. Return one JSON object only; code may use decimal, and implement reconcile_ledger.', prompt, SE_SCHEMA)


def _verify_one(candidate: Path, suite: str, mode: str):
    return verify(candidate, suite, mode)


def run(root: Path, backend: str='offline', mode: str='governed', sandbox: str='trusted_local',
        max_attempts: int=4, resume_id: str | None=None, interrupt_on: int | None=None,
        inject_tamper: bool=False, max_elapsed_seconds: float=120.0) -> tuple[RunStore, dict]:
    if backend not in ('offline', 'openrouter'):
        raise ValueError('backend must be offline or openrouter')
    if mode not in ('governed','feedback_only','single_pass'):
        raise ValueError('Unknown experiment mode')
    if backend != 'offline' and sandbox != 'docker':
        raise ValueError('SECURITY POLICY: --backend openrouter requires --sandbox docker')
    if backend == 'offline' and sandbox not in ('trusted_local','docker'):
        raise ValueError('Unknown sandbox')
    if resume_id:
        store = RunStore(root, resume_id)
        state = store.load()
        if state['demo'] != 'se' or state['status'] in ('ACCEPTED','SINGLE_PASS_COMPLETE','BUDGET_EXHAUSTED','ABORTED','ESCALATED','EXECUTION_FAILURE'):
            raise ValueError('Run is not a resumable software demo')
        if state['details']['backend'] != backend or state['mode'] != mode or state['details']['sandbox'] != sandbox:
            raise ValueError('Cannot resume a run with different backend/mode/sandbox')
        budget = Budget(**state['budget'])
        store.event('RUN_RESUMED', {'phase':state['phase']})
    else:
        budget = Budget(max_attempts=max_attempts, max_api_calls=max_attempts, max_elapsed_seconds=max_elapsed_seconds)
        store, state = RunStore.new(root, 'se', mode, budget,
            {'backend':backend,'sandbox':sandbox,'python':platform.python_version(),
             'demo_kind':'PREAUTHORED_FIXTURES' if backend=='offline' else 'LIVE_MODEL_PROPOSALS',
             'protected_test_access':'verifier_only'})
        (store.directory/'candidates').mkdir(exist_ok=True)
        (store.directory/'reports').mkdir(exist_ok=True)
        (store.directory/'patches').mkdir(exist_ok=True)
        baseline_file = store.directory/'candidates'/'ledger_baseline.py'
        baseline_file.write_text(BASELINE, encoding='utf-8')
        store.event('BASELINE_STAGED', {'sha256':sha256_file(baseline_file)})

    for kind in ('candidates','reports','patches'):
        (store.directory/kind).mkdir(exist_ok=True)

    while True:
        start = time.monotonic()
        pending = state.get('phase') == 'STAGED'
        if not pending:
            stop = budget.exhausted(state)
            if stop:
                state['status'] = 'BUDGET_EXHAUSTED'
                state['details']['stop_reason'] = stop
                store.event('STOP', {'reason':stop})
                break
            index = state['attempts_used']
            attempt = index + 1
            prev = (store.directory/'candidates'/f'ledger_attempt_{index:02d}.py') if index else (store.directory/'candidates'/'ledger_baseline.py')
            prev_text = prev.read_text(encoding='utf-8') if prev.is_file() else BASELINE
            if inject_tamper and index == 0:
                try:
                    validate_candidate(TAMPER_PROPOSAL['path'], TAMPER_PROPOSAL['content'])
                except ValueError:
                    state['status'] = 'ABORTED'
                    state['details']['stop_reason'] = 'POLICY_DENIED_TEST_TAMPERING'
                    store.event('POLICY_DENIED', {'requested_path':TAMPER_PROPOSAL['path']})
                    break
            if backend != 'offline' and state['api_calls'] >= budget.max_api_calls:
                state['status']='BUDGET_EXHAUSTED'
                state['details']['stop_reason']='max_api_calls'
                break
            if backend != 'offline':
                state['api_calls'] += 1
                store.save(state)
                store.event('MODEL_REQUEST_STARTED',{'attempt':attempt,'backend':backend})
            try:
                proposal, usage = _propose(backend, index, state, prev_text)
                if backend != 'offline':
                    state['tokens_used'] += usage['input_tokens'] + usage['output_tokens']
                    if usage.get('cost_usd_reported') is not None:
                        state['details']['reported_api_cost_usd'] = (
                            state['details'].get('reported_api_cost_usd', 0.0) + float(usage['cost_usd_reported']))
                    state['details']['last_generation_id'] = usage.get('generation_id', '')
                    store.event('MODEL_REQUEST_COMPLETED', {
                        'attempt':attempt, 'model':usage['model'],
                        'input_tokens':usage['input_tokens'],
                        'output_tokens':usage['output_tokens'],
                        'cost_usd_reported':usage.get('cost_usd_reported')})
                validate_candidate(proposal.get('path'), proposal.get('source'))
            except (ValueError, SyntaxError, BackendError) as exc:
                state['status']='ESCALATED'
                state['details']['stop_reason']='PROPOSAL_REJECTED_OR_FAILED'
                store.event('PROPOSAL_REJECTED', {'reason':type(exc).__name__})
                break
            new_path = store.directory/'candidates'/f'ledger_attempt_{attempt:02d}.py'
            new_path.write_text(proposal['source'], encoding='utf-8')
            patch_path = store.directory/'patches'/f'attempt_{attempt:02d}.diff'
            patch_path.write_text(''.join(difflib.unified_diff(
                prev_text.splitlines(keepends=True), proposal['source'].splitlines(keepends=True),
                fromfile='ledger_previous.py',tofile='ledger.py')),
                encoding='utf-8')
            state['attempts_used'] = attempt
            state['current_candidate'] = new_path.name
            state['staged_sha256'] = sha256_file(new_path)
            state['phase'] = 'STAGED'
            state['status'] = 'RUNNING'
            store.save(state)
            store.event('CANDIDATE_STAGED', {'attempt':attempt,'candidate_sha256':sha256_file(new_path),
                                             'patch':patch_path.name,'proposer':usage['model']})
            if interrupt_on == attempt:
                store.event('INJECTED_INTERRUPTION', {'attempt':attempt,'checkpoint':'candidate_staged'})
                raise InjectedInterruption(f'Injected interruption after candidate {attempt} staged; resume run_id={state["run_id"]}')
        attempt = state['attempts_used']
        candidate = store.directory/'candidates'/f'ledger_attempt_{attempt:02d}.py'
        if not candidate.is_file():
            state['status']='ESCALATED'
            state['details']['stop_reason']='MISSING_STAGED_CANDIDATE'
            store.event('RECONCILIATION_REQUIRED', {'attempt':attempt})
            break
        # Never execute a candidate that changed after its recorded checkpoint.
        actual_hash = sha256_file(candidate)
        if actual_hash != state.get('staged_sha256'):
            state['status'] = 'ESCALATED'
            state['details']['stop_reason'] = 'CANDIDATE_INTEGRITY_MISMATCH'
            store.event('RECONCILIATION_REQUIRED', {'attempt': attempt, 'reason': 'checksum_mismatch'})
            break
        # Trusted-local execution is permitted ONLY for immutable reference fixtures.
        if sandbox == 'trusted_local' and (
            backend != 'offline'
            or attempt > len(CANDIDATES)
            or candidate.read_text(encoding='utf-8') != CANDIDATES[attempt-1]
        ):
            state['status'] = 'ABORTED'
            state['details']['stop_reason'] = 'TRUSTED_LOCAL_FIXTURE_MISMATCH'
            store.event('POLICY_DENIED', {'attempt': attempt, 'reason': 'untrusted_source'})
            break
        try:
            public = _verify_one(candidate, 'public', sandbox)
            protected = (_verify_one(candidate, 'acceptance', sandbox)
                         if public['passed'] else None)
        except ExecutionError as exc:
            state['status']='EXECUTION_FAILURE'
            state['details']['stop_reason']=str(exc)
            store.event('RUNTIME_FAILURE', {'reason':str(exc)})
            break
        report = {'public':public, 'protected':protected, 'candidate_sha256':sha256_file(candidate)}
        (store.directory/'reports'/f'attempt_{attempt:02d}.json').write_text(
            json.dumps(report,indent=2)+'\n', encoding='utf-8')
        # Protected test details are never included in the next model prompt.
        protected_ok = bool(protected and protected['passed'])
        public_ok = bool(public['passed'])
        record = {
            'attempt':attempt,
            'public_passed':public_ok,
            'public_tests':public['tests'],
            'protected_passed':protected_ok if protected is not None else None,
            'protected_tests':protected['tests'] if protected else None,
            'candidate_sha256':sha256_file(candidate),
            'public_feedback':'; '.join(public.get('details',[]))[:500],
            'protected_feedback':('protected criteria failed; details withheld'
                                 if protected is not None and not protected_ok else 'not supplied'),
        }
        state['attempt_history'].append(record)
        state['phase'] = 'IDLE'
        add_elapsed(state, start)
        store.event('VERIFIER_RESULT', {'attempt':attempt,'public_passed':public_ok,
                                        'protected_passed':record['protected_passed']})
        if mode == 'single_pass':
            state['status'] = 'SINGLE_PASS_COMPLETE'
            state['details']['accepted_using_public_only'] = public_ok
            state['details']['posthoc_protected_audit_passed'] = protected_ok
        elif mode == 'feedback_only' and public_ok:
            state['status'] = 'ACCEPTED'
            state['details']['accepted_using_public_only'] = True
            state['details']['posthoc_protected_audit_passed'] = protected_ok
        elif mode == 'governed' and public_ok and protected_ok:
            state['status'] = 'ACCEPTED'
            state['best_candidate'] = candidate.name
            state['details']['accepted_using_public_only'] = False
            state['details']['posthoc_protected_audit_passed'] = True
        else:
            state['status'] = 'RUNNING'
        store.save(state)
        if state['status'] != 'RUNNING':
            break
    store.save(state)
    store.event('RUN_TERMINAL', {'status':state['status'], 'attempts_used':state['attempts_used']})
    store.export_summary(state)
    return store, state
