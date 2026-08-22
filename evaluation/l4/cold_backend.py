# duration + cold-start aware backend with instance concurrency. Parses /run/<fn>; a function
# is "warm" on this worker if it ran within KEEP seconds, else it pays COLD ms (cold start).
# Allows up to CONC concurrent executions per function and reports available slots (= CONC-active),
# broadcast to every scheduler (comma-separated sched_ip). REPORT_MS>0 -> report periodically (the
# scheduler view lags by up to REPORT_MS = controllable staleness); 0 -> report on every event.
# args: port name sched_ip[,sched_ip...] worker_id [warm_ms cold_ms keep_s conc report_ms dur_file]
# dur_file ('name ms' per line) gives real per-function warm durations; cold = warm + cold_ms penalty.
import http.server, socket, struct, sys, time, threading
port, name, wid = int(sys.argv[1]), sys.argv[2], int(sys.argv[4])
scheds = sys.argv[3].split(',')
WARM = float(sys.argv[5]) / 1000 if len(sys.argv) > 5 else 0.005
COLD = float(sys.argv[6]) / 1000 if len(sys.argv) > 6 else 0.2
KEEP = float(sys.argv[7]) if len(sys.argv) > 7 else 10.0
CONC = int(sys.argv[8]) if len(sys.argv) > 8 else 1
REPORT_MS = int(sys.argv[9]) if len(sys.argv) > 9 else 0
durmap = {}                               # per-function warm execution seconds (from a 'name ms' file)
if len(sys.argv) > 10 and sys.argv[10]:
    for line in open(sys.argv[10]):
        parts = line.split()
        if len(parts) == 2:
            durmap[parts[0]] = float(parts[1]) / 1000.0

def fnv1a(s):
    h = 0x811c9dc5
    for c in s.encode():
        h ^= c; h = (h * 0x01000193) & 0xffffffff
    return h

us = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
seen = {}                 # fn -> last completion time
active = {}               # fn -> in-flight (executing) count
sems = {}                 # fn -> semaphore enforcing CONC concurrent execs
known = set()             # functions this worker has served (for periodic reporting)
lock = threading.Lock()

def report(fn):           # advertise available slots for fn to every scheduler (call under lock)
    slots = CONC - active.get(fn, 0)
    if slots < 0:
        slots = 0
    pkt = struct.pack('>HBIII', 0x484B, 1, wid, fnv1a(fn), slots)
    for s in scheds:
        try:
            us.sendto(pkt, (s, 9020))
        except OSError:
            pass

def sem_for(fn):
    with lock:
        s = sems.get(fn)
        if s is None:
            s = sems[fn] = threading.Semaphore(CONC)
        return s

def reporter():           # staleness mode: report every REPORT_MS instead of on each event
    while True:
        time.sleep(REPORT_MS / 1000)
        with lock:
            for fn in list(known):
                report(fn)

if REPORT_MS > 0:
    threading.Thread(target=reporter, daemon=True).start()

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def setup(self):
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    def do_GET(self):
        fn = self.path.rsplit('/', 1)[-1] or 'unknown'
        sem_for(fn).acquire()     # at most CONC concurrent execs per function; excess queues
        try:
            now = time.time()
            with lock:
                warm = fn in seen and now - seen[fn] < KEEP
                active[fn] = active.get(fn, 0) + 1
                known.add(fn)
                if REPORT_MS == 0:
                    report(fn)
            wd = durmap.get(fn, WARM)         # real per-function warm duration; cold adds a spawn penalty
            time.sleep(wd if warm else wd + COLD)
            with lock:
                seen[fn] = time.time()
                active[fn] -= 1
                if REPORT_MS == 0:
                    report(fn)
            body = ("%s %s %s\n" % (name, fn, 'warm' if warm else 'cold')).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
            self.wfile.write(body)
        finally:
            sem_for(fn).release()
    def log_message(self, *a): pass

class Server(http.server.ThreadingHTTPServer):
    request_queue_size = 512      # default 5 is tiny; L4 connects clients straight to the worker
    daemon_threads = True
Server(('0.0.0.0', port), H).serve_forever()
