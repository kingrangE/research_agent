from datetime import datetime
from contextlib import closing
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import sqlite3
import unittest
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_summary',ROOT/'scripts/summarize_native_load.py')
summary=importlib.util.module_from_spec(spec);spec.loader.exec_module(summary)


class NativeLoadTests(unittest.TestCase):
    def test_unmarked_database_is_never_modified(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'news.sqlite3';path.write_bytes(b'unmarked original')
            result=subprocess.run([sys.executable,str(ROOT/'scripts/serve_load_fixture.py'),'--root',temporary,'--port','0'],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('refuse existing database',result.stderr)
            self.assertEqual(path.read_bytes(),b'unmarked original')
            self.assertFalse((Path(temporary)/'inputs.json').exists())

    def test_aborted_load_does_not_hide_unfinished_attempts_or_inflate_full_window_rps(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            (folder/'command.json').write_text(json.dumps({'started':datetime.fromisoformat('2026-11-17T00:00:00+00:00').timestamp(),'env':{'DURATION':'30s','USERS':'100','MODE':'sessions','PHASE':'normal'}}))
            (folder/'result.json').write_text(json.dumps({'resource_stop':'test limit'}))
            (folder/'telemetry.jsonl').write_text('')
            points=[('request_attempts',3,{}),('http_reqs',2,{}),('http_req_failed',0,{}),('response_outcomes',1,{'outcome':'ok'}),('response_outcomes',1,{'outcome':'content'}),
                    ('active_rounds',1,{'session_slot':'27'}),('api_latency',200,{'endpoint':'dashboard'})]
            with gzip.open(folder/'metrics.json.gz','wt') as stream:
                for metric,value,tags in points:
                    stream.write(json.dumps({'type':'Point','metric':metric,'data':{'time':'2026-11-17T00:00:02+00:00','value':value,'tags':tags}})+'\n')
            result=summary.summarize(folder)
            self.assertEqual(result['attempted'],3)
            self.assertEqual(result['unfinished_attempts'],1)
            self.assertIsNone(result['failure_rate'])
            self.assertEqual(result['failure_per_attempt_lower_bound'],1/3)
            self.assertEqual(result['failure_or_unverified_rate'],2/3)
            self.assertEqual(result['rps_full_scheduled_window'],.1)
            self.assertEqual(result['distinct_active_session_slots'],1)
            self.assertEqual(result['latency_ms']['dashboard']['p99'],200)
            with gzip.open(folder/'metrics.json.gz','at') as stream:
                stream.write(json.dumps({'type':'Point','metric':'http_reqs','data':{'time':'2026-11-17T00:00:03+00:00','value':1,'tags':{}}})+'\n')
            result=summary.summarize(folder)
            self.assertEqual(result['unfinished_attempts'],0)
            self.assertEqual(result['native_completed_without_content_check'],1)
            self.assertEqual(result['unverified_attempts'],1)
            self.assertIsNone(result['failure_rate'])

    def test_quantile_includes_tail(self):
        self.assertEqual(summary.quantile([1,2,100],.5),2)
        self.assertAlmostEqual(summary.quantile([1,2,100],.99),98.04)
        self.assertIsNone(summary.quantile([],.95))

    def test_recovery_requires_a_full_stable_window_and_every_slot(self):
        events=[{'kind':'synthetic','event':'removed','at':0}]
        endpoints=['dashboard','market','feed','quotes','timeline','detail']
        points=[(second,endpoint,10) for second in range(120) for endpoint in endpoints]
        attempts=[(second,6) for second in range(120)]
        beats=[(second,str(slot)) for second in range(0,120,5) for slot in range(100)]
        result=summary.recovery_windows(events,points,[(1,6)],attempts,beats,120)[0]
        self.assertEqual(result['recovery']['seconds_after_removal'],2)
        self.assertEqual(result['verdict'],'met_at_100_sessions')
        missing=[row for row in beats if row[1]!='99']
        self.assertEqual(summary.recovery_windows(events,points,[],attempts,missing,120)[0]['verdict'],'unmet')
        self.assertEqual(summary.recovery_windows(events,points,[],attempts,beats,10)[0]['verdict'],'unverified')

    def test_real_handler_and_sqlite_fixture_on_ephemeral_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            process=subprocess.Popen([sys.executable,str(ROOT/'scripts/serve_load_fixture.py'),'--root',temporary,'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                line=process.stdout.readline()
                if not line:self.fail(process.stderr.read())
                state=json.loads(line);port=state['port']
                with urlopen(f'http://127.0.0.1:{port}/api/articles?q=00010',timeout=15) as response:
                    data=json.load(response)
                self.assertEqual(data['total'],1)
                self.assertEqual(data['articles'][0]['id'],'load27_00010')
                with urlopen(f'http://127.0.0.1:{port}/api/stock-timeline?code=100000',timeout=15) as response:
                    data=json.load(response)
                self.assertEqual(data['code'],'100000')
                self.assertEqual(len(data['points']),60)
                self.assertTrue((Path(temporary)/'news.sqlite3').is_file())
                manifest=json.loads((Path(temporary)/'manifest.json').read_text())
                self.assertEqual(manifest['base_url'],f'http://127.0.0.1:{port}')
                self.assertTrue(manifest['synthetic'])
                with urlopen(f'http://127.0.0.1:{port}'+manifest['feed'][5]['path'],timeout=15) as response:
                    page=json.load(response)
                self.assertEqual(page['articles'][0]['id'],'load27_00969')
                self.assertEqual(page['total'],1000)
                for _ in range(20):
                    with closing(sqlite3.connect(Path(temporary)/'news.sqlite3')) as db:
                        previous=db.execute("SELECT max(json_extract(payload,'$.synthetic_revision')) FROM items").fetchone()[0]
                    if previous is not None:break
                    time.sleep(.05)
                self.assertIsNotNone(previous)
                process.terminate();process.communicate(timeout=15)
                process=subprocess.Popen([sys.executable,str(ROOT/'scripts/serve_load_fixture.py'),'--root',temporary,'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                self.assertTrue(process.stdout.readline())
                for _ in range(20):
                    with closing(sqlite3.connect(Path(temporary)/'news.sqlite3')) as db:
                        current=db.execute("SELECT max(json_extract(payload,'$.synthetic_revision')) FROM items").fetchone()[0]
                    if current>previous:break
                    time.sleep(.05)
                self.assertGreater(current,previous)
                verified=subprocess.run([sys.executable,str(ROOT/'scripts/serve_load_fixture.py'),'--root',temporary,'--verify'],capture_output=True,text=True)
                self.assertEqual(verified.returncode,0,verified.stderr)
                self.assertTrue(json.loads(verified.stdout)['integrity_ok'])
                with closing(sqlite3.connect(Path(temporary)/'news.sqlite3')) as db:
                    db.execute("UPDATE items SET payload='{}' WHERE rowid=(SELECT min(rowid) FROM items)");db.commit()
                corrupted=subprocess.run([sys.executable,str(ROOT/'scripts/serve_load_fixture.py'),'--root',temporary,'--verify'],capture_output=True,text=True)
                self.assertEqual(corrupted.returncode,2)
                self.assertEqual(json.loads(corrupted.stdout)['stored_payload_fingerprint_mismatches'],1)
            finally:
                process.terminate();process.communicate(timeout=15)


if __name__=='__main__':unittest.main()
