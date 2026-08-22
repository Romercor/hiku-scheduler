import http from 'k6/http';
const RATE = Number(__ENV.RATE || 0);
const trend = ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'];
export const options = RATE > 0 ? {
  scenarios: { load: { executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s',
    duration: __ENV.DUR || '30s', preAllocatedVUs: 200, maxVUs: 800 } },
  discardResponseBodies: true, summaryTrendStats: trend,
} : {
  scenarios: { load: { executor: 'constant-vus', vus: Number(__ENV.VUS || 50), duration: __ENV.DUR || '30s' } },
  discardResponseBodies: true, summaryTrendStats: trend,
};
const URL = __ENV.TARGET;
export default function () { http.get(URL); }
