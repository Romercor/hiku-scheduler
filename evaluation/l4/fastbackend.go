// Synthetic worker with warm and cold execution times, in Go so that it does not saturate before
// the scheduler and hide its knee.
// args: port name sched_ip[,sched_ip...] worker_id [warm_ms cold_ms keep_s conc coalesce_ms refresh_ms]
package main

import (
	"encoding/binary"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const sigMagic = 0x484B

var (
	name              string
	wid               uint32
	warm, cold, keep  time.Duration
	conc              int64
	coalesce, refresh time.Duration
	conns             []net.Conn
	mu                sync.RWMutex
	fns               = map[string]*fnState{}
)

type fnState struct {
	hash     uint32
	dirty    int32
	active   int64
	lastDone int64
	sem      chan struct{}
}

func fnv1a(s string) uint32 {
	h := uint32(0x811c9dc5)
	for i := 0; i < len(s); i++ {
		h ^= uint32(s[i])
		h *= 0x01000193
	}
	return h
}

func get(fn string) *fnState {
	mu.RLock()
	st := fns[fn]
	mu.RUnlock()
	if st != nil {
		return st
	}
	mu.Lock()
	defer mu.Unlock()
	if st = fns[fn]; st != nil {
		return st
	}
	st = &fnState{hash: fnv1a(fn), sem: make(chan struct{}, conc)}
	fns[fn] = st
	return st
}

func report(st *fnState) {
	slots := conc - atomic.LoadInt64(&st.active)
	if slots < 0 {
		slots = 0
	}
	var b [15]byte
	binary.BigEndian.PutUint16(b[0:], sigMagic)
	b[2] = 1
	binary.BigEndian.PutUint32(b[3:], wid)
	binary.BigEndian.PutUint32(b[7:], st.hash)
	binary.BigEndian.PutUint32(b[11:], uint32(slots))
	for _, c := range conns {
		c.Write(b[:])
	}
}

func mark(st *fnState) {
	if coalesce == 0 {
		report(st)
		return
	}
	atomic.StoreInt32(&st.dirty, 1)
}

func tick() {
	every := coalesce
	if every == 0 || (refresh > 0 && refresh < every) {
		every = refresh
	}
	if every <= 0 {
		return
	}
	last := time.Now()
	for range time.Tick(every) {
		full := refresh > 0 && time.Since(last) >= refresh
		if full {
			last = time.Now()
		}
		mu.RLock()
		for _, st := range fns {
			d := atomic.SwapInt32(&st.dirty, 0) == 1
			if full || d {
				report(st)
			}
		}
		mu.RUnlock()
	}
}

func handle(w http.ResponseWriter, r *http.Request) {
	fn := r.URL.Path
	if i := strings.LastIndexByte(fn, '/'); i >= 0 {
		fn = fn[i+1:]
	}
	if fn == "" {
		fn = "unknown"
	}
	st := get(fn)
	st.sem <- struct{}{}
	defer func() { <-st.sem }()

	now := time.Now()
	isWarm := now.UnixNano()-atomic.LoadInt64(&st.lastDone) < int64(keep)
	atomic.AddInt64(&st.active, 1)
	mark(st)
	d := warm
	if !isWarm {
		d += cold
	}
	if d > 0 {
		time.Sleep(d)
	}
	atomic.StoreInt64(&st.lastDone, time.Now().UnixNano())
	atomic.AddInt64(&st.active, -1)
	mark(st)

	state := "cold"
	if isWarm {
		state = "warm"
	}
	body := name + " " + fn + " " + state + "\n"
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.Write([]byte(body))
}

func arg(i int, def float64) float64 {
	if len(os.Args) > i && os.Args[i] != "" {
		v, err := strconv.ParseFloat(os.Args[i], 64)
		if err == nil {
			return v
		}
	}
	return def
}

func main() {
	if len(os.Args) < 5 {
		log.Fatal("args: port name sched[,sched] wid [warm_ms cold_ms keep_s conc coalesce_ms refresh_ms]")
	}
	port := os.Args[1]
	name = os.Args[2]
	id, _ := strconv.Atoi(os.Args[4])
	wid = uint32(id)
	warm = time.Duration(arg(5, 5) * float64(time.Millisecond))
	cold = time.Duration(arg(6, 200) * float64(time.Millisecond))
	keep = time.Duration(arg(7, 10) * float64(time.Second))
	conc = int64(arg(8, 1))
	coalesce = time.Duration(arg(9, 0)) * time.Millisecond
	refresh = time.Duration(arg(10, 0)) * time.Millisecond

	for _, s := range strings.Split(os.Args[3], ",") {
		c, err := net.Dial("udp", s+":9020")
		if err != nil {
			log.Fatalf("dial %s: %v", s, err)
		}
		conns = append(conns, c)
	}
	if coalesce > 0 || refresh > 0 {
		go tick()
	}

	srv := &http.Server{Addr: ":" + port, Handler: http.HandlerFunc(handle),
		ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, ErrorLog: log.New(os.Stderr, "", 0)}
	fmt.Printf("%s :%s wid=%d warm=%v cold=%v keep=%v conc=%d coalesce=%v refresh=%v\n",
		name, port, wid, warm, cold, keep, conc, coalesce, refresh)
	log.Fatal(srv.ListenAndServe())
}
