package lambda

import (
	"encoding/binary"
	"net"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/open-lambda/open-lambda/ol/common"
)

// ---- Availability signal ----
// Why: at L4 the scheduler leaves the data path, so it can no longer see a request finish. Each
// worker therefore announces how many idle instances it holds per function, in a small UDP
// datagram that the scheduler's XDP program stores without any process involved. The scheduler
// takes a slot from that count for each connection it sends on an announced slot, and the next
// report replaces the count. Wire format, big endian: magic(2) | op(1) | worker_id(4) | fn_hash(4) | slots(4).
const (
	sigMagic = 0x484B
	sigOp    = 1
	sigLen   = 15
)

var (
	sigMu       sync.Mutex
	sigIdle     = map[string]int{}
	sigDirty    = map[string]bool{}
	sigOnce     sync.Once
	sigConns    []*net.UDPConn
	sigWid      uint32
	sigRefresh  time.Duration
	sigCoalesce time.Duration
)

// ---- Function hash ----
// Why: the scheduler's loader hashes function names with the same FNV-1a, so worker and scheduler
// agree on a function without sending its name, and every datagram has the same fixed size.
func fnv1a(s string) uint32 {
	h := uint32(0x811c9dc5)
	for i := 0; i < len(s); i++ {
		h ^= uint32(s[i])
		h *= 0x01000193
	}
	return h
}

// ---- Setup ----
// Why: the scheduler numbers workers by their position in its list, and our configs put worker i
// on port 5000+i, so the id is derived from the port; a port below 5000 sends nothing rather than
// a wrong id. Every scheduler keeps its own availability map, so each listed peer gets every
// signal.
func sigInit() {
	port, err := strconv.Atoi(common.Conf.Worker_port)
	if err != nil || port < 5000 {
		return
	}
	peers := []string{net.JoinHostPort(common.Conf.Scheduler_url, common.Conf.Scheduler_port)}
	if p := strings.TrimSpace(common.Conf.Scheduler_peers); p != "" {
		peers = strings.Split(p, ",")
	}
	for _, peer := range peers {
		addr, err := net.ResolveUDPAddr("udp", strings.TrimSpace(peer))
		if err != nil {
			continue
		}
		conn, err := net.DialUDP("udp", nil, addr)
		if err != nil {
			continue
		}
		sigConns = append(sigConns, conn)
	}
	sigWid = uint32(port - 5000 + 1)

	sigRefresh = time.Duration(common.Conf.Signal_refresh_ms) * time.Millisecond
	sigCoalesce = time.Duration(common.Conf.Signal_coalesce_ms) * time.Millisecond
	if sigRefresh > 0 || sigCoalesce > 0 {
		go sigTick()
	}
}

// ---- Sending ----
// Why: coalescing keeps control traffic from growing with the request rate, and the refresh
// resends every function because a datagram is never acknowledged. A non-positive interval would
// panic the ticker and kill the worker, so it returns early.
func sigTick() {
	every := sigCoalesce
	if every == 0 || (sigRefresh > 0 && sigRefresh < every) {
		every = sigRefresh
	}
	if every <= 0 {
		return
	}
	type entry struct {
		name  string
		slots int
	}
	var due []entry
	last := time.Now()
	t := time.NewTicker(every)
	defer t.Stop()
	for range t.C {
		full := sigRefresh > 0 && time.Since(last) >= sigRefresh
		if full {
			last = time.Now()
		}
		due = due[:0]
		sigMu.Lock()
		for name, slots := range sigIdle {
			dirty := sigDirty[name]
			delete(sigDirty, name)
			if full || dirty {
				due = append(due, entry{name, slots})
			}
			if full && slots == 0 && !dirty {
				delete(sigIdle, name)
			}
		}
		sigMu.Unlock()
		for _, e := range due {
			sigSend(e.name, e.slots)
		}
	}
}

func sigSend(name string, slots int) {
	var pkt [sigLen]byte
	binary.BigEndian.PutUint16(pkt[0:], sigMagic)
	pkt[2] = sigOp
	binary.BigEndian.PutUint32(pkt[3:], sigWid)
	binary.BigEndian.PutUint32(pkt[7:], fnv1a(name))
	binary.BigEndian.PutUint32(pkt[11:], uint32(slots))
	for _, c := range sigConns {
		c.Write(pkt[:])
	}
}

// ---- Counting idle instances ----
// Why: the worker's server also reads the count (Close_when_busy), so it is kept even with no
// scheduler to send to. Only state changes are reported, so an instance counts at most once, and
// only while it holds a sandbox, since a new one would take the request as a cold start.
func SigIdle(name string) int {
	sigMu.Lock()
	defer sigMu.Unlock()
	return sigIdle[name]
}

func sigReport(name string, delta int) {
	sigOnce.Do(sigInit)

	sigMu.Lock()
	slots := sigIdle[name] + delta
	if slots < 0 {
		slots = 0
	}
	sigIdle[name] = slots
	if len(sigConns) == 0 {
		sigMu.Unlock()
		return
	}
	if sigCoalesce > 0 {
		sigDirty[name] = true
		sigMu.Unlock()
		return
	}
	sigMu.Unlock()

	sigSend(name, slots)
}

func sigSetIdle(name string, cur *bool, idle bool) {
	if *cur == idle {
		return
	}
	*cur = idle
	if idle {
		sigReport(name, 1)
	} else {
		sigReport(name, -1)
	}
}
