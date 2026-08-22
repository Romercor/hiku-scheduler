package steer

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

const objPath = "/app/steer.bpf.o"

type fn struct {
	name string
	port uint16
}

type endpoint struct {
	IP   uint32
	Port uint16
	_    uint16
}

// JSONConfig holds the data configured via a JSON file: the NIC to attach to,
// this scheduler's own IP, the pick strategy, and the worker and function
// tables (as "ip:port" and "name:port" strings). This shall be parsed into a
// proper Config that dictates how the maps are populated.
type JSONConfig struct {
	Iface     string   `json:"iface"`
	Host      string   `json:"host"`
	Strategy  string   `json:"strategy"`
	Workers   []string `json:"workers"`
	Functions []string `json:"functions"`
}

type Config struct {
	Iface    string
	SchedIP  uint32
	Strategy uint32
	Workers  []endpoint
	Funcs    []fn
}

func (c JSONConfig) ToConfig() Config {
	return Config{
		Iface:    c.Iface,
		SchedIP:  hostIP(c.Host),
		Strategy: strategyFromConfig(c),
		Workers:  parseWorkers(c.Workers),
		Funcs:    parseFuncs(c.Functions),
	}
}

func LoadConfigFromFile(configFilepath string) JSONConfig {
	var config JSONConfig

	file, rfErr := os.ReadFile(configFilepath)
	if rfErr != nil {
		log.Fatalf("Cannot read config file (%s)", rfErr)
	}

	decoder := json.NewDecoder(bytes.NewReader(file))
	jsonErr := decoder.Decode(&config) // Parse json config file
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
	}

	panic("Unknown strategy: " + c.Strategy)
}

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

// ep encodes ip:port into the host-endian fields cilium/ebpf marshals back to
// the network order the BPF program writes into packets.
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

func Start(cfg Config) error {
	must(rlimit.RemoveMemlock())
	spec, err := ebpf.LoadCollectionSpec(objPath)
	must(err)
	coll, err := ebpf.NewCollection(spec)
	must(err)
	defer coll.Close()

	w := coll.Maps["workers"]
	for i, e := range cfg.Workers {
		must(w.Update(uint32(i+1), e, ebpf.UpdateAny))
	}

	// function -> scheduler port (function-in-port)
	fp := coll.Maps["fnports"]
	for _, f := range cfg.Funcs {
		must(fp.Update(nport(f.port), fnv1a(f.name), ebpf.UpdateAny))
	}

	// cfg[0] = this scheduler's own IP (network order); cfg[1] = pick strategy
	must(coll.Maps["cfg"].Update(uint32(0), cfg.SchedIP, ebpf.UpdateAny))
	must(coll.Maps["cfg"].Update(uint32(1), cfg.Strategy, ebpf.UpdateAny))

	dev, err := net.InterfaceByName(cfg.Iface)
	must(err)

	// XDP availability (native, fall back to generic on the virtual NIC)
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

	log.Printf("XDP availability (%s) + TC NAT attached to %s; %d function port(s) -> pull(idle_map)", mode, cfg.Iface, len(cfg.Funcs))

	stats := coll.Maps["nat_stats"]
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	t := time.NewTicker(2 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-t.C:
			printStats(stats, coll.Maps["idle_map"])
		case <-sig:
			log.Print("Detaching")
			return nil
		}
	}
}

func printStats(stats, idle *ebpf.Map) {
	labels := []string{"forward", "return", "flows", "no-free"}
	out := "NAT:"
	for i := uint32(0); i < 4; i++ {
		var v uint64
		if err := stats.Lookup(&i, &v); err == nil {
			out += fmt.Sprintf(" %s=%d", labels[i], v)
		}
	}

	// count idle_map entries with a free slot
	free := 0
	var k struct{ FnHash, WorkerID uint32 }
	var st struct {
		Slots      uint32
		_          uint32
		LastSeenNs uint64
	}
	it := idle.Iterate()
	for it.Next(&k, &st) {
		if st.Slots > 0 {
			free++
		}
	}
	log.Printf("%s | idle_map free-entries=%d", out, free)
}

func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
