import http from 'k6/http';
import {check, randomSeed, sleep} from 'k6';
import {SharedArray} from 'k6/data';

const N_COPIES = __ENV.N_COPIES;
const SEED = __ENV.SEED;
const SCHEDULER_DNS = __ENV.SCHEDULER_DNS;

const scheduler = `http://${SCHEDULER_DNS}:9020/run`;

// The L4 scheduler sees no URL path, so the function must be in the port (l4: BASE_PORT + index)
// or in the address (l4addr: 10.200.0.x on one port, routed to the scheduler, owned by no machine).
const MODE = __ENV.MODE || 'l7';
const BASE_PORT = Number(__ENV.BASE_PORT || 5100);
const ADDR_BASE = (10 << 24) | (200 << 16);
const SERVICE_PORT = Number(__ENV.SERVICE_PORT || 8080);
const funcAddr = (i) => {
    const v = (ADDR_BASE + i + 1) >>> 0;
    return `${(v >>> 24) & 255}.${(v >>> 16) & 255}.${(v >>> 8) & 255}.${v & 255}`;
};

const benchmarks = [
    "chameleon",
    "dd",
    "float_operation",
    "gzip_compression",
    "json_dumps_loads",
    "linpack",
    "matmul",
    "pyaes"
];

const funcProbabilities = new SharedArray('funcProbabilities', function () {
    return [JSON.parse(open(__ENV.PROBS || 'azure_function_probabilities.json'))];
});
let uniqueFuncs = Object.keys(funcProbabilities[0]);

// Pseudo-random number generator for fair evaluation of different strategies
// Generate a unique seed for each VU based on its __VU ID
randomSeed(SEED);
const seedgen = (vu = __VU) => (vu * 10000 + Math.random() * 2 ** 32) >>> 0;
const getRand = sfc32(seedgen(), seedgen(), seedgen(), seedgen());
// SHARED=1 gives every VU the same function sample, so the popularity skew of the trace reaches
// the workers; by default each VU draws its own and the skews average out over the VUs.
const sampleRand = __ENV.SHARED === '1' ? sfc32(seedgen(0), seedgen(0), seedgen(0), seedgen(0)) : getRand;

// Randomly sample functions
let sampledFuncs = uniqueFuncs.sort(() => sampleRand() - 0.5).slice(0, benchmarks.length * N_COPIES);

// Filter out sampled functions
const sampledProbDict = Object.fromEntries(
    Object.entries(funcProbabilities[0]).filter(([func, _]) => sampledFuncs.includes(func))
);

// Calculate total probability
let totalProb = 0;
for (const key in sampledProbDict) {
    if (sampledProbDict.hasOwnProperty(key)) {
        totalProb += sampledProbDict[key]["probability"];
    }
}

// Normalize probabilities
for (const key in sampledProbDict) {
    sampledProbDict[key] = Object.assign({}, sampledProbDict[key], {
        probability: sampledProbDict[key]["probability"] / totalProb
    });
}


function weightedRandomChoice(sampledProbDict) {
    // Accumulate probabilities and compare with random value
    const randomValue = getRand();

    let accumulatedProb = 0;
    for (const [key, stats] of Object.entries(sampledProbDict)) {
        accumulatedProb += stats["probability"];
        if (randomValue <= accumulatedProb) {
            return key;
        }
    }
}

function constructPayload(benchmark) {
    let payload;

    switch (benchmark) {
        case "chameleon":
            payload = JSON.stringify({"num_of_rows": 250, "num_of_cols": 250, "metadata": ""});
            break;
        case "dd":
            payload = JSON.stringify({"bs": "1024", "count": "100000"});
            break;
        case "float_operation":
            payload = JSON.stringify({"n": 100000, "metadata": ""});
            break;
        case "gzip_compression":
            payload = JSON.stringify({"file_size": 5});
            break;
        case "json_dumps_loads":
            payload = JSON.stringify({"link": "https://api.nobelprize.org/2.1/nobelPrizes"});
            break;
        case "linpack":
            payload = JSON.stringify({"n": 100, "metadata": ""});
            break;
        case "matmul":
            payload = JSON.stringify({"n": 100, "metadata": ""});
            break;
        case "pyaes":
            payload = JSON.stringify({"length_of_message": 100, "num_of_iterations": 100, "metadata": ""});
            break;
        default:
            throw new Error("Invalid benchmark");
    }

    return payload;
}

// Seedable random number generator
// https://stackoverflow.com/a/47593316
function sfc32(a, b, c, d) {
    return function () {
        a |= 0;
        b |= 0;
        c |= 0;
        d |= 0;
        let t = (a + b | 0) + d | 0;
        d = d + 1 | 0;
        a = b ^ b >>> 9;
        b = c + (c << 3) | 0;
        c = (c << 21 | c >>> 11);
        c = c + t | 0;
        return (t >>> 0) / 4294967296;
    }
}

export default function () {
    // Randomly choose a function based on probability distribution
    const chosenFunc = weightedRandomChoice(sampledProbDict);

    // Map chosen function to benchmark
    let benchmarkMap = {};
    for (let copy = 0; copy < N_COPIES; copy++) {
        for (let i = 0; i < benchmarks.length; i++) {
            const index = copy * benchmarks.length + i;
            benchmarkMap[index] = benchmarks[i] + "-" + copy;
        }
    }

    const funcName = benchmarkMap[sampledFuncs.indexOf(chosenFunc)];

    // Build payload and params
    const benchmark = funcName.split('-')[0];
    const payload = constructPayload(benchmark);

    const params = {
        headers: {
            'Content-Type': 'application/json',
        },
    };

    const dash = funcName.lastIndexOf('-');
    const index = Number(funcName.slice(dash + 1)) * benchmarks.length
        + benchmarks.indexOf(funcName.slice(0, dash));
    const port = BASE_PORT + index;
    let url;
    if (MODE === 'l4addr') {
        url = `http://${funcAddr(index)}:${SERVICE_PORT}/run/${funcName}`;
    } else if (MODE === 'l4') {
        url = `http://${SCHEDULER_DNS}:${port}/run/${funcName}`;
    } else {
        url = `${scheduler}/${funcName}`;
    }
    let res = http.post(url, payload, params);
    check(res, {
        'status is 200': (r) => r.status === 200,
    });

    sleep((getRand() * 0.9 + 0.1) * SLEEPSCALE);
}

// SLEEPSCALE and VUSCALE lowered together give fewer, busier VUs at about the same load, so each
// connection carries more requests. VUSCALE alone splits the profile across k6 instances.
const SLEEPSCALE = Number(__ENV.SLEEPSCALE || 1);
const VUSCALE = Number(__ENV.VUSCALE || 1);
const vus = (n) => Math.max(1, Math.round(n * VUSCALE));

// NOKA=1 opens a connection per request, since L4 picks a worker per connection and L7 per request.
// RATE=<req/s> is an open loop held for DUR, so the load does not slow down with the system (use
// SLEEPSCALE=0); RAMP=<time> first rises from a fifth of it, so not every function starts at once.
export const options = {
    discardResponseBodies: true,
    noConnectionReuse: __ENV.NOKA === '1',
    scenarios: __ENV.RATE ? {
        open_loop: Object.assign({
            timeUnit: '1s',
            preAllocatedVUs: 500,
            maxVUs: 3000,
            gracefulStop: '0s',
        }, __ENV.RAMP ? {
            executor: 'ramping-arrival-rate',
            startRate: Math.round(Number(__ENV.RATE) / 5),
            stages: [
                {target: Number(__ENV.RATE), duration: __ENV.RAMP},
                {target: Number(__ENV.RATE), duration: __ENV.DUR || '120s'},
            ],
        } : {
            executor: 'constant-arrival-rate',
            rate: Number(__ENV.RATE),
            duration: __ENV.DUR || '120s',
        }),
    } : {
        low_load: {
            executor: 'constant-vus',
            vus: vus(20),
            duration: '100s',
            startTime: '0s',
            gracefulStop: '0s',
        },
        medium_load: {
            executor: 'constant-vus',
            vus: vus(50),
            duration: '100s',
            startTime: '100s',
            gracefulStop: '0s',
        },
        high_load: {
            executor: 'constant-vus',
            vus: vus(100),
            duration: '100s',
            startTime: '200s',
            gracefulStop: '0s',
        },
    },
};
