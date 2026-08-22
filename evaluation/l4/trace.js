// Trace-driven load: pick a function per request by weight, hit the L4 function port
// (:<port>/run/<name>) or the L7 proxy (:9020/run/<name>), and count cold vs warm
// from the backend response. env: FUNCS MODE(l4|l7) SCHED RATE DUR
import http from 'k6/http';
import { Counter } from 'k6/metrics';

const funcs = JSON.parse(open(__ENV.FUNCS || 'trace.json'));
const MODE = __ENV.MODE || 'l4';
const SCHED = __ENV.SCHED || '10.156.0.22';
const cum = [];
let acc = 0;
for (const f of funcs) { acc += f.weight; cum.push(acc); }
const cold = new Counter('cold_starts');
const warm = new Counter('warm_hits');
const w1c = new Counter('to_worker1');
const w2c = new Counter('to_worker2');
const w3c = new Counter('to_worker3');

export const options = {
  scenarios: { load: { executor: 'constant-arrival-rate', rate: Number(__ENV.RATE || 500),
    timeUnit: '1s', duration: __ENV.DUR || '30s', gracefulStop: '3s',
    preAllocatedVUs: 200, maxVUs: 1000 } },
  noConnectionReuse: __ENV.NOKA === '1',
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

function pick() {
  const r = Math.random();
  let lo = 0, hi = cum.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; if (r <= cum[m]) hi = m; else lo = m + 1; }
  return funcs[lo];
}

export default function () {
  const f = pick();
  const url = MODE === 'l7'
    ? `http://${SCHED}:9020/run/${f.name}`
    : `http://${SCHED}:${f.port}/run/${f.name}`;
  const res = http.get(url);
  if (res.status !== 200 && __ENV.DEBUG)
    console.error(`FAIL s=${res.status} ec=${res.error_code} e=${res.error} port=${f.port}`);
  if (res.body && res.body.indexOf('cold') >= 0) cold.add(1); else warm.add(1);
  if (res.body && res.body.indexOf('worker-1') >= 0) w1c.add(1);
  else if (res.body && res.body.indexOf('worker-2') >= 0) w2c.add(1);
  else if (res.body && res.body.indexOf('worker-3') >= 0) w3c.add(1);
}
