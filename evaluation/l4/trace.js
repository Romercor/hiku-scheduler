// Load from a weighted function table, counting cold and warm from the backend's reply.
// MODE=direct hits the workers with no scheduler, as the control.
// env: FUNCS MODE(l4|l7|direct) SCHED WORKERS RATE DUR BURST VUS MAXVUS TMO
import http from 'k6/http';
import { Counter } from 'k6/metrics';

const funcs = JSON.parse(open(__ENV.FUNCS || 'trace.json'));
const MODE = __ENV.MODE || 'l4';
const SCHED = __ENV.SCHED || '10.156.0.22';
const WORKERS = (__ENV.WORKERS || '').split(',').filter(Boolean);
const cum = [];
let acc = 0;
for (const f of funcs) { acc += f.weight; cum.push(acc); }
const cold = new Counter('cold_starts');
const warm = new Counter('warm_hits');
const N_W = Number(__ENV.N_WORKERS || 8);
const wc = [];
for (let i = 1; i <= N_W; i++) wc.push(new Counter('to_worker' + i));

// BURST=low,high,seconds switches the rate between the two every that many seconds, for DUR
// (seconds) in all, instead of holding RATE: the steps are what makes instances scale up and down.
const burst = (__ENV.BURST || '').split(',').map(Number);
const stages = [];
for (let t = 0; burst.length === 3 && t < parseInt(__ENV.DUR || '30'); t += burst[2]) {
  const target = burst[(t / burst[2]) % 2];
  stages.push({ target, duration: '0s' }, { target, duration: burst[2] + 's' });
}
const vus = { timeUnit: '1s', gracefulStop: '3s',
  preAllocatedVUs: Number(__ENV.VUS || 200), maxVUs: Number(__ENV.MAXVUS || 1000) };

export const options = {
  scenarios: { load: stages.length
    ? Object.assign({ executor: 'ramping-arrival-rate', startRate: burst[0], stages }, vus)
    : Object.assign({ executor: 'constant-arrival-rate', rate: Number(__ENV.RATE || 500),
                      duration: __ENV.DUR || '30s' }, vus) },
  noConnectionReuse: __ENV.NOKA === '1',
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

function pick() {
  const r = Math.random();
  let lo = 0, hi = cum.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; if (r <= cum[m]) hi = m; else lo = m + 1; }
  return funcs[lo];
}

// The reply 'worker-N fn warm' is read by offset: a regex costs more CPU than the request.
export default function () {
  const f = pick();
  let url;
  if (MODE === 'l7') url = `http://${SCHED}:9020/run/${f.name}`;
  else if (MODE === 'direct') url = `http://${WORKERS[(Math.random() * WORKERS.length) | 0]}/run/${f.name}`;
  else url = `http://${SCHED}:${f.port}/run/${f.name}`;
  const res = http.get(url, { timeout: __ENV.TMO || '10s' });
  if (res.status !== 200 && __ENV.DEBUG)
    console.error(`FAIL s=${res.status} ec=${res.error_code} e=${res.error} port=${f.port}`);
  const b = res.body;
  if (b) {
    if (b.charCodeAt(b.length - 2) === 100) cold.add(1); else warm.add(1);
    const w = b.charCodeAt(7) - 48;
    if (w >= 1 && w <= N_W) wc[w - 1].add(1);
  }
}
