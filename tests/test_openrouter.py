"""Contract tests: no actual OpenRouter credentials, network or model needed."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from loopeng.backends import OpenRouterChat, SE_SCHEMA, RD_SCHEMA, BackendError
from loopeng.demo_rd.pipeline import run as run_rd


class FakeHTTP:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode('utf-8')
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, n=None): return self.payload if n is None else self.payload[:n]


class DummyOpener:
    def __init__(self, response):
        self.response = response
        self.requests = []
    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        if isinstance(self.response, Exception): raise self.response
        return FakeHTTP(self.response)


GOOD = {'choices':[{'message':{'role':'assistant','content':json.dumps({
    'feature_map':'interaction','lr':0.08,'l2':0.01,'epochs':220})},'finish_reason':'stop'}],
    'usage':{'prompt_tokens':131,'completion_tokens':74,'cost':0.0006},
    'id':'gen-test-id','model':'provider/model'}


class OpenRouterContractTests(unittest.TestCase):
    def get_client(self, response=GOOD):
        env={'OPENROUTER_API_KEY':'test-SECRET-that-must-not-leak',
             'OPENROUTER_MODEL':'provider/model',
             'OPENROUTER_REQUIRE_ZDR':'1'}
        scope=patch.dict(os.environ,env)
        scope.start(); self.addCleanup(scope.stop)
        client=OpenRouterChat()
        opener=DummyOpener(response)
        client.opener=opener
        return client, opener

    def test_schema_auth_routing_and_usage(self):
        client,opener=self.get_client()
        data,usage=client.ask_json('instructions','synthetic dataset',RD_SCHEMA)
        self.assertEqual(data['feature_map'],'interaction')
        self.assertEqual(usage['input_tokens'],131)
        self.assertEqual(usage['cost_usd_reported'],0.0006)
        self.assertTrue(json.loads(opener.requests[0][0].data)['usage']['include'])
        request,_=opener.requests[0]
        self.assertEqual(request.full_url,'https://openrouter.ai/api/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'),'Bearer test-SECRET-that-must-not-leak')
        body=json.loads(request.data)
        self.assertTrue(body['provider']['require_parameters'])
        self.assertEqual(body['provider']['data_collection'],'deny')
        self.assertTrue(body['provider']['zdr'])
        self.assertTrue(body['response_format']['json_schema']['strict'])
        self.assertEqual(body['response_format']['json_schema']['schema'],RD_SCHEMA)
        self.assertNotIn('test-SECRET-that-must-not-leak',json.dumps(body))
        self.assertEqual(len(opener.requests),1)

    def test_missing_schema_fails_closed(self):
        client,opener=self.get_client()
        with self.assertRaises(BackendError): client.ask_json('x','y',None)
        self.assertEqual(opener.requests,[])

    def test_root_key_attack_rejected(self):
        altered = {**GOOD,'choices':[{'message':{'content':json.dumps({
            'feature_map':'linear','lr':0.1,'l2':0.1,'epochs':20,'extra':'tamper'})},
            'finish_reason':'stop'}]}
        client,_=self.get_client(altered)
        with self.assertRaisesRegex(BackendError,'root JSON schema'):
            client.ask_json('x','y',RD_SCHEMA)

    def test_incomplete_output_rejected(self):
        altered={**GOOD,'choices':[{'message':{'content':'{}'},'finish_reason':'length'}]}
        client,_=self.get_client(altered)
        with self.assertRaisesRegex(BackendError,'incomplete'):
            client.ask_json('x','y',RD_SCHEMA)

    def test_refusal_rejected(self):
        altered={**GOOD,'choices':[{'message':{'refusal':'no','content':None},'finish_reason':'stop'}]}
        client,_=self.get_client(altered)
        with self.assertRaisesRegex(BackendError,'refused'):
            client.ask_json('x','y',RD_SCHEMA)

    def test_http_error_does_not_leak_credentials_or_body(self):
        error=HTTPError('https://openrouter.ai/api/v1/chat/completions',429,
                        'bad: test-SECRET-that-must-not-leak',{},io.BytesIO(b'private prompt'))
        client,_=self.get_client(error)
        with self.assertRaises(BackendError) as result:
            client.ask_json('x','y',RD_SCHEMA)
        self.assertIn('429',str(result.exception))
        self.assertNotIn('SECRET',str(result.exception))
        self.assertNotIn('private prompt',str(result.exception))

    def test_preflight_requires_model_and_schema(self):
        client,_=self.get_client()
        def fake_get(path,payload=None):
            if path=='/key': return {'data':{'limit_remaining':5,'label':'sk-or-example'}}
            if path=='/models': return {'data':[{'id':'provider/model',
                   'supported_parameters':['structured_outputs','tools']} ]}
            raise AssertionError(path)
        client._fetch=fake_get
        report=client.preflight()
        self.assertTrue(report['advertises_structured_outputs'])
        self.assertEqual(report['limit_remaining'],5)

    def test_wrong_endpoint_fails(self):
        client,_=self.get_client()
        with self.assertRaises(BackendError): client._fetch('https://third-party.example')

    def test_rd_pipeline_live_stub_receives_only_validation_history(self):
        class Stub:
            def ask_json(self,system,prompt,schema):
                assert schema is RD_SCHEMA
                assert 'heldout F1' not in prompt
                return ({'feature_map':'interaction','lr':0.08,'l2':0.01,'epochs':220},
                        {'input_tokens':30,'output_tokens':20,'model':'test-model',
                         'generation_id':'mock-1','cost_usd_reported':0.001})
        with tempfile.TemporaryDirectory() as tmp, \
             patch('loopeng.demo_rd.pipeline.make_backend',return_value=Stub()):
            store,state=run_rd(Path(tmp),backend='openrouter',max_attempts=1)
            self.assertEqual(state['api_calls'],1)
            self.assertEqual(state['tokens_used'],50)
            self.assertEqual(state['details']['heldout_access_count'],1)
            self.assertEqual(state['details']['reported_api_cost_usd'],0.001)
            self.assertEqual(state['status'],'SEARCH_COMPLETE')
            event_data=(store.directory/'events.jsonl').read_text()
            self.assertIn('MODEL_REQUEST_STARTED',event_data)
            self.assertIn('MODEL_REQUEST_COMPLETED',event_data)

    def test_se_pipeline_live_stub_and_protected_verification(self):
        from loopeng.demo_se.pipeline import run as run_se
        from loopeng.demo_se.fixtures import CANDIDATES
        class Stub:
            i = 0
            def ask_json(self, instructions, prompt, schema):
                assert schema is SE_SCHEMA
                assert 'PROTECTED RESULT' in prompt
                assert 'protected_cases' not in prompt
                self.i += 1
                return ({'path':'ledger.py','source':CANDIDATES[self.i-1]},
                        {'input_tokens':18,'output_tokens':25,'model':'mock-model',
                         'generation_id':f'mock-{self.i}','cost_usd_reported':0.002})
        proposer=Stub()
        def fake_verify(candidate, suite, mode):
            assert mode == 'docker'
            attempt=int(candidate.stem.split('_')[-1])
            is_public = suite == 'public'
            passed=(attempt >= 2) if is_public else (attempt >= 3)
            return {'passed':passed,'tests':3,'failures':0 if passed else 1,
                    'details':[] if passed else ['test_failure']}
        with tempfile.TemporaryDirectory() as tmp, \
             patch('loopeng.demo_se.pipeline.make_backend',return_value=proposer), \
             patch('loopeng.demo_se.pipeline._verify_one',side_effect=fake_verify):
            _,state=run_se(Path(tmp),backend='openrouter',sandbox='docker',
                           mode='governed',max_attempts=3)
            self.assertEqual(state['status'],'ACCEPTED')
            self.assertEqual(state['attempts_used'],3)
            self.assertEqual(state['api_calls'],3)
            self.assertEqual([x['protected_passed'] for x in state['attempt_history']],
                             [None,False,True])
            self.assertAlmostEqual(state['details']['reported_api_cost_usd'],0.006)

    def test_failed_request_counted_before_send(self):
        class Stub:
            def ask_json(self,*a,**kw): raise BackendError('mock rate limit')
        with tempfile.TemporaryDirectory() as tmp, \
             patch('loopeng.demo_rd.pipeline.make_backend',return_value=Stub()):
            _,state=run_rd(Path(tmp),backend='openrouter',max_attempts=2)
            self.assertEqual(state['status'],'ESCALATED')
            self.assertEqual(state['api_calls'],1)
            self.assertEqual(state['attempts_used'],0)


if __name__=='__main__': unittest.main()
