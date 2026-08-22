# echo backend: HTTP/1.1 keep-alive, threaded, TCP_NODELAY.
# args: port name [sched_ip worker_id]  -- if given, emits a FREE signal on completion
import http.server, socket, struct, sys
port, name = int(sys.argv[1]), sys.argv[2]
emit = len(sys.argv) >= 5
if emit:
    sched, wid = sys.argv[3], int(sys.argv[4])
    FREE = struct.pack('>HBIII', 0x484B, 1, wid, 0x68118e25, 0)
    us = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def setup(self):
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    def do_GET(self):
        body = (name + "\n").encode()
        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
        self.wfile.write(body)
        if emit:
            us.sendto(FREE, (sched, 9020))
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(('0.0.0.0', port), H).serve_forever()
