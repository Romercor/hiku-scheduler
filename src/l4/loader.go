// Package l4 is the user-space side of the L4 scheduler. It reads the JSON config, loads the two
// eBPF programs of bpf/scheduler.bpf.c, fills their maps, attaches them to the network interface
// and then only prints counters, so no request ever passes through this process. In the kernel,
// a client connects to a function's address, the nat program picks a worker that announced a free
// instance and rewrites the connection to it, and the availability program stores the workers'
// announcements (signal.go).
package l4

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/cilium/ebpf"
	"github.com/cilium/ebpf/link"
	"github.com/cilium/ebpf/rlimit"
)

// ---- Kernel-side values ----
// Why: map values are copied into the kernel as raw bytes, so endpoint repeats the C struct
// endpoint including its padding. objPath is where setup_l4.sh installs the compiled program.
const objPath = "/app/scheduler.bpf.o"

type fn struct {
	name string
	port uint16
}

type fnAddr struct {
	name string
	addr uint32
}

type endpoint struct {
	IP   uint32
	Port uint16
	_    uint16
}

// ---- Config ----
// Why: the JSON is converted once at start, so a malformed entry stops the scheduler before
// anything is attached, and an unknown strategy name panics instead of running another one.
type JSONConfig struct {
	Iface         string   `json:"iface"`
	Host          string   `json:"host"`
	Strategy      string   `json:"strategy"`
	Fallback      string   `json:"fallback"`
	Refused       bool     `json:"rst_feedback"`
	PenaltyMs     uint32   `json:"penalty_ms"`
	Workers       []string `json:"workers"`
	Functions     []string `json:"functions"`
	FunctionAddrs []string `json:"function_addrs"`
	ServicePort   int      `json:"service_port"`
	SyntheticFns  int      `json:"synthetic_fns"`
	FinReclaim    bool     `json:"fin_reclaim"`
}

type Config struct {
	Iface     string
	SchedIP   uint32
	Strategy  uint32
	Fallback  uint32
	Refused   uint32
	Penalty   uint32
	SvcPort   uint16
	Synthetic int
	FinRec    uint32
	Workers   []endpoint
	Funcs     []fn
	FuncAddrs []fnAddr
}

func (c JSONConfig) ToConfig() Config {
	return Config{
		Iface:     c.Iface,
		SchedIP:   hostIP(c.Host),
		Strategy:  strategyFromConfig(c),
		Fallback:  fallbackFromConfig(c),
		Refused:   boolToU32(c.Refused),
		Penalty:   c.PenaltyMs,
		SvcPort:   uint16(c.ServicePort),
		Synthetic: c.SyntheticFns,
		FinRec:    boolToU32(c.FinReclaim),
		Workers:   parseWorkers(c.Workers),
		Funcs:     parseFuncs(c.Functions),
		FuncAddrs: parseFuncAddrs(c.FunctionAddrs),
	}
}

func LoadConfigFromFile(configFilepath string) JSONConfig {
	var config JSONConfig

	file, rfErr := os.ReadFile(configFilepath)
	if rfErr != nil {
		log.Fatalf("Cannot read config file (%s)", rfErr)
	}

	decoder := json.NewDecoder(bytes.NewReader(file))
	jsonErr := decoder.Decode(&config)
	if jsonErr != nil {
		log.Fatalf("Config file Ill-formed (%s)", jsonErr)
	}

	return config
}

func strategyFromConfig(c JSONConfig) uint32 {
	switch c.Strategy {
	case "weighted-random":
		return 0
	case "p2c":
		return 1
	case "jsq":
		return 2
	case "", "ordered":
		return 3
	}

	panic("Unknown strategy: " + c.Strategy)
}

func fallbackFromConfig(c JSONConfig) uint32 {
	switch c.Fallback {
	case "random":
		return 0
	case "hashed":
		return 1
	case "hashed2":
		return 2
	case "", "least-loaded":
		return 3
	case "bounded":
		return 4
	}

	panic("Unknown fallback: " + c.Fallback)
}

func boolToU32(b bool) uint32 {
	if b {
		return 1
	}
	return 0
}

// ---- Byte order and hashing ----
// Why: the kernel program compares addresses and ports in network order, but cilium/ebpf writes
// map keys and values in host order, so addresses and ports are byte-swapped here first; the
// swap assumes a little-endian host. fnv1a must match the one in the worker's signal.go exactly,
// since the function hash is the only thing the worker's signal and the scheduler's tables share.
func parseWorkers(workers []string) []endpoint {
	var out []endpoint
	for _, w := range workers {
		host, portStr, err := net.SplitHostPort(w)
		must(err)
		port, err := strconv.Atoi(portStr)
		must(err)
		out = append(out, ep(host, uint16(port)))
	}
	return out
}

func parseFuncs(funcs []string) []fn {
	var out []fn
	for _, f := range funcs {
		kv := strings.SplitN(f, ":", 2)
		if len(kv) != 2 {
			log.Fatalf("Config file Ill-formed (bad function %q)", f)
		}
		port, err := strconv.Atoi(strings.TrimSpace(kv[1]))
		must(err)
		out = append(out, fn{strings.TrimSpace(kv[0]), uint16(port)})
	}
	return out
}

func parseFuncAddrs(funcs []string) []fnAddr {
	var out []fnAddr
	for _, f := range funcs {
		kv := strings.SplitN(f, ":", 2)
		if len(kv) != 2 {
			log.Fatalf("Config file Ill-formed (bad function address %q)", f)
		}
		ip := net.ParseIP(strings.TrimSpace(kv[1])).To4()
		if ip == nil {
			log.Fatalf("Config file Ill-formed (not an IPv4 address: %q)", f)
		}
		out = append(out, fnAddr{strings.TrimSpace(kv[0]), binary.LittleEndian.Uint32(ip)})
	}
	return out
}

func ep(ipStr string, port uint16) endpoint {
	ip := net.ParseIP(ipStr).To4()
	var pb [2]byte
	binary.BigEndian.PutUint16(pb[:], port)
	return endpoint{IP: binary.LittleEndian.Uint32(ip), Port: binary.LittleEndian.Uint16(pb[:])}
}

func hostIP(host string) uint32 {
	return binary.LittleEndian.Uint32(net.ParseIP(host).To4())
}

func nport(p uint16) uint16 {
	var b [2]byte
	binary.BigEndian.PutUint16(b[:], p)
	return binary.LittleEndian.Uint16(b[:])
}

func fnv1a(s string) uint32 {
	h := uint32(0x811c9dc5)
	for i := 0; i < len(s); i++ {
		h ^= uint32(s[i])
		h *= 0x01000193
	}
	return h
}

// ---- Address check ----
// Why: a function address equal to the scheduler's own would make a worker reply that arrives on
// the service port look like a new request, and one equal to a worker's would send clients to
// that worker directly, past the scheduler. The per-worker maps have a fixed 16 entries with ids
// starting at 1, whatever N_WORKERS is. All three are refused before anything is attached.
func checkAddrs(cfg Config) {
	if len(cfg.Workers) >= 16 {
		log.Fatalf("worker ids are 1-based and the workers map holds 16, so at most 15 workers")
	}
	own := map[uint32]string{cfg.SchedIP: "the scheduler's own address"}
	for _, w := range cfg.Workers {
		own[w.IP] = "a worker's address"
	}
	for _, f := range cfg.FuncAddrs {
		if what, clash := own[f.addr]; clash {
			log.Fatalf("function %q is addressed as %s", f.name, what)
		}
	}
}

// ---- Start ----
// Why: any failed step is fatal, because a partly filled map would steer silently wrong; after
// that the kernel handles every request and this process only prints counters.
func Start(cfg Config) error {
	must(rlimit.RemoveMemlock())
	checkAddrs(cfg)
	spec, err := ebpf.LoadCollectionSpec(objPath)
	must(err)
	coll, err := ebpf.NewCollection(spec)
	must(err)
	defer coll.Close()

	w := coll.Maps["workers"]
	for i, e := range cfg.Workers {
		must(w.Update(uint32(i+1), e, ebpf.UpdateAny))
	}

	fp := coll.Maps["fnports"]
	for _, f := range cfg.Funcs {
		must(fp.Update(nport(f.port), fnv1a(f.name), ebpf.UpdateAny))
	}

	fa := coll.Maps["fnaddrs"]
	for _, f := range cfg.FuncAddrs {
		must(fa.Update(f.addr, fnv1a(f.name), ebpf.UpdateAny))
	}

	if cfg.Synthetic > 0 {
		start := time.Now()
		keys := make([]uint32, cfg.Synthetic)
		vals := make([]uint32, cfg.Synthetic)
		var b [4]byte
		for i := range keys {
			binary.BigEndian.PutUint32(b[:], 0x0A400000+uint32(i)+1)
			keys[i] = binary.LittleEndian.Uint32(b[:])
			vals[i] = uint32(i) + 1
		}
		if _, err := fa.BatchUpdate(keys, vals, nil); err != nil {
			log.Fatalf("padding fnaddrs with %d entries: %v", cfg.Synthetic, err)
		}
		log.Printf("padded fnaddrs with %d synthetic entries in %s",
			cfg.Synthetic, time.Since(start).Round(time.Millisecond))
	}

	must(coll.Maps["cfg"].Update(uint32(0), cfg.SchedIP, ebpf.UpdateAny))
	must(coll.Maps["cfg"].Update(uint32(1), cfg.Strategy, ebpf.UpdateAny))
	must(coll.Maps["cfg"].Update(uint32(2), cfg.Fallback, ebpf.UpdateAny))
	must(coll.Maps["cfg"].Update(uint32(3), cfg.Refused, ebpf.UpdateAny))
	must(coll.Maps["cfg"].Update(uint32(4), uint32(nport(cfg.SvcPort)), ebpf.UpdateAny))
	must(coll.Maps["cfg"].Update(uint32(5), cfg.Penalty, ebpf.UpdateAny))
	must(coll.Maps["cfg"].Update(uint32(6), cfg.FinRec, ebpf.UpdateAny))

	dev, err := net.InterfaceByName(cfg.Iface)
	must(err)

	xl, err := link.AttachXDP(link.XDPOptions{Program: coll.Programs["availability"], Interface: dev.Index})
	mode := "native"
	if err != nil {
		xl, err = link.AttachXDP(link.XDPOptions{
			Program: coll.Programs["availability"], Interface: dev.Index, Flags: link.XDPGenericMode,
		})
		mode = "generic"
	}
	must(err)
	defer xl.Close()

	tl, err := link.AttachTCX(link.TCXOptions{
		Interface: dev.Index, Program: coll.Programs["nat"], Attach: ebpf.AttachTCXIngress,
	})
	must(err)
	defer tl.Close()

	log.Printf("XDP availability (%s) + TC NAT attached to %s; %d function port(s), %d function address(es) on :%d"+
		" -> pull(idle_map), strategy=%d fallback=%d",
		mode, cfg.Iface, len(cfg.Funcs), len(cfg.FuncAddrs), cfg.SvcPort, cfg.Strategy, cfg.Fallback)

	stats := coll.Maps["nat_stats"]
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	t := time.NewTicker(2 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-t.C:
			printStats(stats, coll.Maps["idle_map"], coll.Maps["wflows"], len(cfg.Workers))
		case <-sig:
			log.Print("Detaching")
			return nil
		}
	}
}

// ---- Counters ----
// Why: the kernel program has no other output, and the evaluation harness reads the last line.
func printStats(stats, idle, wflows *ebpf.Map, nWorkers int) {
	labels := []string{"forward", "return", "flows", "no-free", "refused", "signals",
		"rst-old", "by-addr", "penal-skip", "dropped", "syn-new", "syn-stale", "fin-freed",
		"d-noworker", "d-noport", "d-noflow", "live", "left-home", "sig-full"}
	out := "NAT:"
	for i := uint32(0); i < uint32(len(labels)); i++ {
		var v uint64
		if err := stats.Lookup(&i, &v); err == nil {
			out += fmt.Sprintf(" %s=%d", labels[i], v)
		}
	}

	free := 0
	var k struct{ FnHash, WorkerID uint32 }
	var st struct {
		Slots      int32
		_          uint32
		LastSeenNs uint64
	}
	it := idle.Iterate()
	for it.Next(&k, &st) {
		if st.Slots > 0 {
			free++
		}
	}

	load := ""
	for i := uint32(1); i <= uint32(nWorkers); i++ {
		var v int64
		if err := wflows.Lookup(&i, &v); err == nil {
			load += fmt.Sprintf(" %d", v)
		}
	}
	log.Printf("%s | idle_map free-entries=%d | wflows=%s", out, free, load)
}

func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
