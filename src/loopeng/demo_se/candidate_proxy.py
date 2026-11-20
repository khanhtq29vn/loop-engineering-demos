"""Untrusted-candidate sandbox driver: input-only, no acceptance assertions/expected values.

The host sends {"cases": [{"name":..., "entries":...}, ...]}. Only outputs are
returned to the host; the host keeps expected results and pass/fail logic.
"""
import importlib.util
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import sys


def main():
    try:
        payload=json.loads(sys.stdin.read(100000))
        cases=payload['cases']
        if not isinstance(cases,list) or len(cases)>100:
            raise ValueError('invalid cases')
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            spec=importlib.util.spec_from_file_location('ledger',Path(sys.argv[1]))
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        outcomes=[]
        for case in cases:
            try:
                with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                    result=module.reconcile_ledger(case['entries'])
                outcomes.append({'name':case['name'],'value':result,'exception':None})
            except Exception as ex:
                outcomes.append({'name':case['name'],'value':None,'exception':type(ex).__name__})
        print(json.dumps({'outcomes':outcomes},allow_nan=False))
    except BaseException as exc:
        print(json.dumps({'error':type(exc).__name__}))

if __name__=='__main__':
    main()
