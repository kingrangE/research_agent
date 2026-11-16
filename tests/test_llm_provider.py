import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import intelligence as ai
from llm_provider import Provider, NoRedirect


class ProviderTest(unittest.TestCase):
    def config(self, **env):
        with patch.dict(os.environ,env,clear=True):
            return Provider.from_env()

    def test_nvidia_default_and_key_missing_do_not_fall_back_to_local(self):
        p=self.config(LLM_ENABLED='1')
        self.assertEqual(p.name,'nvidia')
        self.assertEqual(p.model,'nvidia/nemotron-3-ultra-550b-a55b')
        self.assertFalse(p.enabled)
        self.assertEqual(p.missing_configuration,'NVIDIA_API_KEY 설정 필요')

    def test_vendor_request_formats_and_secrets(self):
        schema=ai.LINK_SCHEMA;messages=[{'role':'user','content':'return JSON'}]
        for name,key in [('nvidia','NVIDIA_API_KEY'),('openai','OPENAI_API_KEY'),('gemini','GEMINI_API_KEY'),('openai_compatible','LLM_API_KEY')]:
            p=self.config(LLM_PROVIDER=name,LLM_MODEL='chosen-model',LLM_BASE_URL='https://example.com/v1/',**{key:'secret-test-key'})
            url,body,headers=p.request('link',p.model,messages,schema,64)
            self.assertEqual(url,'https://example.com/v1/chat/completions')
            self.assertEqual(headers['Authorization'],'Bearer secret-test-key')
            self.assertFalse(body['stream'])
            self.assertEqual(body['model'],'chosen-model')
            self.assertNotIn('secret-test-key',repr(p))
            self.assertNotIn('secret-test-key',json.dumps(body))
            if name=='nvidia':
                self.assertNotIn('response_format',body)
                self.assertEqual(body['reasoning_effort'],'none')
            else:self.assertEqual(body['response_format']['json_schema']['schema'],schema)
            self.assertEqual(body['max_completion_tokens' if name=='openai' else 'max_tokens'],64)

    def test_format_and_endpoint_configuration_isolates_caches_without_resetting_usage(self):
        env={'LLM_PROVIDER':'nvidia','NVIDIA_API_KEY':'secret-a'}
        base=self.config(**env)
        rotated=self.config(**{**env,'NVIDIA_API_KEY':'secret-b'})
        self.assertEqual(base.cache_scope,rotated.cache_scope)
        for extra in ({'LLM_RESPONSE_FORMAT':'json_schema'},{'LLM_REASONING_EFFORT':'medium'}):
            changed=self.config(**{**env,**extra})
            self.assertNotEqual(base.cache_scope,changed.cache_scope)
            self.assertEqual(base.usage_scope,changed.usage_scope)
        self.assertNotEqual(base.usage_scope,self.config(**{**env,'LLM_BASE_URL':'https://other.example/v1'}).usage_scope)
        for mode in ('json_schema','json_object'):
            p=self.config(**{**env,'LLM_RESPONSE_FORMAT':mode})
            self.assertEqual(p.request('link',p.model,[],ai.LINK_SCHEMA,64)[1]['response_format']['type'],mode)

    def test_invalid_config_and_redirects_fail_closed(self):
        for env in ({'LLM_PROVIDER':'typo'},{'LLM_BASE_URL':'https://user:secret@example.com/v1'},
                    {'LLM_BASE_URL':'http://example.com/v1'},{'LLM_BASE_URL':'https://example.com/v1?key=secret'},
                    {'LLM_RESPONSE_FORMAT':'unknown'},{'LLM_TOKEN_PARAMETER':'arbitrary'},
                    {'LLM_PROVIDER':'openai_compatible'}):
            with self.assertRaises(ValueError):self.config(**env)
        with self.assertRaises(ValueError):NoRedirect().redirect_request(None,None,302,'',{},'https://other.example')

    def test_response_parser_uses_final_content_and_rejects_refusal_or_truncation(self):
        p=self.config()
        response={'choices':[{'finish_reason':'stop','message':{'content':'{"same_event":false}','reasoning_content':'private reasoning'}}]}
        self.assertEqual(json.loads(p.content(response)),{'same_event':False})
        for reason in ('length','tool_calls'):
            with self.assertRaises(ValueError):p.content({'choices':[{'finish_reason':reason,'message':{'content':'{}'}}]})
        with self.assertRaises(ValueError):p.content({'choices':[{'finish_reason':'stop','message':{'content':'{}','refusal':'no'}}]})

    def test_actual_http_exchange_does_not_retry_or_forward_credentials_on_redirect(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        from urllib.error import HTTPError
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            status=200
            def log_message(self,*args):pass
            def do_GET(self):
                calls.append(('GET',self.path));self.send_response(200);self.end_headers()
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(('POST',self.path,body,self.headers.get('Authorization')))
                self.send_response(Handler.status)
                if Handler.status==302:self.send_header('Location','/stolen')
                self.end_headers()
                self.wfile.write(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"same_event":false}'}}],'usage':{'prompt_tokens':4,'completion_tokens':9}}).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'LLM_PROVIDER':'nvidia','NVIDIA_API_KEY':'test-only','LLM_ENABLED':'1','LLM_BASE_URL':f'http://127.0.0.1:{server.server_port}/v1'},clear=True):
                engine=ai.Engine(Path(tmp)/'calls.sqlite3')
                self.assertEqual(engine.call('link',{},ai.LINK_SCHEMA),{'same_event':False})
                self.assertEqual(calls[0][1],'/v1/chat/completions')
                self.assertEqual(calls[0][2]['reasoning_effort'],'none')
                self.assertEqual(calls[0][3],'Bearer test-only')
                Handler.status=302
                with self.assertRaises(ValueError):engine.call('link',{},ai.LINK_SCHEMA)
                Handler.status=429
                with self.assertRaises(HTTPError):engine.call('link',{},ai.LINK_SCHEMA)
                self.assertEqual(len(calls),3)
                self.assertTrue(all(c[0]=='POST' for c in calls))
                self.assertEqual(engine.usage()['calls_today'],3)
                self.assertEqual(engine.usage()['input_tokens'],4)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_cloud_budget_does_not_count_local_or_legacy_and_model_change_does_not_reset_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'analysis.sqlite3'
            with patch.dict(os.environ,{'LLM_PROVIDER':'ollama','LLM_ENABLED':'1','LLM_MODEL':'local'},clear=True):local=ai.Engine(path)
            with local.db() as db:
                db.execute('INSERT INTO attempts(day,task,model,status,scope) VALUES(?,?,?,?,?)',(ai.now()[:10],'read','local','failed',local.client.usage_scope))
                db.execute('INSERT INTO attempts(day,task,model,status) VALUES(?,?,?,?)',(ai.now()[:10],'read','legacy','received'))
            env={'LLM_PROVIDER':'nvidia','NVIDIA_API_KEY':'test-only','LLM_ENABLED':'1','LLM_DAILY_CALL_LIMIT':'1'}
            with patch.dict(os.environ,env,clear=True):cloud=ai.Engine(path)
            response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"same_event":false}'}}],'usage':{'prompt_tokens':3,'completion_tokens':5}}).encode()
            with patch('intelligence.urlopen',return_value=response):self.assertEqual(cloud.call('link',{},ai.LINK_SCHEMA),{'same_event':False})
            self.assertEqual(cloud.usage()['calls_today'],1)
            self.assertEqual(cloud.usage()['legacy_calls_today'],1)
            with patch.dict(os.environ,{**env,'LLM_MODEL':'another-model'},clear=True):other=ai.Engine(path)
            self.assertNotEqual(cloud.queue.namespace,other.queue.namespace)
            with patch('intelligence.urlopen') as request:
                with self.assertRaisesRegex(ValueError,'일일'):other.call('link',{},ai.LINK_SCHEMA)
                request.assert_not_called()
