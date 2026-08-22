// SPDX-License-Identifier: GPL-2.0
//
// L4 pull-based steering, entirely in-kernel. Two programs share idle_map:
//   * availability (XDP): ingests worker FREE/BUSY UDP signals -> idle_map   (Bar 1)
//   * nat (TC ingress):   at a new connection, picks a FREE worker for the
//                         function (= dst port) from idle_map, then NATs the
//                         client<->worker packets                            (Bar 2)
// No userspace proxy, no socket pairing.

#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/in.h>
#include <linux/udp.h>
#include <linux/tcp.h>
#include <linux/pkt_cls.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>

/* ---- availability signal (Bar 1) ---- */
#define SIG_MAGIC 0x484B /* "HK" */
#define SIG_PORT  9020
#define SIG_LEN   15

struct sig_key {
    __u32 fn_hash;
    __u32 worker_id;
};
struct worker_state {
    __u32 slots; /* available concurrent execution slots for this fn (0 = busy) */
    __u64 last_seen_ns;
};

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __type(key, struct sig_key);
    __type(value, struct worker_state);
    __uint(max_entries, 4096);
} idle_map SEC(".maps");

/* ---- steering config/state (Bar 2) ---- */
/* function identity = scheduler dst port; the loader fills fnports (port -> fn_hash).
   this scheduler's own IP (network order) lives in cfg[0], set by the loader. */
#ifndef N_WORKERS
#define N_WORKERS   3
#endif
#define STALE_NS    3000000000ULL         /* drop a worker not heard from in 3s */

struct endpoint {
    __u32 ip;   /* network order */
    __u16 port; /* network order */
};
struct flowval {
    __u32 client_ip;
    __u32 worker_ip;
    __u16 worker_port;
    __u16 func_port;   /* scheduler port the client hit; restored on the return path */
};

/* worker_id -> endpoint, populated by the loader */
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __type(key, __u32);
    __type(value, struct endpoint);
    __uint(max_entries, 8);
} workers SEC(".maps");

/* scheduler dst port -> fn_hash, populated by the loader */
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __type(key, __u16);
    __type(value, __u32);
    __uint(max_entries, 64);
} fnports SEC(".maps");

/* cfg[0] = this scheduler's own IP (network order); cfg[1] = pick strategy
   (0 weighted-random, 1 P2C, 2 JSQ). Set by the loader. */
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __type(key, __u32);
    __type(value, __u32);
    __uint(max_entries, 4);
} cfg SEC(".maps");

/* nat-port (client source port) -> flow */
struct {
    __uint(type, BPF_MAP_TYPE_LRU_HASH);
    __type(key, __u16);
    __type(value, struct flowval);
    __uint(max_entries, 65536);
} flow SEC(".maps");

/* stats: [0]=forward [1]=return [2]=flows [3]=no-free-fallback */
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __type(key, __u32);
    __type(value, __u64);
    __uint(max_entries, 4);
} nat_stats SEC(".maps");

static __always_inline void bump(__u32 i)
{
    __u64 *v = bpf_map_lookup_elem(&nat_stats, &i);
    if (v)
        __sync_fetch_and_add(v, 1);
}

/* ---------- Bar 1: availability ingest ---------- */
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
    struct worker_state st = { .slots = slots, .last_seen_ns = bpf_ktime_get_ns() };
    bpf_map_update_elem(&idle_map, &key, &st, BPF_ANY);
    return XDP_DROP;
}

/* ---------- Bar 2: NAT steering ---------- */
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

/* free, non-stale slots for {fn, worker}, else 0 */
static __always_inline __u32 wslots(__u32 fn_hash, __u32 id, __u64 now)
{
    struct sig_key k = { .fn_hash = fn_hash, .worker_id = id };
    struct worker_state *ws = bpf_map_lookup_elem(&idle_map, &k);
    if (ws && ws->slots > 0 && now - ws->last_seen_ns < STALE_NS)
        return ws->slots;
    return 0;
}
static __always_inline void consume(__u32 fn_hash, __u32 id)
{
    struct sig_key k = { .fn_hash = fn_hash, .worker_id = id };
    struct worker_state *ws = bpf_map_lookup_elem(&idle_map, &k);
    if (ws && ws->slots > 0)
        ws->slots--;
}

static __always_inline __u32 pick_strategy(void)
{
    __u32 one = 1;
    __u32 *s = bpf_map_lookup_elem(&cfg, &one);
    return s ? *s : 0;
}

/* pull: pick a non-stale worker with free slots and consume one (JIQ pop, generalized to
   concurrency C). Strategy (cfg[1]): 0 weighted-random (roulette, load-aware but decorrelated),
   1 P2C (sample 2, take more slots), 2 JSQ (strict most-slots). No free slot -> random. */
static __always_inline __u32 pick_worker(__u32 fn_hash)
{
    __u64 now = bpf_ktime_get_ns();
    __u32 strat = pick_strategy();
    __u32 id, best = 0;

    if (strat == 1) {                       /* P2C */
        __u32 a = bpf_get_prandom_u32() % N_WORKERS + 1;
        __u32 b = bpf_get_prandom_u32() % N_WORKERS + 1;
        __u32 sa = wslots(fn_hash, a, now), sb = wslots(fn_hash, b, now);
        best = (sa >= sb) ? a : b;
        if ((sa >= sb ? sa : sb) == 0)
            best = 0;
    } else if (strat == 2) {                /* JSQ: strict most free slots */
        __u32 bs = 0;
#pragma unroll
        for (id = 1; id <= N_WORKERS; id++) {
            __u32 s = wslots(fn_hash, id, now);
            if (s > 0 && (best == 0 || s > bs)) {
                best = id;
                bs = s;
            }
        }
    } else {                                /* weighted-random (roulette) */
        __u32 total = 0;
#pragma unroll
        for (id = 1; id <= N_WORKERS; id++)
            total += wslots(fn_hash, id, now);
        if (total) {
            __u32 r = bpf_get_prandom_u32() % total, acc = 0;
#pragma unroll
            for (id = 1; id <= N_WORKERS; id++) {
                acc += wslots(fn_hash, id, now);
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
    return bpf_get_prandom_u32() % N_WORKERS + 1;
}

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

    if (daddr != SCHED_IP)
        return TC_ACT_OK;

    __u8 tcpflags = 0;
    bpf_skb_load_bytes(skb, TCP_FLAGS_OFF, &tcpflags, 1);

    /* forward: client -> scheduler:<function port> */
    __u32 *fnh = bpf_map_lookup_elem(&fnports, &dport);
    if (fnh) {
        __u16 natport = sport;
        struct flowval *fv = bpf_map_lookup_elem(&flow, &natport);
        __u32 wip;
        __u16 wport;
        if (fv) {
            wip = fv->worker_ip;
            wport = fv->worker_port;
        } else if (!(tcpflags & 0x04)) {
            __u32 id = pick_worker(*fnh);
            struct endpoint *e = bpf_map_lookup_elem(&workers, &id);
            if (!e)
                return TC_ACT_OK;
            struct flowval nf = { .client_ip = saddr, .worker_ip = e->ip,
                                  .worker_port = e->port, .func_port = dport };
            bpf_map_update_elem(&flow, &natport, &nf, BPF_ANY);
            wip = e->ip;
            wport = e->port;
            bump(2);
        } else {
            return TC_ACT_OK; /* stray RST, no flow */
        }
        set_ip(skb, IP_SRC_OFF, saddr, SCHED_IP);
        set_ip(skb, IP_DST_OFF, daddr, wip);
        set_port(skb, TCP_DST_OFF, dport, wport);
        if (tcpflags & 0x04)
            bpf_map_delete_elem(&flow, &natport);
        bump(0);
        return bpf_redirect_neigh(skb->ifindex, NULL, 0, 0);
    }

    /* return: worker -> scheduler:natport */
    __u16 natport = dport;
    struct flowval *fv = bpf_map_lookup_elem(&flow, &natport);
    if (!fv || saddr != fv->worker_ip || sport != fv->worker_port)
        return TC_ACT_OK;
    __u32 cip = fv->client_ip;
    __u16 fport = fv->func_port;
    set_ip(skb, IP_SRC_OFF, saddr, SCHED_IP);
    set_ip(skb, IP_DST_OFF, daddr, cip);
    set_port(skb, TCP_SRC_OFF, sport, fport);
    if (tcpflags & 0x04)
        bpf_map_delete_elem(&flow, &natport);
    bump(1);
    return bpf_redirect_neigh(skb->ifindex, NULL, 0, 0);
}

char _license[] SEC("license") = "GPL";
