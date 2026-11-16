"""One synthetic, billable connectivity check; never runs news analysis."""
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import intelligence


def main():
    os.environ.setdefault('LLM_ENABLED','1')
    engine=intelligence.Engine()
    if not engine.enabled:
        print('연결 미실행: '+engine.client.missing_configuration)
        return 2
    try:
        result=engine.call('link',{'task':'연결 검사 전용 가상 입력입니다. same_event를 false로 반환하세요.'},intelligence.LINK_SCHEMA)
        if not isinstance(result,dict) or set(result)!={'same_event'} or result['same_event'] is not False:
            raise ValueError('연결 검사 JSON 불일치')
    except Exception as error:
        print('연결 검사 실패: '+type(error).__name__+(f' (HTTP {error.code})' if isinstance(error,HTTPError) else ''))
        return 1
    print(json.dumps({'provider':engine.provider,'model':engine.model,'status':'ok','usage':engine.usage()},ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
