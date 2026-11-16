"""Check local read APIs without issuing supplier requests or exposing quote values."""
import json
import statistics
import time
from urllib.request import urlopen


def main():
    timings=[]
    for market in ('KR','US'):
        for _ in range(10):
            started=time.perf_counter()
            with urlopen('http://127.0.0.1:8765/api/market-watch?market='+market,timeout=10) as response:
                result=json.load(response)
            timings.append(time.perf_counter()-started)
            assert result['market']==market
            assert len(result['candidates'])<=5
            for group in result['themes']:
                assert group['up']+group['down']+group['flat']==group['observed']<=group['tracked']
                if group['observed']==0:assert group['mean_percent'] is None
            for candidate in result['candidates']:
                assert candidate['market_difference_pp'] is not None
    p95=sorted(timings)[int(.95*len(timings))-1]
    print(json.dumps({'requests':len(timings),'concurrency':1,'median_seconds':statistics.median(timings),'p95_seconds':p95,'p95_goal_passed':p95<1}))


if __name__=='__main__':main()
