// Measures what ingesting the signals of a large pool costs the scheduler, without that pool.
// Several senders spread the load over the scheduler's RX queues.
// args: sched_ip rate_pps seconds n_workers n_functions [senders]
package main

import (
	"encoding/binary"
	"fmt"
	"log"
	"net"
	"os"
	"strconv"
	"sync"
	"sync/atomic"
	"time"
)

func main() {
	if len(os.Args) < 6 {
		log.Fatal("args: sched_ip rate_pps seconds n_workers n_functions [senders]")
	}
	num := func(i int) int { v, _ := strconv.Atoi(os.Args[i]); return v }
	rate, secs, workers, funcs, senders := num(2), num(3), num(4), num(5), 4
	if len(os.Args) > 6 {
		senders = num(6)
	}

	var sent int64
	var wg sync.WaitGroup
	end := time.Now().Add(time.Duration(secs) * time.Second)
	for s := 0; s < senders; s++ {
		wg.Add(1)
		go func(s int) {
			defer wg.Done()
			c, err := net.Dial("udp", os.Args[1]+":9020")
			if err != nil {
				log.Fatal(err)
			}
			var b [15]byte
			binary.BigEndian.PutUint16(b[0:], 0x484B)
			b[2] = 1
			per := rate / senders / 1000
			if per < 1 {
				per = 1
			}
			gap := time.Duration(float64(per) * float64(senders) / float64(rate) * float64(time.Second))
			for i, next := s, time.Now(); time.Now().Before(end); next = next.Add(gap) {
				for k := 0; k < per; k++ {
					binary.BigEndian.PutUint32(b[3:], uint32(i/funcs%workers+1))
					binary.BigEndian.PutUint32(b[7:], uint32(i%funcs)*2654435761)
					binary.BigEndian.PutUint32(b[11:], uint32(i&1))
					c.Write(b[:])
					i += senders
				}
				atomic.AddInt64(&sent, int64(per))
				time.Sleep(time.Until(next))
			}
		}(s)
	}
	wg.Wait()
	fmt.Printf("sent %d in %ds = %d/s\n", sent, secs, sent/int64(secs))
}
