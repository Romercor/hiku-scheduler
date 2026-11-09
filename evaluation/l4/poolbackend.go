// Like fastbackend.go, but a function owns a pool of instances, for the concurrency test.
// GET /stats returns: requests cold_starts instance_seconds
// args: port name sched_ip[,sched_ip...] worker_id [warm_ms cold_ms keep_s conc coalesce_ms refresh_ms]
package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

const sigMagic = 0x484B

type inst struct {
	active   int
	started  bool
	idleFrom time.Time
}

type fnState struct {
	name  string
	hash  uint32
	dirty bool
	insts []*inst
}

var (
	name, self, sched0 string
	wid                uint32
	warm, cold, keep   time.Duration
	conc               int
	coalesce, refresh  time.Duration
	conns              []net.Conn
	mu                 sync.Mutex
	fns                = map[string]*fnState{}
	requests, colds    int
	instSeconds        float64
)

func fnv1a(s string) uint32 {
	h := uint32(0x811c9dc5)
	for i := 0; i < len(s); i++ {
		h ^= uint32(s[i])
		h *= 0x01000193
	}
	return h
}

// report and mark are called with mu held
func report(st *fnState) {
	slots := 0
	for _, in := range st.insts {
		if in.started {
			slots += conc - in.active
		}
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
	st.dirty = true
}

func tick() {
	const step = 10 * time.Millisecond
	lastSig, lastFull := time.Now(), time.Now()
	for now := range time.Tick(step) {
		sig := coalesce > 0 && now.Sub(lastSig) >= coalesce
		full := refresh > 0 && now.Sub(lastFull) >= refresh
		if sig {
			lastSig = now
		}
		if full {
			lastFull = now
		}
		mu.Lock()
		for _, st := range fns {
			kept := st.insts[:0]
			for _, in := range st.insts {
				if in.started && in.active == 0 && now.Sub(in.idleFrom) > keep {
					st.dirty = true
					go destroyed(st.name)
					continue
				}
				kept = append(kept, in)
			}
			st.insts = kept
			instSeconds += float64(len(kept)) * step.Seconds()
			if full || (st.dirty && (sig || coalesce == 0)) {
				st.dirty = false
				report(st)
			}
		}
		mu.Unlock()
	}
}

func destroyed(fn string) {
	body := fmt.Sprintf(`{"host": "%s"}`, self)
	resp, err := http.Post("http://"+sched0+":9020/destroySandbox/"+fn, "application/json", bytes.NewBufferString(body))
	if err == nil {
		resp.Body.Close()
	}
}

func handle(w http.ResponseWriter, r *http.Request) {
	fn := r.URL.Path[strings.LastIndexByte(r.URL.Path, '/')+1:]
	if fn == "stats" {
		mu.Lock()
		fmt.Fprintf(w, "%d %d %.1f\n", requests, colds, instSeconds)
		mu.Unlock()
		return
	}

	mu.Lock()
	st := fns[fn]
	if st == nil {
		st = &fnState{name: fn, hash: fnv1a(fn)}
		fns[fn] = st
	}
	var in *inst
	for _, c := range st.insts {
		if c.started && c.active < conc && (in == nil || c.active > in.active) {
			in = c
		}
	}
	isWarm := in != nil
	if !isWarm {
		in = &inst{}
		st.insts = append(st.insts, in)
		colds++
	}
	in.active++
	requests++
	mark(st)
	mu.Unlock()

	d := warm
	if !isWarm {
		d += cold
	}
	time.Sleep(d)

	mu.Lock()
	in.active--
	in.started = true
	in.idleFrom = time.Now()
	mark(st)
	mu.Unlock()

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
	warm = time.Duration(arg(5, 50) * float64(time.Millisecond))
	cold = time.Duration(arg(6, 250) * float64(time.Millisecond))
	keep = time.Duration(arg(7, 10) * float64(time.Second))
	conc = int(arg(8, 1))
	coalesce = time.Duration(arg(9, 0)) * time.Millisecond
	refresh = time.Duration(arg(10, 0)) * time.Millisecond

	for _, s := range strings.Split(os.Args[3], ",") {
		c, err := net.Dial("udp", s+":9020")
		if err != nil {
			log.Fatalf("dial %s: %v", s, err)
		}
		conns = append(conns, c)
	}
	sched0 = strings.Split(os.Args[3], ",")[0]
	host, _, _ := net.SplitHostPort(conns[0].LocalAddr().String())
	self = host + ":" + port
	go tick()

	srv := &http.Server{Addr: ":" + port, Handler: http.HandlerFunc(handle),
		ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, ErrorLog: log.New(os.Stderr, "", 0)}
	fmt.Printf("%s :%s wid=%d warm=%v cold=%v keep=%v conc=%d coalesce=%v refresh=%v\n",
		name, port, wid, warm, cold, keep, conc, coalesce, refresh)
	log.Fatal(srv.ListenAndServe())
}
