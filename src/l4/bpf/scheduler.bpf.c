// SPDX-License-Identifier: GPL-2.0
//
// Pull-based L4 scheduler for serverless functions, run in the kernel so that no user-space
// process handles a request. Two programs share the maps below, which the loader (loader.go)
// fills from the config:
//   availability (XDP) stores the workers' availability signals: UDP to port 9020, 15 bytes,
//                      big endian: magic(2) op(1, unused here) worker_id(4) fn_hash(4) slots(4)
//   nat (TC ingress)   picks a worker with a free instance of the function at each new TCP
//                      connection and NATs the connection to it and the reply back
// Maps, their types and the counter and teardown helpers come first, then the availability
// program, then the steps nat is built from, and nat itself at the end.

#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/in.h>
#include <linux/udp.h>
#include <linux/tcp.h>
#include <linux/pkt_cls.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>

/* ---- Availability state ----
   Why: the scheduler never sees a function finish, so each worker reports its free instances per
   function and idle_map keeps the latest report per (function, worker). slots is signed because
   two CPUs can take the last slot at once and drive it to -1, which must still read as busy. */
#define SIG_MAGIC 0x484B
#define SIG_PORT  9020
#define SIG_LEN   15

struct sig_key {
    __u32 fn_hash;
    __u32 worker_id;
};
struct worker_state {
    __s32 slots;
    __u64 last_seen_ns;
};

#ifndef IDLE_MAX
#define IDLE_MAX 4096
#endif
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __type(key, struct sig_key);
    __type(value, struct worker_state);
    __uint(max_entries, IDLE_MAX);
} idle_map SEC(".maps");

/* ---- Limits ----
   Why: a kernel program needs fixed sizes, so N_WORKERS, FN_MAX and IDLE_MAX are set at build time
   (setup_l4.sh takes N_WORKERS from the config). A report older than STALE_NS is ignored, so a
   dead worker is not picked from its last report. A refusal comes right after the SYN, so a worker
   RST later than REFUSE_FRESH_NS is taken as an ordinary close. PENALTY_NS is only the default skip
   time, as the loader can set its own. Each connection holds one NAT port on its worker, so
   FLOW_MAX bounds how many can be open at once. */
#ifndef N_WORKERS
#define N_WORKERS   3
#endif
#ifndef FN_MAX
#define FN_MAX      65536
#endif
#define STALE_NS    3000000000ULL
#define REFUSE_FRESH_NS 50000000ULL
#define PENALTY_NS      20000000ULL
#define NAT_PORT_BASE 1024
#define NAT_PORT_SPAN 64512
#define FLOW_MAX      (N_WORKERS * NAT_PORT_SPAN)

/* ---- Flow state ----
   Why: both directions of a connection are rewritten, so a connection must be found from either
   side. Forward packets carry the client tuple (fwdkey), return packets the worker tuple (natkey);
   the worker sees every connection as SCHED_IP:<nat_port>, so nat_port is unique per worker.
   fwdkey holds both halves of what the client dialled, so one layout serves both naming modes, and
   has no padding, as map keys are compared byte for byte. flowval keeps what the reply and the
   close need: saw_resp tells a refusal from an abortive close, wid lets teardown release the
   worker's load, fin[] holds the ack number expected for each side's FIN. Addresses and ports are
   in network order, as written into packets. */
struct endpoint {
    __u32 ip;
    __u16 port;
};
struct fwdkey {
    __u32 client_ip;
    __u32 func_addr;
    __u16 client_port;
    __u16 func_port;
};
struct natkey {
    __u32 worker_ip;
    __u16 worker_port;
    __u16 nat_port;
};
struct fwdval {
    struct natkey nk;
    __u32 closing;
};
struct flowval {
    __u64 opened_ns;
    __u64 state;
    __u32 client_ip;
    __u32 func_addr;
    __u16 client_port;
    __u16 func_port;
    __u8  saw_resp;
    __u8  wid;
    __u16 _pad;
    __u32 fin[2];
};
#define ST_FIN_C  1
#define ST_FIN_W  2
#define ST_ACK_C  4
#define ST_ACK_W  8
#define ST_CLOSED 15
#define ST_UNLOAD 16

/* ---- Loader tables ----
   Why: workers, functions and settings differ per deployment, so the loader writes them at start.
   A function is named by a destination address (fnaddrs, address mode, one shared service port) or
   by a port on the scheduler's own address (fnports, port mode). Address mode needs no address on
   any interface, as TC ingress sees the packet before the kernel checks whether it is local.
   Worker ids start at 1, as 0 means no worker, so the 16-entry per-worker maps allow 15 workers.
   cfg: [0] scheduler IP, [1] pick strategy, [2] fallback, [3] RST feedback, [4] service port,
   [5] refusal penalty in ms, [6] reclaim connections on close. */
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __type(key, __u32);
    __type(value, struct endpoint);
    __uint(max_entries, 16);
} workers SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __type(key, __u16);
    __type(value, __u32);
    __uint(max_entries, 64);
} fnports SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __type(key, __u32);
    __type(value, __u32);
    __uint(max_entries, FN_MAX);
} fnaddrs SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __type(key, __u32);
    __type(value, __u32);
    __uint(max_entries, 8);
} cfg SEC(".maps");

/* ---- Connection and worker state ----
   Why: fwd and flow hold one entry per direction, so each path finds its connection with one
   lookup on what its own packets carry; both are LRU, so connections whose close was missed cannot
   fill them. wpenalty skips a worker that refused a connection and is kept apart from idle_map,
   which the worker's next report overwrites. The kernel cannot see a worker's load, so wflows
   counts the connections it has sent there, for the load-aware fallbacks. wnext keeps each
   worker's NAT port search position between connections, so a port just freed is not handed out
   again at once. */
struct {
    __uint(type, BPF_MAP_TYPE_LRU_HASH);
    __type(key, struct fwdkey);
    __type(value, struct fwdval);
    __uint(max_entries, FLOW_MAX);
} fwd SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_LRU_HASH);
    __type(key, struct natkey);
    __type(value, struct flowval);
    __uint(max_entries, FLOW_MAX);
} flow SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __type(key, __u32);
    __type(value, __u64);
    __uint(max_entries, 16);
} wpenalty SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __type(key, __u32);
    __type(value, __s64);
    __uint(max_entries, 16);
} wflows SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __type(key, __u32);
    __type(value, __u32);
    __uint(max_entries, 16);
} wnext SEC(".maps");

/* ---- Counters ----
   Why: the programs have no other output, so every outcome is counted here and printStats in
   loader.go reads them while the scheduler runs. 0 forward, 1 return, 2 flows, 3 fallback used,
   4 refused, 5 signals, 6 RST that is not a refusal, 7 by address, 8 penalty skip, 9 not steered
   (dropped in address mode, passed on in port mode), with its cause in 13 no worker (a guard that
   pick_worker never triggers), 14 no NAT port or 15 no flow, 10 new on SYN, 11 SYN on an open
   entry, 12 closed by FIN, 16 live flows, 17 left hashed home, 18 signal not stored (idle_map
   full). */
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __type(key, __u32);
    __type(value, __u64);
    __uint(max_entries, 24);
} nat_stats SEC(".maps");

static __always_inline void bump(__u32 i)
{
    __u64 *v = bpf_map_lookup_elem(&nat_stats, &i);
    if (v)
        __sync_fetch_and_add(v, 1);
}

static __always_inline void unbump(__u32 i)
{
    __u64 *v = bpf_map_lookup_elem(&nat_stats, &i);
    if (v)
        __sync_fetch_and_add(v, -1);
}

/* ---- Flow teardown ----
   Why: every teardown goes through drop_flow, so the live-flow counter and the worker load stay in
   step with the deletes, and unload's test-and-set releases a connection's load exactly once,
   whichever path gets there first. Without reclaim on close a closed connection leaves only by RST
   or LRU eviction, and eviction skips drop_flow, so its load is never released. */
static __always_inline void unload(struct flowval *fv)
{
    __u32 wid = fv->wid;
    __s64 *l = bpf_map_lookup_elem(&wflows, &wid);
    if (l && !(__sync_fetch_and_or(&fv->state, ST_UNLOAD) & ST_UNLOAD))
        __sync_fetch_and_add(l, -1);
}

static __always_inline void drop_flow(struct fwdkey *fk, struct natkey *nk)
{
    struct flowval *fv = bpf_map_lookup_elem(&flow, nk);
    if (fv)
        unload(fv);
    bpf_map_delete_elem(&fwd, fk);
    bpf_map_delete_elem(&flow, nk);
    unbump(16);
}

/* ---- Availability ingest (XDP program) ----
   Why: XDP takes the signal at the start of the receive path, so storing it needs no system call
   and no user-space process. The packet is dropped after the update, as nothing else on this host
   needs it. The state is zeroed in full so no stale stack bytes reach the map, which the verifier
   may reject. */
SEC("xdp")
int availability(struct xdp_md *ctx)
{
    void *data = (void *)(long)ctx->data, *end = (void *)(long)ctx->data_end;
    struct ethhdr *eth = data;
    if ((void *)(eth + 1) > end || eth->h_proto != bpf_htons(ETH_P_IP))
        return XDP_PASS;
    struct iphdr *iph = (void *)(eth + 1);
    if ((void *)(iph + 1) > end || iph->protocol != IPPROTO_UDP)
        return XDP_PASS;
    __u32 ihl = iph->ihl * 4;
    if (ihl < sizeof(*iph))
        return XDP_PASS;
    struct udphdr *udph = (void *)iph + ihl;
    if ((void *)(udph + 1) > end || udph->dest != bpf_htons(SIG_PORT))
        return XDP_PASS;
    __u8 *p = (void *)(udph + 1);
    if ((void *)(p + SIG_LEN) > end)
        return XDP_PASS;
    if ((((__u16)p[0] << 8) | p[1]) != SIG_MAGIC)
        return XDP_PASS;

    __u32 worker_id = ((__u32)p[3] << 24) | ((__u32)p[4] << 16) | ((__u32)p[5] << 8) | p[6];
    __u32 fn_hash   = ((__u32)p[7] << 24) | ((__u32)p[8] << 16) | ((__u32)p[9] << 8) | p[10];
    __u32 slots     = ((__u32)p[11] << 24) | ((__u32)p[12] << 16) | ((__u32)p[13] << 8) | p[14];

    struct sig_key key = { .fn_hash = fn_hash, .worker_id = worker_id };
    struct worker_state st;
    __builtin_memset(&st, 0, sizeof(st));
    st.slots = slots;
    st.last_seen_ns = bpf_ktime_get_ns();
    if (bpf_map_update_elem(&idle_map, &key, &st, BPF_ANY))
        bump(18);
    bump(5);
    return XDP_DROP;
}

/* ---- Packet layout and rewriting ----
   Why: the TCP checksum covers the IP addresses (pseudo-header) and the whole payload, so
   recomputing it would read the full packet; each rewrite instead patches the IP and TCP checksums
   from the old and the new value. nat never checks ihl, so the fixed offsets assume an IPv4 header
   without options; a packet with options would be rewritten in the wrong place. */
#define IP_OFF        ETH_HLEN
#define IP_PROTO_OFF  (IP_OFF + 9)
#define IP_CSUM_OFF   (IP_OFF + 10)
#define IP_SRC_OFF    (IP_OFF + 12)
#define IP_DST_OFF    (IP_OFF + 16)
#define TCP_OFF       (IP_OFF + 20)
#define TCP_SRC_OFF   (TCP_OFF + 0)
#define TCP_DST_OFF   (TCP_OFF + 2)
#define TCP_CSUM_OFF  (TCP_OFF + 16)
#define TCP_FLAGS_OFF (TCP_OFF + 13)
#define TH_FIN 0x01
#define TH_SYN 0x02
#define TH_RST 0x04
#define TH_ACK 0x10

static __always_inline void set_ip(struct __sk_buff *skb, int off, __u32 old, __u32 nw)
{
    bpf_skb_store_bytes(skb, off, &nw, 4, 0);
    bpf_l3_csum_replace(skb, IP_CSUM_OFF, old, nw, 4);
    bpf_l4_csum_replace(skb, TCP_CSUM_OFF, old, nw, 4 | BPF_F_PSEUDO_HDR);
}
static __always_inline void set_port(struct __sk_buff *skb, int off, __u16 old, __u16 nw)
{
    bpf_skb_store_bytes(skb, off, &nw, 2, 0);
    bpf_l4_csum_replace(skb, TCP_CSUM_OFF, old, nw, 2);
}

/* ---- NAT port allocation ----
   Why: the worker tells connections apart by the source port it sees, so each one needs its own
   port on that worker. The BPF_NOEXIST insert is the claim, so two CPUs cannot win the same port.
   Ports are walked, not drawn at random, so a port the worker still holds in TIME_WAIT is reused as
   late as possible. Function ports are skipped, or the worker's reply would look like a new client
   connection; they are assumed to be one block of up to 64 (the fnports size), so after a hit the
   search jumps past it. */
static __always_inline int alloc_nat(struct natkey *nk, struct flowval *fv)
{
    __u32 wid = fv->wid;
    __u32 *next = bpf_map_lookup_elem(&wnext, &wid);
    if (!next)
        return -1;
#pragma unroll
    for (int i = 0; i < 16; i++) {
        __u16 p = NAT_PORT_BASE + (__u16)(__sync_fetch_and_add(next, 1) % NAT_PORT_SPAN);
        __u16 np = bpf_htons(p);
        if (bpf_map_lookup_elem(&fnports, &np)) {
            __sync_fetch_and_add(next, 64);
            continue;
        }
        nk->nat_port = np;
        if (bpf_map_update_elem(&flow, nk, fv, BPF_NOEXIST) == 0)
            return 0;
    }
    return -1;
}

/* ---- Free slots ----
   Why: a report cannot show a full accept queue, so a worker under a refusal penalty counts as
   having no free slots. consume takes the slot right away so a SYN on another CPU does not take it
   too; the check and the decrement are separate steps, so two CPUs can both take the last slot,
   which the signed slots absorb. */
static __always_inline __u32 wslots(__u32 fn_hash, __u32 id, __u64 now)
{
    __u64 *until = bpf_map_lookup_elem(&wpenalty, &id);
    if (until && now < *until) {
        bump(8);
        return 0;
    }
    struct sig_key k = { .fn_hash = fn_hash, .worker_id = id };
    struct worker_state *ws = bpf_map_lookup_elem(&idle_map, &k);
    if (ws && ws->slots > 0 && now - ws->last_seen_ns < STALE_NS)
        return (__u32)ws->slots;
    return 0;
}

static __always_inline void consume(__u32 fn_hash, __u32 id)
{
    struct sig_key k = { .fn_hash = fn_hash, .worker_id = id };
    struct worker_state *ws = bpf_map_lookup_elem(&idle_map, &k);
    if (ws && ws->slots > 0)
        __sync_fetch_and_add(&ws->slots, -1);
}

/* ---- Close tracking ----
   Why: a connection may be forgotten only once both FINs are sent and acknowledged (matched by ack
   number), or the last ACK finds no entry and is not rewritten. Once both sides have sent FIN
   neither sends more data, so the connection stops counting as load then, before the last ACK.
   The bits are set atomically because the two directions can run on different CPUs. */
static __always_inline __u32 track_close(struct __sk_buff *skb, struct flowval *fv, __u8 flags,
                                         __u32 from_worker)
{
    __u32 seq = 0, ack = 0, add = 0, peer = !from_worker;
    if (flags & TH_FIN) {
        __u16 totlen = 0;
        __u8 doff = 0;
        bpf_skb_load_bytes(skb, TCP_OFF + 4, &seq, 4);
        bpf_skb_load_bytes(skb, IP_OFF + 2, &totlen, 2);
        bpf_skb_load_bytes(skb, TCP_OFF + 12, &doff, 1);
        fv->fin[from_worker] = bpf_ntohl(seq) + bpf_ntohs(totlen) - 20 - (doff >> 4) * 4 + 1;
        add = from_worker ? ST_FIN_W : ST_FIN_C;
    }
    bpf_skb_load_bytes(skb, TCP_OFF + 8, &ack, 4);
    if ((flags & TH_ACK) && ((fv->state | add) & (peer ? ST_FIN_W : ST_FIN_C)) &&
        bpf_ntohl(ack) == fv->fin[peer])
        add |= peer ? ST_ACK_W : ST_ACK_C;
    if (!add)
        return 0;
    __u64 st = __sync_fetch_and_or(&fv->state, add) | add;
    if ((st & (ST_FIN_C | ST_FIN_W)) == (ST_FIN_C | ST_FIN_W))
        unload(fv);
    if ((st & ST_CLOSED) != ST_CLOSED)
        return 0;
    bump(12);
    return 1;
}

/* ---- Settings and load lookups ----
   Why: settings live in cfg rather than constants, so the loader can change them per run without a
   rebuild. The loader writes every entry; only the penalty has a built-in default for 0. wload
   reads a negative count as 0, since cast to unsigned it would look like a huge load. */
static __always_inline __u32 wload(__u32 id)
{
    __s64 *l = bpf_map_lookup_elem(&wflows, &id);
    return (l && *l > 0) ? (__u32)*l : 0;
}

static __always_inline __u32 pick_strategy(void)
{
    __u32 one = 1;
    __u32 *s = bpf_map_lookup_elem(&cfg, &one);
    return s ? *s : 0;
}

static __always_inline __u32 pick_fallback(void)
{
    __u32 two = 2;
    __u32 *f = bpf_map_lookup_elem(&cfg, &two);
    return f ? *f : 0;
}

static __always_inline __u32 rst_feedback(void)
{
    __u32 three = 3;
    __u32 *f = bpf_map_lookup_elem(&cfg, &three);
    return f ? *f : 0;
}

static __always_inline __u32 fin_reclaim(void)
{
    __u32 six = 6;
    __u32 *v = bpf_map_lookup_elem(&cfg, &six);
    return v ? *v : 0;
}

static __always_inline __u16 service_port(void)
{
    __u32 four = 4;
    __u32 *v = bpf_map_lookup_elem(&cfg, &four);
    return v ? (__u16)*v : 0;
}

static __always_inline __u64 penalty_ns(void)
{
    __u32 five = 5;
    __u32 *v = bpf_map_lookup_elem(&cfg, &five);
    return (v && *v) ? (__u64)(*v) * 1000000ULL : PENALTY_NS;
}

/* ---- Refusal feedback ----
   Why: a full accept queue does not show in the signal, so a worker that refuses connections would
   keep being picked. A worker answers a full queue with a RST only if it sets
   tcp_abort_on_overflow=1; by default Linux silently drops the handshake's last ACK and the client
   retries, so this never fires. A worker RST is either such a refusal or an abortive close; a
   refusal comes before any response byte, so a RST before one and within REFUSE_FRESH_NS counts as
   one. Refusals are counted even with the feedback off, so runs with and without it stay
   comparable. The penalty is per worker because all functions share the worker's port and accept
   queue, and it expires on its own because a recovered worker sends no signal that it recovered. */
static __always_inline void refused(__u32 wip, __u16 wport, __u8 saw, __u64 opened_ns, __u64 now)
{
    if (saw || now - opened_ns > REFUSE_FRESH_NS) {
        bump(6);
        return;
    }
    bump(4);
    if (!rst_feedback())
        return;
    __u32 id, hit = 0;
#pragma unroll
    for (id = 1; id <= N_WORKERS; id++) {
        __u32 w = id;
        struct endpoint *e = bpf_map_lookup_elem(&workers, &w);
        if (!hit && e && e->ip == wip && e->port == wport)
            hit = id;
    }
    if (!hit)
        return;
    __u64 until = now + penalty_ns();
    bpf_map_update_elem(&wpenalty, &hit, &until, BPF_ANY);
}

/* ---- Worker pick ----
   Why: this is the pull decision - a request goes first to a worker that announced a free
   instance of its function, and that slot is consumed so the next request does not take it too.
   cfg[1] chooses among free workers: 0 weighted random, 1 P2C, 2 JSQ, 3 ordered (the first in the
   function's own hash order, which keeps a function on as few workers as its load needs).
   The kernel cannot hold a SYN back until a worker is free, so when the strategy finds none free
   (P2C looks at only two) cfg[2] still picks one: 0 random, 1 hashed home, 2 two hashed homes,
   3 least-loaded (from a random start so ties spread), 4 the hashed home while it holds fewer
   than ceil(1.25 x mean) connections, otherwise the next worker after it under that bound
   (CH-BL). Penalised workers are skipped to avoid another refusal; if all are penalised, sending
   beats dropping. */
static __always_inline __u32 pick_worker(__u32 fn_hash)
{
    __u64 now = bpf_ktime_get_ns();
    __u32 strat = pick_strategy();
    __u32 id, best = 0;

    if (strat == 1) {
        __u32 a = bpf_get_prandom_u32() % N_WORKERS + 1;
        __u32 b = bpf_get_prandom_u32() % N_WORKERS + 1;
        __u32 sa = wslots(fn_hash, a, now), sb = wslots(fn_hash, b, now);
        best = (sa >= sb) ? a : b;
        if ((sa >= sb ? sa : sb) == 0)
            best = 0;
    } else if (strat == 2) {
        __u32 bs = 0;
#pragma unroll
        for (id = 1; id <= N_WORKERS; id++) {
            __u32 s = wslots(fn_hash, id, now);
            if (s > 0 && (best == 0 || s > bs)) {
                best = id;
                bs = s;
            }
        }
    } else if (strat == 3) {
#pragma unroll
        for (id = 0; id < N_WORKERS; id++) {
            __u32 cand = (fn_hash + id) % N_WORKERS + 1;
            if (!best && wslots(fn_hash, cand, now) > 0)
                best = cand;
        }
    } else {
        __u32 slots[N_WORKERS + 1];
        __u32 total = 0;
        __builtin_memset(slots, 0, sizeof(slots));
#pragma unroll
        for (id = 1; id <= N_WORKERS; id++) {
            slots[id] = wslots(fn_hash, id, now);
            total += slots[id];
        }
        if (total) {
            __u32 r = bpf_get_prandom_u32() % total, acc = 0;
#pragma unroll
            for (id = 1; id <= N_WORKERS; id++) {
                acc += slots[id];
                if (!best && r < acc)
                    best = id;
            }
        }
    }

    if (best) {
        consume(fn_hash, best);
        return best;
    }
    bump(3);
    __u32 want, fb = pick_fallback();
    if (fb >= 3) {
        __u32 total = 0, bl = 0, cap;
        __u32 start = (fb == 3 ? bpf_get_prandom_u32() : fn_hash) % N_WORKERS;
        if (fb == 4) {
#pragma unroll
            for (id = 1; id <= N_WORKERS; id++)
                total += wload(id);
        }
        cap = (5 * (total + 1) + 4 * N_WORKERS - 1) / (4 * N_WORKERS);
        want = 0;
#pragma unroll
        for (id = 0; id < N_WORKERS; id++) {
            __u32 cand = (start + id) % N_WORKERS + 1;
            __u32 l = wload(cand);
            if (fb == 3 ? (!want || l < bl) : (!want && l < cap)) {
                want = cand;
                bl = l;
            }
        }
        if (!want)
            want = start + 1;
        if (fb == 4 && want != start + 1)
            bump(17);
    } else if (fb == 2) {
        __u32 h1 = fn_hash % N_WORKERS + 1;
        __u32 h2 = (fn_hash / N_WORKERS) % N_WORKERS + 1;
        if (h2 == h1)
            h2 = h1 % N_WORKERS + 1;
        __u32 s1 = wslots(fn_hash, h1, now), s2 = wslots(fn_hash, h2, now);
        if (s1 == s2)
            want = (bpf_get_prandom_u32() & 1) ? h1 : h2;
        else
            want = (s1 > s2) ? h1 : h2;
    } else if (fb == 1) {
        want = fn_hash % N_WORKERS + 1;
    } else {
        want = bpf_get_prandom_u32() % N_WORKERS + 1;
    }
    __u32 free_seen = 0;
#pragma unroll
    for (id = 1; id <= N_WORKERS; id++) {
        __u32 w = id;
        __u64 *u = bpf_map_lookup_elem(&wpenalty, &w);
        if (!(u && now < *u))
            free_seen = 1;
    }
    if (!free_seen)
        return want;
#pragma unroll
    for (id = 0; id < N_WORKERS; id++) {
        __u32 cand = (want - 1 + id) % N_WORKERS + 1;
        __u64 *u = bpf_map_lookup_elem(&wpenalty, &cand);
        if (!(u && now < *u))
            return cand;
    }
    return want;
}

/* ---- Steering (TC program) ----
   Why: TC ingress sees every packet before routing, so a connection is sent to a worker and its
   reply restored without a user-space proxy. Requests and replies arrive at the same hook and only
   the destination tells them apart: a known function address on the service port, or our own
   address plus a known port, is a request; workers always reply to our address and a NAT port,
   which never equals a function port. In address mode a request we cannot steer is dropped, so
   the kernel does not forward it for an address nothing owns. With reclaim on close, a SYN on a
   closing connection is decided again; a SYN on an open one keeps its worker (a retransmit, or a
   reused tuple whose entry was never freed). A FIN seen on the return path is marked in fwd too,
   because the forward path only looks there. */
SEC("tc")
int nat(struct __sk_buff *skb)
{
    __u16 h_proto;
    if (bpf_skb_load_bytes(skb, 12, &h_proto, 2) < 0 || h_proto != bpf_htons(ETH_P_IP))
        return TC_ACT_OK;
    __u8 proto;
    if (bpf_skb_load_bytes(skb, IP_PROTO_OFF, &proto, 1) < 0 || proto != IPPROTO_TCP)
        return TC_ACT_OK;

    __u32 saddr, daddr;
    __u16 sport, dport;
    if (bpf_skb_load_bytes(skb, IP_SRC_OFF, &saddr, 4) < 0 ||
        bpf_skb_load_bytes(skb, IP_DST_OFF, &daddr, 4) < 0 ||
        bpf_skb_load_bytes(skb, TCP_SRC_OFF, &sport, 2) < 0 ||
        bpf_skb_load_bytes(skb, TCP_DST_OFF, &dport, 2) < 0)
        return TC_ACT_OK;

    __u32 zero = 0;
    __u32 *sipp = bpf_map_lookup_elem(&cfg, &zero);
    if (!sipp)
        return TC_ACT_OK;
    __u32 SCHED_IP = *sipp;

    __u32 *fnh = bpf_map_lookup_elem(&fnaddrs, &daddr);
    if (fnh && dport != service_port())
        fnh = NULL;
    __u32 by_addr = fnh ? 1 : 0;
    if (!fnh && daddr == SCHED_IP)
        fnh = bpf_map_lookup_elem(&fnports, &dport);
    if (!fnh && daddr != SCHED_IP)
        return TC_ACT_OK;

    __u8 tcpflags = 0;
    bpf_skb_load_bytes(skb, TCP_FLAGS_OFF, &tcpflags, 1);

    if (fnh) {
        struct fwdkey fk;
        __builtin_memset(&fk, 0, sizeof(fk));
        fk.client_ip = saddr;
        fk.func_addr = daddr;
        fk.client_port = sport;
        fk.func_port = dport;

        struct natkey nk;
        __builtin_memset(&nk, 0, sizeof(nk));
        struct fwdval *known = bpf_map_lookup_elem(&fwd, &fk);
        __u32 over = 0;
        if (known && known->closing && (tcpflags & TH_SYN)) {
            nk = known->nk;
            drop_flow(&fk, &nk);
            known = NULL;
        }
        if (known) {
            nk = known->nk;
            if (tcpflags & TH_SYN)
                bump(11);
            if (fin_reclaim() && (known->closing || (tcpflags & TH_FIN))) {
                struct flowval *fv2 = bpf_map_lookup_elem(&flow, &nk);
                known->closing = 1;
                if (fv2)
                    over = track_close(skb, fv2, tcpflags, 0);
            }
        } else if (tcpflags & TH_SYN) {
            __u32 id = pick_worker(*fnh);
            struct endpoint *e = bpf_map_lookup_elem(&workers, &id);
            if (!e) {
                bump(9);
                bump(13);
                return by_addr ? TC_ACT_SHOT : TC_ACT_OK;
            }
            struct flowval fv;
            __builtin_memset(&fv, 0, sizeof(fv));
            fv.client_ip = saddr;
            fv.func_addr = daddr;
            fv.client_port = sport;
            fv.func_port = dport;
            fv.opened_ns = bpf_ktime_get_ns();
            fv.wid = id;
            nk.worker_ip = e->ip;
            nk.worker_port = e->port;
            if (alloc_nat(&nk, &fv) < 0) {
                bump(9);
                bump(14);
                return by_addr ? TC_ACT_SHOT : TC_ACT_OK;
            }
            struct fwdval fwv = { .nk = nk };
            bpf_map_update_elem(&fwd, &fk, &fwv, BPF_ANY);
            bump(2);
            bump(16);
            __s64 *l = bpf_map_lookup_elem(&wflows, &id);
            if (l)
                __sync_fetch_and_add(l, 1);
            if (tcpflags & TH_SYN)
                bump(10);
        } else {
            bump(9);
            bump(15);
            return by_addr ? TC_ACT_SHOT : TC_ACT_OK;
        }
        set_ip(skb, IP_SRC_OFF, saddr, SCHED_IP);
        set_ip(skb, IP_DST_OFF, daddr, nk.worker_ip);
        set_port(skb, TCP_SRC_OFF, sport, nk.nat_port);
        set_port(skb, TCP_DST_OFF, dport, nk.worker_port);
        if ((tcpflags & TH_RST) || over)
            drop_flow(&fk, &nk);
        bump(0);
        if (by_addr)
            bump(7);
        return bpf_redirect_neigh(skb->ifindex, NULL, 0, 0);
    }

    struct natkey nk;
    __builtin_memset(&nk, 0, sizeof(nk));
    nk.worker_ip = saddr;
    nk.worker_port = sport;
    nk.nat_port = dport;
    struct flowval *fv = bpf_map_lookup_elem(&flow, &nk);
    if (!fv)
        return TC_ACT_OK;
    __u32 cip = fv->client_ip;
    __u32 faddr = fv->func_addr;
    __u16 cport = fv->client_port;
    __u16 fport = fv->func_port;
    __u64 opened = fv->opened_ns;
    __u8 saw = fv->saw_resp;
    __u16 totlen = 0;
    __u8 doff = 0;
    bpf_skb_load_bytes(skb, IP_OFF + 2, &totlen, 2);
    bpf_skb_load_bytes(skb, TCP_OFF + 12, &doff, 1);
    if (!saw && (int)bpf_ntohs(totlen) - 20 - ((doff >> 4) * 4) > 0)
        fv->saw_resp = 1;
    set_ip(skb, IP_SRC_OFF, saddr, faddr);
    set_ip(skb, IP_DST_OFF, daddr, cip);
    set_port(skb, TCP_SRC_OFF, sport, fport);
    set_port(skb, TCP_DST_OFF, dport, cport);
    struct fwdkey fk;
    __builtin_memset(&fk, 0, sizeof(fk));
    fk.client_ip = cip;
    fk.func_addr = faddr;
    fk.client_port = cport;
    fk.func_port = fport;
    __u32 over = 0;
    if (fin_reclaim() && (fv->state || (tcpflags & TH_FIN))) {
        if ((tcpflags & TH_FIN) && !fv->state) {
            struct fwdval *fw = bpf_map_lookup_elem(&fwd, &fk);
            if (fw)
                fw->closing = 1;
        }
        over = track_close(skb, fv, tcpflags, 1);
    }
    if (tcpflags & TH_RST)
        refused(saddr, sport, saw, opened, bpf_ktime_get_ns());
    if ((tcpflags & TH_RST) || over)
        drop_flow(&fk, &nk);
    bump(1);
    return bpf_redirect_neigh(skb->ifindex, NULL, 0, 0);
}

char _license[] SEC("license") = "GPL";
