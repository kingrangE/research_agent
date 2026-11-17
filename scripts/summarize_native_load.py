"""Aggregate private native k6 output, retaining denominators and session evidence."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import json
import math
from pathlib import Path


def quantile(values,q):
    if not values:return None
    values=sorted(values);position=(len(values)-1)*q;lower=math.floor(position);upper=math.ceil(position)
    return values[lower]+(values[upper]-values[lower])*(position-lower)


def recovery_windows(events,points,errors,attempts,heartbeats,end):
    reports=[]
    for event in events:
        if event['event']!='removed':continue
        removed=event['at'];next_fault=min([e['at'] for e in events if e['event']=='start' and e['at']>removed]+[end])
        found=None;observed=False
        for offset in range(61):
            begin=removed+offset;finish=begin+60
            if finish>next_fault:break
            observed=True
            samples=defaultdict(list)
            for at,endpoint,value in points:
                if begin<=at<finish:samples[endpoint].append(value)
            offered=sum(value for at,value in attempts if begin<=at<finish)
            failed=sum(value for at,value in errors if begin<=at<finish)
            slots=Counter(slot for at,slot in heartbeats if begin<=at<finish)
            if (set(samples)=={'dashboard','market','feed','quotes','timeline','detail'} and offered>0
                and failed==0 and len(slots)==100 and min(slots.values())>=11
                and all(quantile(values,.95)<=1000 and quantile(values,.99)<=3000 for values in samples.values())):
                found={'seconds_after_removal':offset,'stable_window_seconds':60,'attempted_in_window':offered,
                       'failures_in_window':failed,'active_slots':len(slots)};break
        reports.append({'kind':event['kind'],'removed_at':removed,'recovery':found,
                        'verdict':'met_at_100_sessions' if found else 'unmet' if observed else 'unverified',
                        'scope':'1-second search resolution; conservative zero-error 60s window, API budgets and >=11 heartbeats per slot; synthetic writer and integrity checked separately'})
    return reports


def summarize(folder):
    command=json.loads((folder/'command.json').read_text())
    config=command['env'];start=command['started'];seconds=int(config['DURATION'][:-1])*{'s':1,'m':60,'h':3600}[config['DURATION'][-1]]
    rows=Counter();outcomes=Counter();latency=defaultdict(list);session_times=defaultdict(list);error_codes=Counter()
    attempted_window=0;completed_window=0;native_completed_window=0;network=Counter();active_buckets=defaultdict(set);first=None;last=None;native_start=None
    fault_events=[json.loads(line) for line in (folder/'faults.jsonl').read_text().splitlines()] if (folder/'faults.jsonl').exists() else []
    fault_points=[];fault_errors=[];fault_attempts=[];fault_heartbeats=[];last_point=0
    path=folder/'metrics.json.gz'
    with gzip.open(path,'rt') as stream:
        for line in stream:
            row=json.loads(line)
            if row['type']!='Point':continue
            metric=row['metric'];data=row['data'];value=data['value'];tags=data.get('tags') or {}
            at=datetime.fromisoformat(data['time']).timestamp()
            last_point=max(last_point,at)
            if native_start is None and (metric=='initialized_sessions' or config['MODE']=='arrival' and metric=='active_rounds'):
                native_start=at;start=at
            rows[metric]+=value if metric not in ('api_latency','schedule_delay','http_req_duration') else 1
            if metric=='request_attempts':
                first=at if first is None else min(first,at);last=at if last is None else max(last,at)
                if start<=at<start+seconds:attempted_window+=value
                if fault_events:fault_attempts.append((at,value))
            if metric=='response_outcomes':
                outcomes[tags['outcome']]+=value
                if start<=at<start+seconds:completed_window+=value
                if fault_events and tags['outcome'] in ('content','status'):fault_errors.append((at,value))
            if fault_events and metric=='http_req_failed' and value:fault_errors.append((at,value))
            if metric=='http_reqs' and tags.get('error_code'):error_codes[tags['error_code']]+=value
            if metric=='http_reqs' and start<=at<start+seconds:native_completed_window+=value
            if metric=='api_latency':
                latency[tags['endpoint']].append(value)
                if fault_events:fault_points.append((at,tags['endpoint'],value))
            if metric in ('data_received','data_sent'):network[metric]+=value
            if metric=='active_rounds' and 'session_slot' in tags:
                session_times[tags['session_slot']].append(at)
                active_buckets[int((at-start)//5)].add(tags['session_slot'])
                if fault_events:fault_heartbeats.append((at,tags['session_slot']))
    telemetry=[json.loads(line) for line in (folder/'telemetry.jsonl').read_text().splitlines()]
    target={};generator={}
    for kind,result in [('server',target),('generator',generator)]:
        for key in ['cpu_percent','rss_bytes','threads','tcp_connections']:
            values=[r[kind][key] for r in telemetry if key in r[kind]]
            result[key]={'first':values[0] if values else None,'last':values[-1] if values else None,
                         'p50':quantile(values,.5),'p95':quantile(values,.95),'max':max(values) if values else None}
    gaps=[b-a for times in session_times.values() for a,b in zip(sorted(times),sorted(times)[1:])]
    durations=[max(t)-min(t) for t in session_times.values()]
    observed_span=last-first if first is not None and last is not None else None
    attempts=rows['request_attempts'];native_completed=rows['http_reqs']
    failed=rows['http_req_failed']+outcomes['content']+outcomes['status']
    unfinished=max(0,attempts-native_completed)
    unverified=max(0,attempts-failed-outcomes['ok'])
    summary=json.loads((folder/'summary.json').read_text()) if (folder/'summary.json').exists() else {}
    transport=Counter()
    for code,count in error_codes.items():
        number=int(code)
        category=('request_timeout' if number==1050 else 'connection_timeout' if number==1211
                  else 'other_connection' if 1200<=number<1300 else '4xx' if 1400<=number<1500
                  else '5xx' if 1500<=number<1600 else 'other_error')
        transport[category]+=count
    return {'stage':folder.name,'configured_users':int(config['USERS']),'configured_seconds':seconds,'mode':config['MODE'],
            'workload_version':summary.get('version'),'manifest_sha256':config.get('MANIFEST_SHA256'),
            'expected_rps':summary.get('expected_rps'),
            'phase':config['PHASE'],'result':json.loads((folder/'result.json').read_text()),
            'native_window_start_utc_epoch':native_start,
            'expected_requests_full_interval':summary.get('expected_requests'),
            'attempted':attempts,'completed':native_completed,'body_checked_completed':sum(outcomes.values()),
            'validated_successes':outcomes['ok'],'failures':failed,
            'failure_rate':failed/attempts if attempts and not unverified else None,
            'failure_per_attempt_lower_bound':failed/attempts if attempts else None,
            'unfinished_attempts':unfinished,'unverified_attempts':unverified,
            'native_completed_without_content_check':max(0,native_completed-sum(outcomes.values())),
            'failure_or_unverified_rate':(failed+unverified)/attempts if attempts else None,
            'outcomes':dict(outcomes),'missed_poll_rounds':rows['missed_poll_rounds'],'dropped_arrival_iterations':rows['dropped_iterations'],
            'native_error_codes':dict(error_codes),
            'native_transport_failures':dict(transport),
            'native_connection_timings_ms':{k:summary.get('metrics',{}).get(k,{}).get('values') for k in ['http_req_blocked','http_req_connecting','http_req_tls_handshaking']},
            'attempted_in_scheduled_window':attempted_window,'native_completed_in_scheduled_window':native_completed_window,
            'body_checked_in_scheduled_window':completed_window,
            'rps_full_scheduled_window':attempted_window/seconds,
            'completed_rps_full_scheduled_window':native_completed_window/seconds,
            'native_event_window_seconds':last_point-native_start if native_start else None,
            'native_completion_rps_over_event_window':native_completed/(last_point-native_start) if native_start and last_point>native_start else None,
            'observed_request_span_seconds':observed_span,'rps_over_observed_request_span':attempts/observed_span if observed_span else None,
            'network_bytes_k6':dict(network),'latency_ms':{k:{'n':len(v),'p50':quantile(v,.5),'p95':quantile(v,.95),'p99':quantile(v,.99)} for k,v in latency.items()},
            'initialized_sessions':rows['initialized_sessions'],'distinct_active_session_slots':len(session_times),
            'session_rounds':rows['active_rounds'],'completed_rounds':rows['completed_rounds'],
            'minimum_slot_span_seconds':min(durations) if durations else None,
            'slot_round_counts':{'min':min(map(len,session_times.values())) if session_times else None,
                                 'max':max(map(len,session_times.values())) if session_times else None},
            'inter_round_gap_seconds':{'n':len(gaps),'p50':quantile(gaps,.5),'p95':quantile(gaps,.95),'max':max(gaps) if gaps else None},
            'active_slots_per_5s_bucket':{k:len(v) for k,v in sorted(active_buckets.items())},
            'server':target,'generator':generator,
            'fault_recoveries':recovery_windows(fault_events,fault_points,fault_errors,fault_attempts,fault_heartbeats,last_point),
            'limits':['Same-host synthetic input; no production capacity claim.',
                      'Scheduled-window RPS uses the full requested interval even if interrupted; observed-span RPS is separately labelled.',
                      'Interrupted batches can have native completions without JS body validation; these are never successful reads.',
                      '5-second buckets can cross jitter boundaries; per-slot gap and span are required.',
                      'ps CPU is a sampled OS value, not isolated core demand; TCP connections sampled every 5s.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path);args=parser.parse_args()
    reports=[]
    for folder in sorted(args.directory.iterdir()):
        if folder.is_dir() and (folder/'result.json').exists():
            report=summarize(folder);reports.append(report)
            (folder/'aggregate.json').write_text(json.dumps(report,indent=2))
    (args.directory/'aggregates.json').write_text(json.dumps(reports,indent=2))
    print(json.dumps([{'stage':r['stage'],'attempted':r['attempted'],'failure_rate':r['failure_rate'],'distinct_slots':r['distinct_active_session_slots']} for r in reports]))


if __name__=='__main__':main()
