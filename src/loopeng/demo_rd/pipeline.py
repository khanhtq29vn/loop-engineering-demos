"""Bounded validation search with held-out evaluation only after selection."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import platform
import time

from loopeng.backends import make_backend, BackendError, RD_SCHEMA
from loopeng.core import Budget, RunStore, InjectedInterruption, add_elapsed, write_json_atomic
from loopeng.demo_rd.model import (
    Config, BASELINE, PREAUTHORED_HYPOTHESES, make_dataset, train, evaluate,
)
from loopeng.demo_rd.visualize import write_trajectory


def _propose(backend: str, index: int, state: dict) -> tuple[Config, dict]:
    if backend == 'offline':
        config=PREAUTHORED_HYPOTHESES[min(index,len(PREAUTHORED_HYPOTHESES)-1)]
        return config, {'input_tokens':0,'output_tokens':0,'model':'offline-preauthored-hypothesis'}
    history = [
        {'attempt':h['attempt'],'configuration':h['config'],
         'validation_f1':h['validation']['f1'],'accepted':h['kept']}
        for h in state['attempt_history']
    ]
    prompt = (
        'Objective: maximize binary-classification validation F1 on a fixed synthetic data split. '
        'Choose a configuration from allowed feature maps (linear, interaction, quadratic), '
        'lr between 0.00001 and 0.5, l2 between 0 and 2, epochs integer 5 to 500. '
        'Data has an interaction component; sample size is modest. '
        'Return exactly JSON keys feature_map, lr, l2, epochs. '
        'DO NOT request held-out metrics or data. '
        f'Baseline validation F1: {state["details"]["baseline_validation"]["f1"]}. '
        f'History: {json.dumps(history)}'
    )
    obj, usage = make_backend(backend).ask_json('Research configuration proposer. Output one valid JSON object, no prose.',prompt, RD_SCHEMA)
    return Config.parse(obj),usage


def run(root: Path, backend: str='offline', mode: str='governed', seed: int=2026,
        max_attempts: int=5, max_elapsed_seconds: float=120.0,
        resume_id: str|None=None, interrupt_on: int|None=None) -> tuple[RunStore,dict]:
    if backend not in ('offline','openrouter'):
        raise ValueError('Unknown backend')
    if mode not in ('governed','single_pass'):
        raise ValueError('Unknown mode')
    data=make_dataset(seed)
    if resume_id:
        store=RunStore(root,resume_id)
        state=store.load()
        if state['demo']!='rd' or state['status']!='RUNNING':
            raise ValueError('Run is not a resumable research demo')
        if state['details']['seed']!=seed or state['details']['backend']!=backend or state['mode']!=mode:
            raise ValueError('Resume must retain seed, backend and mode')
        if state['details']['dataset_sha256']!=data['hash']:
            raise ValueError('Reconstructed dataset hash mismatch; aborting recovery')
        budget=Budget(**state['budget'])
        store.event('RUN_RESUMED',{'phase':state['phase']})
    else:
        budget=Budget(max_attempts=max_attempts,max_api_calls=max_attempts,max_elapsed_seconds=max_elapsed_seconds)
        baseline_model=train(BASELINE,data['sets']['train'])
        baseline_validation=evaluate(baseline_model,data['sets']['validation'])
        store,state=RunStore.new(root,'rd',mode,budget,{
            'backend':backend,
            'seed':seed,
            'python':platform.python_version(),
            'dataset_sha256':data['hash'],
            'split_sizes':data['counts'],
            'baseline_config':asdict(BASELINE),
            'baseline_validation':baseline_validation,
            'best_validation':baseline_validation,
            'best_config':asdict(BASELINE),
            'heldout_access_count':0,
            'demo_kind':'PREAUTHORED_HYPOTHESES' if backend=='offline' else 'LIVE_MODEL_PROPOSALS',
            'selection_rule':'strict improvement in validation F1; heldout is NOT used in search',
        })
        store.event('BASELINE_VALIDATED', {'validation_f1':baseline_validation['f1'], 'dataset_sha256':data['hash']})

    finish_reason=None
    while True:
        start=time.monotonic()
        if state['phase']!='STAGED':
            stop=budget.exhausted(state)
            if stop:
                finish_reason=stop
                break
            if mode=='single_pass' and state['attempts_used']>=1:
                finish_reason='single_pass_limit'
                break
            attempt=state['attempts_used']+1
            if backend!='offline' and state['api_calls']>=budget.max_api_calls:
                finish_reason='max_api_calls'
                break
            if backend != 'offline':
                state['api_calls'] += 1
                store.save(state)
                store.event('MODEL_REQUEST_STARTED',{'attempt':attempt,'backend':backend})
            try:
                config,usage=_propose(backend,attempt-1,state)
            except (ValueError,BackendError) as exc:
                state['status']='ESCALATED'
                state['details']['stop_reason']='PROPOSAL_REJECTED_OR_FAILED'
                store.event('PROPOSAL_REJECTED',{'type':type(exc).__name__})
                break
            if backend!='offline':
                state['tokens_used']+=usage['input_tokens']+usage['output_tokens']
                if usage.get('cost_usd_reported') is not None:
                    state['details']['reported_api_cost_usd'] = (
                        state['details'].get('reported_api_cost_usd', 0.0) + float(usage['cost_usd_reported']))
                state['details']['last_generation_id'] = usage.get('generation_id', '')
                store.event('MODEL_REQUEST_COMPLETED', {
                    'attempt':attempt,'model':usage['model'],
                    'input_tokens':usage['input_tokens'],
                    'output_tokens':usage['output_tokens'],
                    'cost_usd_reported':usage.get('cost_usd_reported')})
            state['attempts_used']=attempt
            state['phase']='STAGED'
            state['current_candidate']=asdict(config)
            store.save(state)
            store.event('HYPOTHESIS_STAGED',{'attempt':attempt,'configuration':asdict(config),'proposer':usage['model']})
            if interrupt_on==attempt:
                store.event('INJECTED_INTERRUPTION', {'attempt':attempt,'checkpoint':'hypothesis_staged'})
                raise InjectedInterruption(f'Injected interruption after research hypothesis {attempt} staged; resume run_id={state["run_id"]}')
        config=Config.parse(state['current_candidate'])
        model=train(config,data['sets']['train'])
        val=evaluate(model,data['sets']['validation'])
        prev_best=state['details']['best_validation']['f1']
        kept = val['f1'] > prev_best + 1e-9
        if kept:
            state['details']['best_validation']=val
            state['details']['best_config']=asdict(config)
        record={'attempt':state['attempts_used'],'config':asdict(config),'validation':val,
                'kept':kept,'best_so_far_f1':state['details']['best_validation']['f1']}
        state['attempt_history'].append(record)
        state['phase']='IDLE'
        state['current_candidate']=None
        add_elapsed(state,start)
        store.event('EXPERIMENT_EVALUATED',record)
        store.save(state)
    if state['status']=='RUNNING':
        # The held-out split is accessed exactly here, after configuration selection.
        baseline_model=train(BASELINE,data['sets']['train'])
        best_config=Config.parse(state['details']['best_config'])
        best_model=train(best_config,data['sets']['train'])
        state['details']['heldout_access_count'] += 1
        state['details']['heldout_report']={
            'baseline':evaluate(baseline_model,data['sets']['heldout']),
            'selected':evaluate(best_model,data['sets']['heldout']),
            'selection_based_on':'validation_only',
            'interpretation':'One synthetic seed is illustrative, not evidence of general superiority',
        }
        state['status']='SEARCH_COMPLETE'
        state['details']['stop_reason']=finish_reason or 'requested_limit'
        store.event('HELDOUT_EVALUATED_ONCE',{'heldout_report':state['details']['heldout_report']})
    state['elapsed_seconds']+=0.0
    store.save(state)
    store.event('RUN_TERMINAL',{'status':state['status'],'reason':state['details'].get('stop_reason')})
    store.export_summary(state)
    if state['attempt_history']:
        write_trajectory(store.directory,state['attempt_history'],state['details']['baseline_validation']['f1'])
    write_json_atomic(store.directory/'experiment_manifest.json',{
        'dataset_sha256':data['hash'], 'seed':seed, 'split_sizes':data['counts'],
        'model_family':'full-batch logistic regression implemented in Python stdlib',
        'train_only_preprocessing':True,
        'heldout_access_count':state['details']['heldout_access_count'],
        'disclosure':'Offline hypotheses are authored; this is NOT an autonomous discovery result',
    })
    return store,state
