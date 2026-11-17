"""Independent content probes of this synthetic target during native load."""
from datetime import datetime
from hashlib import sha256
import argparse
import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch-pid',type=int,required=True);parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();root=args.directory/'target';output=args.directory/'content-probes.jsonl'
    timeline=args.directory/'fault-run/faults-100-12m/faults.jsonl'
    codes=[str(100000+i) for i in range(4)]
    with output.open('x',buffering=1) as log:
        while subprocess.run(['kill','-0',str(args.watch_pid)],capture_output=True).returncode==0:
            started=time.time();state=json.loads((root/'fault.json').read_text()) if (root/'fault.json').exists() else {}
            record={'at':started,'fault_before':state,'quotes':{}}
            events=[json.loads(line) for line in timeline.read_text().splitlines()] if timeline.exists() else []
            fault_start=next((e['at'] for e in reversed(events) if e['kind']==state.get('provider') and e['event']=='start'),None)
            try:
                with urlopen('http://127.0.0.1:19227/api/quotes?codes='+','.join(codes),timeout=3) as response:
                    payload=json.load(response)
                for code in codes:
                    quote=payload['quotes'][code];price=100+int(sha256(code.encode()).hexdigest()[:4],16)%100
                    record['quotes'][code]={'status':quote.get('status'),'code_matches':quote.get('code')==code,
                        'price_matches':quote.get('price')==price,'fetched_at':quote.get('fetched_at'),
                        'false_normal':bool(fault_start and quote.get('status')=='ok' and
                            datetime.fromisoformat(quote['fetched_at']).timestamp()>fault_start)}
            except Exception as error:record['error']=type(error).__name__
            record['fault_after']=json.loads((root/'fault.json').read_text()) if (root/'fault.json').exists() else {}
            record['seconds']=time.time()-started;log.write(json.dumps(record)+'\n')
            time.sleep(2)


if __name__=='__main__':main()
