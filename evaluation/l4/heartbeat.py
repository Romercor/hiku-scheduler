# worker availability signal. args: sched_ip worker_id [func_name...]  (default pyaes)
import socket, struct, sys, time
sched, wid = sys.argv[1], int(sys.argv[2])
names = sys.argv[3:] or ['pyaes']
def fnv1a(s):
    h = 0x811c9dc5
    for c in s.encode():
        h ^= c; h = (h * 0x01000193) & 0xffffffff
    return h
hashes = [fnv1a(n) for n in names]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
while True:
    for fh in hashes:
        s.sendto(struct.pack('>HBIII', 0x484B, 1, wid, fh, 1), (sched, 9020))  # 1 free slot
    time.sleep(1)
