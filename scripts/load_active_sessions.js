// k6 v0.54+; private fixture manifest, no provider calls or fault injection here.
import http from 'k6/http';
import { sleep } from 'k6';
import exec from 'k6/execution';
import { Counter, Rate, Trend } from 'k6/metrics';

export const VERSION = 'active-sessions-v1';
const manifest = JSON.parse(open(__ENV.MANIFEST));
const users = Number(__ENV.USERS || 100);
const duration = __ENV.DURATION || '10m';
const mode = __ENV.MODE || 'sessions';
const phase = __ENV.PHASE || 'normal';
const seed = Number(__ENV.SEED || 27);
const period = 5;
const durationMatch = /^(\d+)(s|m|h)$/.exec(duration);
const seconds = durationMatch ? Number(durationMatch[1]) * ({s:1,m:60,h:3600}[durationMatch[2]]) : 0;
const expectedRounds = users * seconds / period;
const expectedRequests = users * (seconds / period * 2 + seconds / 10) + users * .15 * seconds / 30;
const attempts = new Counter('request_attempts');
const failures = new Rate('response_failure');
const outcomes = new Counter('response_outcomes');
const latency = new Trend('api_latency', true);
const rounds = new Counter('active_rounds');
const completedRounds = new Counter('completed_rounds');
const initialized = new Counter('initialized_sessions');
const missed = new Counter('missed_poll_rounds');
const delay = new Trend('schedule_delay', true);

export function validateManifest(value) {
  if (!value.isolated || !value.external_egress_blocked || value.product_mode !== 'data')
    throw new Error('isolated data-mode server with blocked provider egress required');
  if (!/^https?:\/\/[^/?#]+$/.test(value.base_url)) throw new Error('base_url must be an origin');
  for (const group of ['dashboard', 'market', 'feed', 'quotes', 'timeline', 'detail']) {
    if (!Array.isArray(value[group]) || !value[group].length) throw new Error('missing fixtures: '+group);
    for (const item of value[group]) {
      if (!/^\/api\/[a-z-]+(?:\?[^\s#]*)?$/.test(item.path)) throw new Error('relative API path required');
      if (!Array.isArray(item.assertions) || !item.assertions.length) throw new Error('content assertions required');
      if (item.status !== undefined && item.status !== 200) throw new Error('only HTTP 200 is a successful read');
      for (const assertion of item.assertions) {
        if (typeof assertion.pointer !== 'string' || (assertion.pointer && !assertion.pointer.startsWith('/')) || !Object.prototype.hasOwnProperty.call(assertion, 'equals')
            || (assertion.equals !== null && typeof assertion.equals === 'object'))
          throw new Error('JSON pointer and equals required');
      }
    }
  }
}
validateManifest(manifest);
if (!Number.isInteger(users) || users < 100 || users > 10000 || users % 100 || seconds < 30 || seconds % 30 || !['sessions','arrival'].includes(mode)
    || !['normal','fault','recovery'].includes(phase) || !Number.isInteger(seed)) throw new Error('invalid run configuration');

// Arrival mode is deliberately a separate experiment, not a count of active users.
export const options = {
  scenarios: { load: mode === 'sessions'
    ? { executor: 'constant-vus', vus: users, duration, gracefulStop: '20s' }
    : { executor: 'constant-arrival-rate', rate: users, timeUnit: '5s', duration,
        preAllocatedVUs: Number(__ENV.GENERATOR_VUS || users), maxVUs: Number(__ENV.GENERATOR_VUS || users), gracefulStop: '20s' } },
  discardResponseBodies: false,
  maxRedirects: 0,
  systemTags: ['proto','status','method','name','group','check','error_code','scenario','expected_response'],
  summaryTrendStats: ['avg','p(50)','p(95)','p(99)','max','count'],
  thresholds: phase === 'normal' ? {
    'response_failure{phase:normal}': ['rate<=0.001'],
    ...(mode === 'sessions' ? {missed_poll_rounds: ['count==0']} : {}),
    active_rounds: [`count>=${expectedRounds}`],
    ...(mode === 'sessions' ? {initialized_sessions: [`count==${users}`]} : {}),
    ...(mode === 'arrival' ? { dropped_iterations: ['count==0'] } : {}),
    ...Object.fromEntries(['dashboard','market','feed','quotes','timeline','detail'].map(endpoint =>
      [`api_latency{endpoint:${endpoint},phase:normal}`, ['p(95)<=1000','p(99)<=3000']]))
  } : {}
};

export function randomIndex(id, tick, size) {
  // Deterministic integer hash: no global RNG state affected by request completion order.
  let x = (id ^ Math.imul(tick + 1, 2654435761) ^ seed) >>> 0;
  x ^= x >>> 16; x = Math.imul(x, 2246822507); x ^= x >>> 13;
  return (x >>> 0) % size;
}

export function workload(id, tick) {
  const group = (id - 1) % 100;
  const endpoints = ['dashboard', group < 60 ? 'market' : group < 85 ? 'feed' : 'timeline'];
  if (tick % 2 === 0) endpoints.push('quotes');
  // shortcut: modal dwell and navigation are provisional until a real browser trace calibrates them.
  if (group >= 85 && tick % 6 === 0) endpoints.push('detail');
  return endpoints.map(endpoint => ({endpoint, fixture: manifest[endpoint][
    __ENV.POPULAR === '1' && ['quotes','timeline'].includes(endpoint) ? 0 : randomIndex(id, tick, manifest[endpoint].length)]}));
}

export function validContent(body, assertions) {
  try {
    const value = JSON.parse(body);
    return assertions.every(({pointer, equals}) => {
      const actual = pointer === '' ? value : pointer.slice(1).split('/').reduce((v, key) =>
        v == null ? undefined : v[key.replace(/~1/g, '/').replace(/~0/g, '~')], value);
      return JSON.stringify(actual) === JSON.stringify(equals);
    });
  } catch { return false; }
}

let nextTickAt;
let logicalTick = 0;
export default function () {
  const id = mode === 'sessions' ? exec.vu.idInTest : exec.scenario.iterationInTest + 1;
  if (mode === 'sessions') {
    if (nextTickAt === undefined) {
      initialized.add(1);
      const offset = __ENV.SYNC === '1' ? 0 : randomIndex(id, 0, 5000) / 1000;
      sleep(offset);
      nextTickAt = Date.now();
    }
    const late = Math.max(0, Date.now() - nextTickAt);
    delay.add(late, {phase});
    const lost = Math.floor(late / (period * 1000));
    missed.add(lost);
    logicalTick += lost;
  }
  const tick = mode === 'sessions' ? logicalTick : Math.floor(exec.scenario.iterationInTest / users);
  const sessionTags = mode === 'sessions' ? {phase, mode, session_slot: String(id)} : {phase, mode};
  rounds.add(1, sessionTags);
  // Parallel fetches match independent UI timers; request timeouts remain bounded.
  const requests = workload(id, tick);
  for (const {endpoint} of requests) attempts.add(1, {endpoint, phase});
  const responses = http.batch(requests.map(({endpoint,fixture}) => ['GET', manifest.base_url + fixture.path, null,
    { timeout: '15s', redirects: 0, tags: {name: endpoint, endpoint, phase}, responseType: 'text' }]));
  responses.forEach((response, index) => {
    const {endpoint, fixture} = requests[index];
    const tags = {endpoint, phase};
    const contentOK = validContent(response.body, fixture.assertions);
    const ok = response.status === 200 && contentOK;
    failures.add(!ok, tags);
    outcomes.add(1, {...tags, outcome: response.status === 0 ? (response.error_code === 1050 ? 'timeout' : 'connection')
      : response.status >= 500 ? '5xx' : response.status >= 400 ? '4xx' : !contentOK ? 'content' : ok ? 'ok' : 'status'});
    latency.add(response.timings.duration, tags);
  });
  completedRounds.add(1, sessionTags);
  if (mode === 'sessions') {
    logicalTick++;
    nextTickAt += period * 1000;
    sleep(Math.max(0, (nextTickAt - Date.now()) / 1000));
  }
}

export function handleSummary(data) {
  const result = { version: VERSION, users, mode, phase, seed, duration,
    expected_rounds: expectedRounds, expected_requests: expectedRequests, expected_rps: expectedRequests / seconds,
    attempted_requests: data.metrics.request_attempts?.values.count ?? 0,
    unattempted_expected_requests: Math.max(0, expectedRequests - (data.metrics.request_attempts?.values.count ?? 0)),
    fixture_manifest_sha256: __ENV.MANIFEST_SHA256 || null,
    browser_trace_calibrated: manifest.browser_trace_calibrated === true,
    goal_10000: 'unverified',
    note: 'Thresholds alone do not establish active-user attainment, integrity, recovery or browser latency. Join private request output and host telemetry; see protocol.',
    metrics: data.metrics };
  return { [__ENV.SUMMARY || 'issue27-summary.json']: JSON.stringify(result, null, 2) };
}
