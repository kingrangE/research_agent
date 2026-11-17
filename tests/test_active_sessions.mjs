import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

// Execute the actual k6 module with deterministic metric/transport shims.
// This tests workload accounting and contracts, not native k6 scheduling or HTTP performance.
function harness(env = {}) {
  const groups = ['dashboard','market','feed','quotes','timeline','detail'];
  const manifest = {isolated:true, external_egress_blocked:true, product_mode:'data', base_url:'http://127.0.0.1:19227'};
  for (const group of groups) manifest[group] = [0,1,2].map(i => ({path:`/api/${group}?case=${i}`, assertions:[{pointer:'/ok',equals:true}]}));
  const metrics = {}, sleeps = [];
  class Metric {
    constructor(name) { this.name = name; metrics[name] = []; }
    add(value, tags) { metrics[this.name].push({value, tags}); }
  }
  const transport = {body:'{"ok":true}', status:200, timings:{duration:12}};
  const context = vm.createContext({__ENV:{MANIFEST:'fixture', ...env}, open:()=>JSON.stringify(manifest),
    http:{batch:requests=>requests.map(()=>transport)}, sleep:n=>sleeps.push(n),
    exec:{vu:{idInTest:1}, scenario:{iterationInTest:0}}, Counter:Metric, Rate:Metric, Trend:Metric});
  const source = readFileSync(new URL('../scripts/load_active_sessions.js', import.meta.url),'utf8')
    .replace(/^import .*;\n/gm,'').replace('export default function ()','function run()').replace(/export /g,'');
  vm.runInContext(source, context);
  return {context, metrics, transport, manifest, sleeps, call:code=>vm.runInContext(code, context)};
}

test('10000 HTTP sessions preserve 60/25/15 mixture and expected 5050 RPS', () => {
  const h = harness();
  const counts = h.call(`(() => {
    const counts = {};
    for (let id=1;id<=10000;id++) for (let tick=0;tick<6;tick++)
      for (const request of workload(id,tick)) counts[request.endpoint]=(counts[request.endpoint]||0)+1;
    return counts;
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(counts)), {dashboard:60000,market:36000,quotes:30000,feed:15000,timeline:9000,detail:1500});
  assert.equal(Object.values(counts).reduce((a,b)=>a+b,0)/30, 5050);
  assert.equal(h.call('randomIndex(27,3,9999)'),h.call('randomIndex(27,3,9999)'));
  assert.ok(h.call('new Set(Array.from({length:100},(_,i)=>randomIndex(i,0,5000))).size') > 90);
});

test('2xx malformed JSON, wrong symbol, missing price and stale-as-normal contracts fail', () => {
  const h = harness();
  assert.equal(h.call(`validContent('invalid', [{pointer:'/symbol',equals:'EXPECTED'}])`), false);
  for (const body of ['{}','{"symbol":"WRONG"}','{"symbol":"EXPECTED","price":null}','{"symbol":"EXPECTED","price":1,"status":"ok"}']) {
    h.context.body = body;
    assert.equal(h.call(`validContent(body,[{pointer:'/symbol',equals:'EXPECTED'},{pointer:'/status',equals:'missing'}])`),false);
  }
  assert.equal(h.call(`validContent('{"a/b":{"~key":0}}',[{pointer:'/a~1b/~0key',equals:0}])`), true);
  assert.equal(h.call(`validContent('{"price":null}',[{pointer:'/price',equals:99}])`), false);
  assert.equal(h.call(`validContent('{"price":null,"status":"missing"}',[{pointer:'/price',equals:null},{pointer:'/status',equals:'missing'}])`), true);
});

test('each attempted request has one result and HTTP 200 content errors count in failure denominator', () => {
  const h = harness();
  h.call('run()');
  assert.equal(h.metrics.initialized_sessions.length,1);
  assert.equal(h.metrics.request_attempts.length,3);
  assert.equal(h.metrics.response_failure.length,3);
  assert.ok(h.metrics.response_failure.every(x=>!x.value));
  h.transport.body = '{}';
  h.call('run()');
  assert.ok(h.metrics.response_failure.slice(3).every(x=>x.value));
  assert.ok(h.metrics.response_outcomes.slice(3).every(x=>x.tags.outcome==='content'));
});

test('late session cadence exposes missed rounds instead of pretending lower offered load passes', () => {
  const h = harness();
  h.call('run(); nextTickAt=Date.now()-12000; run()');
  assert.equal(h.metrics.missed_poll_rounds.at(-1).value,2);
  assert.ok(h.metrics.schedule_delay.at(-1).value >= 12000);
});

test('arrival executor and fault budgets are separate, redirects and unsafe manifests rejected', () => {
  const h = harness({MODE:'arrival',USERS:'10000'});
  assert.equal(h.call('options.scenarios.load.rate'),10000);
  assert.equal(h.call('options.scenarios.load.timeUnit'),'5s');
  assert.equal(h.call('options.maxRedirects'),0);
  assert.equal(h.call('options.thresholds.dropped_iterations[0]'),'count==0');
  assert.equal(harness({PHASE:'fault'}).call('Object.keys(options.thresholds).length'),0);
  for (const mutation of ['external_egress_blocked=false','isolated=false','product_mode="model"','base_url="https://host/path"','quotes[0].path="//elsewhere/api"','quotes[0].assertions=[]']) {
    assert.throws(()=>harness().call(`manifest.${mutation};validateManifest(manifest)`));
  }
});

test('timeout, connection and 5xx remain distinguishable and reports cannot approve 10000', () => {
  const h = harness();
  h.transport.status=0; h.transport.error_code=1050; h.call('run()');
  assert.equal(h.metrics.response_outcomes.at(-1).tags.outcome,'timeout');
  h.transport.error_code=1210; h.call('run()');
  assert.equal(h.metrics.response_outcomes.at(-1).tags.outcome,'connection');
  h.transport.status=503; h.call('run()');
  assert.equal(h.metrics.response_outcomes.at(-1).tags.outcome,'5xx');
  const summary = h.call('handleSummary({metrics:{}})');
  assert.equal(JSON.parse(summary['issue27-summary.json']).goal_10000,'unverified');
});
