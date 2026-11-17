"""Run bounded local issue-27 native k6 experiments and retain private telemetry."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
LIMITS={'generator_rss_bytes':4*1024**3,'combined_rss_bytes':6*1024**3,
        'server_threads':384,'raw_output_bytes':1024**3}


def capture(*args):
    result=subprocess.run(args,capture_output=True,text=True)
    return result.returncode,result.stdout.strip()


def sample(pid):
    code,value=capture('ps','-p',str(pid),'-o','pcpu=,rss=')
    if code or not value:return {'pid':pid,'exited':True}
    cpu,rss=value.split()
    _,threads=capture('ps','-M','-p',str(pid),'-o','pid=')
    _,files=capture('lsof','-nP','-a','-p',str(pid),'-iTCP','-F','fT')
    return {'pid':pid,'cpu_percent':float(cpu),'rss_bytes':int(rss)*1024,
            'threads':len(threads.splitlines()),'tcp_connections':files.count('TST=ESTABLISHED'),
            'tcp_listeners':files.count('TST=LISTEN')}


def notify(subject,body,args):
    result=subprocess.run(['orca','orchestration','send','--from',args.sender,'--type','status',
                           '--subject',subject,'--body',body,'--task-id',args.task,'--dispatch-id',args.dispatch],capture_output=True,text=True)
    return {'exit_code':result.returncode,'stdout':result.stdout.strip()}


def run_stage(args,name,users,duration,mode='sessions',phase='normal',sync=False,faults=None):
    folder=args.output/name;folder.mkdir()
    env={**os.environ,'MANIFEST':str(args.manifest),'MANIFEST_SHA256':sha256(args.manifest.read_bytes()).hexdigest(),
         'USERS':str(users),'DURATION':duration,'MODE':mode,'PHASE':phase,'SEED':'27','SYNC':'1' if sync else '0',
         'POPULAR':os.environ.get('POPULAR','0'),
         'SUMMARY':str(folder/'summary.json'),'K6_NO_USAGE_REPORT':'true'}
    command=['k6','run','--quiet','--no-usage-report','--out','json='+str(folder/'metrics.json.gz'),str(ROOT/'scripts/load_active_sessions.js')]
    started=time.time()
    (folder/'command.json').write_text(json.dumps(dict(command=command,env={k:env[k] for k in ['MANIFEST','MANIFEST_SHA256','USERS','DURATION','MODE','PHASE','SEED','SYNC','POPULAR','SUMMARY']},started=started,limits=LIMITS),indent=2))
    with (folder/'k6.log').open('w') as log:
        process=subprocess.Popen(command,env=env,stdout=log,stderr=log,cwd=ROOT)
        stopped=None;last_notice=started;fault_thread=None
        fault_errors=[]
        if faults:
            def guarded_faults():
                try:faults(folder)
                except Exception as error:
                    fault_errors.append(type(error).__name__+': '+str(error))
                    (folder/'fault-error.json').write_text(json.dumps(fault_errors))
            fault_thread=threading.Thread(target=guarded_faults,daemon=True);fault_thread.start()
        with (folder/'telemetry.jsonl').open('w',buffering=1) as telemetry:
            while process.poll() is None:
                now=time.time();generator=sample(process.pid);target=sample(args.target_pid)
                output_bytes=(folder/'metrics.json.gz').stat().st_size if (folder/'metrics.json.gz').exists() else 0
                record={'at':now,'elapsed':now-started,'generator':generator,'server':target,'compressed_output_bytes':output_bytes}
                telemetry.write(json.dumps(record)+'\n')
                if generator.get('rss_bytes',0)>LIMITS['generator_rss_bytes']:stopped='generator RSS budget exceeded'
                elif generator.get('rss_bytes',0)+target.get('rss_bytes',0)>LIMITS['combined_rss_bytes']:stopped='combined RSS budget exceeded'
                elif target.get('threads',0)>LIMITS['server_threads']:stopped='server thread safety budget exceeded'
                elif output_bytes>LIMITS['raw_output_bytes']:stopped='raw output disk budget exceeded'
                if stopped:
                    process.send_signal(signal.SIGINT)
                    try:process.wait(timeout=25)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                    break
                if now-last_notice>=60:
                    notify('#27 실제 부하 진행: '+name,json.dumps(record,ensure_ascii=False),args);last_notice=now
                time.sleep(5)
        code=process.wait()
        if fault_thread:fault_thread.join(timeout=300)
    result={'stage':name,'users':users,'duration':duration,'mode':mode,'phase':phase,'elapsed_seconds':time.time()-started,
            'exit_code':code,'resource_stop':stopped,'completed_duration':stopped is None and code in (0,99),'fault_errors':fault_errors}
    (folder/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
    notify('#27 단계 결과: '+name,json.dumps(result,ensure_ascii=False),args)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--target-pid',type=int,required=True)
    parser.add_argument('--sender',required=True);parser.add_argument('--task',required=True);parser.add_argument('--dispatch',required=True)
    parser.add_argument('--faults-only',action='store_true')
    parser.add_argument('--target-root',type=Path)
    args=parser.parse_args();args.output=args.output.resolve();args.manifest=args.manifest.resolve()
    args.output.mkdir(exist_ok=False)
    plan={'started_at':datetime.now(timezone.utc).isoformat(),'head':capture('git','rev-parse','HEAD')[1],
          'limits':LIMITS,'mode':'same-host actual HTTP; deterministic synthetic data; no paid or production resource',
          'stages':[[100,'10m'],[1000,'10m'],[5000,'10m'],[10000,'30m'],[10000,'2h']],
          'on_resource_stop':'stop regular escalation; one guarded 10000-VU diagnostic attempt, then lower-load probes',
          'normal_budgets':{'p95_ms':1000,'p99_ms':3000,'failure_rate':.001},'recovery_budget_seconds':60}
    if args.faults_only:
        plan['stages']=[[100,'12m']];plan['phase']='fault'
        plan['fault_schedule']=[[30,55,'429'],[140,165,'5xx'],[250,275,'timeout'],[360,385,'missing'],[470,475,'db-lock'],[580,582,'restart']]
    (args.output/'plan.json').write_text(json.dumps(plan,indent=2))
    if args.faults_only:
        if args.target_root is None:parser.error('--faults-only requires --target-root')
        root=args.target_root.resolve()
        def inject(folder):
            origin=time.monotonic()
            with (folder/'faults.jsonl').open('w',buffering=1) as timeline:
                def record(kind,event,**extra):
                    timeline.write(json.dumps({'at':time.time(),'kind':kind,'event':event,**extra})+'\n')
                for begin,end,kind in [(30,55,'429'),(140,165,'5xx'),(250,275,'timeout'),(360,385,'missing'),(470,475,'db-lock'),(580,582,'restart')]:
                    time.sleep(max(0,begin-(time.monotonic()-origin)))
                    if kind=='db-lock':
                        connection=sqlite3.connect(root/'news.sqlite3',timeout=10)
                        started=time.monotonic();connection.execute('BEGIN IMMEDIATE')
                        record(kind,'start',acquire_seconds=time.monotonic()-started)
                    elif kind=='restart':
                        record(kind,'start',old_pid=args.target_pid)
                        # This PID was explicitly supplied as this harness's isolated server.
                        os.kill(args.target_pid,signal.SIGTERM)
                    else:
                        temporary=root/'fault.tmp';temporary.write_text(json.dumps({'provider':kind}));temporary.replace(root/'fault.json')
                        record(kind,'start')
                    time.sleep(max(0,end-(time.monotonic()-origin)))
                    if kind=='db-lock':connection.rollback();connection.close()
                    elif kind=='restart':
                        with (folder/'restarted-server.log').open('w') as log:
                            target=subprocess.Popen(['python3',str(ROOT/'scripts/serve_load_fixture.py'),'--root',str(root),'--port','19227'],stdout=log,stderr=log,cwd=ROOT)
                        args.target_pid=target.pid
                        (folder/'restarted-pid.txt').write_text(str(target.pid))
                    else:
                        temporary=root/'fault.tmp';temporary.write_text('{}');temporary.replace(root/'fault.json')
                    record(kind,'removed',target_pid=args.target_pid)
        result=run_stage(args,'faults-100-12m',100,'12m',phase='fault',faults=inject)
        (args.output/'results.json').write_text(json.dumps({'results':[result]},indent=2));return
    results=[];interrupted=False
    for n,duration in plan['stages']:
        name=f'regular-{n}-{duration}'
        result=run_stage(args,name,n,duration);results.append(result)
        if result['resource_stop']:
            interrupted=True
            time.sleep(20)
            if n<10000:results.append(run_stage(args,'diagnostic-10000-30s',10000,'30s'))
            break
    # Separate short probes do not substitute for the scheduled regular intervals.
    time.sleep(20)
    results.append(run_stage(args,'arrival-1000-60s-smoke',1000,'60s',mode='arrival'))
    time.sleep(20)
    results.append(run_stage(args,'synchronized-100-60s-smoke',100,'60s',sync=True))
    (args.output/'results.json').write_text(json.dumps({'results':results,'regular_escalation_interrupted':interrupted},indent=2))


if __name__=='__main__':main()
