import test from 'node:test';
import assert from 'node:assert/strict';
import {aggregate,distribution,attachResourceTimings} from '../scripts/benchmark_browser.mjs';

test('nearest-rank tails retain denominator and do not mix empty/error with successful timing',()=>{
  assert.deepEqual(distribution([]),{n:0,p50:null,p95:null,p99:null});
  assert.deepEqual(distribution(Array.from({length:100},(_,i)=>i+1)),{n:100,p50:50,p95:95,p99:99});
  const rows=[...Array.from({length:100},()=>({status:'success',ms:50})),{status:'empty',ms:1},{status:'timeout',ms:20000},{status:'blocked'}];
  const r=aggregate(rows,'ms',1000);
  assert.equal(r.attempted,103);assert.equal(r.success_only.n,100);assert.equal(r.success_only.p95,50);
  assert.equal(r.counts.empty,1);assert.equal(r.counts.timeout,1);assert.equal(r.counts.blocked,1);
  assert.equal(r.by_status.empty.p95,1);assert.equal(r.by_status.timeout.p95,20000);
  assert.equal(r.by_status.blocked.n,0);
  assert.equal(r.verdict,'unmet');
  assert.equal(aggregate([{status:'empty',ms:1}],'ms',2500).verdict,'unverified');
  assert.equal(aggregate([{status:'success',ms:1}],'ms',2500).verdict,'unverified');
  assert.equal(aggregate(rows.slice(0,100),'ms',1000).verdict,'met');
});

test('native timing replaces asynchronous CDP events without clamping impossible clocks',()=>{
  const requests=[{url:'/a',wall_time:1.1,cdp_event_ttfb_ms:400,cdp_total_ms:300},{url:'/b',wall_time:1.2},{url:'/c',wall_time:1.3}];
  attachResourceTimings(requests,[{url:'/a',start:100,response_start:210,response_end:350},{url:'/b',start:200,response_start:0,response_end:230}],1000);
  assert.equal(requests[0].ttfb_ms,110);assert.equal(requests[0].total_ms,250);
  assert.equal(requests[0].cdp_event_ttfb_ms,400);
  assert.equal(requests[1].timing_status,'unverified_invalid_resource_timing');assert.equal(requests[1].total_ms,undefined);
  assert.equal(requests[2].timing_status,'unverified_missing_resource_timing');
});
