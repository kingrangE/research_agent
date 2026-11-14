"""Check actual text-role rendering; this does not measure financial accuracy."""
import argparse
import json
import os
from urllib.request import Request, urlopen


def validate_context(tokens, context):
    expected={25:'<|im_start|>',27:'<|im_end|>',9:'<|system|>',8:'<|user|>',10:'<|assistant|>'}
    if not isinstance(tokens,list) or len(tokens)<=27 or any(tokens[i]!=name for i,name in expected.items()):
        raise ValueError('A.X 역할 토큰 번호 불일치')
    if not isinstance(context,list) or any(type(i) is not int or not 0<=i<len(tokens) for i in context):
        raise ValueError('생성 문맥 토큰 형식 오류')
    roles=[context[i+1] for i,t in enumerate(context[:-1]) if t==25]
    if roles!=[9,8,10] or any(context.count(i)!=1 for i in (9,8,10)):
        raise ValueError('시스템·사용자·응답 역할 렌더링 불일치 또는 중복')


def call(path,payload):
    endpoint=os.environ.get('OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')+path
    request=Request(endpoint,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=120) as response:
        body=response.read(8_000_001)
    if len(body)>8_000_000:
        raise ValueError('모델 메타데이터 크기 제한')
    return json.loads(body)


def check(model):
    metadata=call('/api/show',{'model':model,'verbose':True})
    response=call('/api/generate',{'model':model,'system':'SYSTEM_MARKER','prompt':'USER_MARKER','stream':False,
        'options':{'num_ctx':16384,'num_predict':1,'temperature':0}})
    if response.get('done') is not True:
        raise ValueError('역할 렌더링 검사 미완료')
    validate_context(metadata.get('model_info',{}).get('tokenizer.ggml.tokens'),response.get('context'))
    print('시스템·사용자·응답 역할 토큰 확인 완료. 금융 정확도 검증은 별도입니다.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',default='research-ax4-official-template:latest')
    check(parser.parse_args().model)
