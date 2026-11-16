"""Provider wire formats; domain prompts and evidence checks stay in intelligence."""
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

PRESETS = {
    'nvidia': ('https://integrate.api.nvidia.com/v1', 'NVIDIA_API_KEY', 'nvidia/nemotron-3-ultra-550b-a55b'),
    'openai': ('https://api.openai.com/v1', 'OPENAI_API_KEY', ''),
    'gemini': ('https://generativelanguage.googleapis.com/v1beta/openai', 'GEMINI_API_KEY', 'gemini-3.5-flash-lite'),
    'openai_compatible': ('', 'LLM_API_KEY', ''),
    'ollama': ('http://127.0.0.1:11434', '', 'ax4-light:latest'),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('LLM API 리다이렉트는 허용하지 않습니다')


open_request = build_opener(NoRedirect()).open


@dataclass(frozen=True)
class Provider:
    name: str
    model: str
    base_url: str
    key: str = field(repr=False)
    response_format: str = 'json_schema'
    token_parameter: str = 'max_tokens'
    reasoning_effort: str = ''

    @classmethod
    def from_env(cls):
        name=os.environ.get('LLM_PROVIDER') or 'nvidia'
        if name not in PRESETS:
            raise ValueError('지원하지 않는 LLM_PROVIDER')
        base,key_env,model=PRESETS[name]
        base=(os.environ.get('OLLAMA_URL',base) if name=='ollama' else os.environ.get('LLM_BASE_URL') or base).rstrip('/')
        parsed=urlsplit(base)
        if (not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.scheme not in ('https','http')
                or (parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1','::1','host.docker.internal'))):
            raise ValueError('LLM API 주소는 자격 증명 없는 HTTPS 또는 로컬 HTTP 주소여야 합니다')
        mode='json_schema' if name=='ollama' else os.environ.get('LLM_RESPONSE_FORMAT') or ('prompt' if name=='nvidia' else 'json_schema')
        token=os.environ.get('LLM_TOKEN_PARAMETER') or ('max_completion_tokens' if name=='openai' else 'max_tokens')
        effort=os.environ.get('LLM_REASONING_EFFORT') or ('none' if name=='nvidia' else '')
        if mode not in ('prompt','json_schema','json_object') or token not in ('max_tokens','max_completion_tokens'):
            raise ValueError('LLM 출력 형식 또는 토큰 매개변수 설정 오류')
        if effort not in ('','none','minimal','low','medium','high'):
            raise ValueError('LLM 추론 설정 오류')
        return cls(name,os.environ.get('LLM_MODEL') or model,base,os.environ.get(key_env,'') if key_env else '',mode,token,effort)

    @property
    def enabled(self):
        return os.environ.get('LLM_ENABLED')=='1' and bool(self.model) and (self.name=='ollama' or bool(self.key))

    @property
    def usage_scope(self):
        return sha256(json.dumps([self.name,self.base_url]).encode()).hexdigest()

    @property
    def cache_scope(self):
        return sha256(json.dumps([self.name,self.base_url,self.response_format,self.token_parameter,self.reasoning_effort]).encode()).hexdigest()

    @property
    def missing_configuration(self):
        if not self.model:return 'LLM_MODEL 설정 필요'
        if self.name!='ollama' and not self.key:return PRESETS[self.name][1]+' 설정 필요'
        return 'LLM_ENABLED=1 설정 필요'

    def request(self, task, model, messages, output_schema, max_tokens):
        if self.name=='ollama':
            return self.base_url+'/api/chat', {'model':model,'messages':messages,'stream':False,'format':output_schema,
                'options':{'temperature':0,'num_ctx':16384,'num_predict':max_tokens}}, {'Content-Type':'application/json'}
        body={'model':model,'messages':messages,'stream':False,self.token_parameter:max_tokens}
        if self.response_format=='json_schema':
            body['response_format']={'type':'json_schema','json_schema':{'name':task,'strict':True,'schema':output_schema}}
        elif self.response_format=='json_object':
            body['response_format']={'type':'json_object'}
        if self.reasoning_effort:body['reasoning_effort']=self.reasoning_effort
        return self.base_url+'/chat/completions',body,{'Content-Type':'application/json','Authorization':'Bearer '+self.key}

    def usage(self, response):
        if self.name=='ollama':
            return {'prompt_tokens':response.get('prompt_eval_count',0),'completion_tokens':response.get('eval_count',0)}
        return response.get('usage') or {}

    def content(self, response):
        if self.name=='ollama':
            complete=response.get('done') is True and response.get('done_reason')=='stop'
            content=response.get('message',{}).get('content','')
        else:
            choice=response['choices'][0];message=choice['message']
            complete=choice.get('finish_reason')=='stop' and not message.get('refusal')
            content=message.get('content','')
        if not complete:raise ValueError('모델 응답 미완료·거절')
        return content
