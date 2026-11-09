# Idle-priority counter: one SCHED_IDLE process per vCPU counts busy-loop chunks for a fixed time and
# prints /proc/stat's cpu line before and after. Fewer counts than in an idle run is capacity the
# scheduler took from other work on the machine.
# Why: the kernel scheduler runs in softirq, which mpstat does not attribute to it.
# args: seconds
import multiprocessing as mp, os, sys, time


def work(cpu, secs, q):
    os.sched_setaffinity(0, {cpu})
    os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))
    end, n = time.monotonic() + secs, 0
    while time.monotonic() < end:
        for _ in range(10000):
            pass
        n += 1
    q.put((cpu, n))


if __name__ == "__main__":
    secs = float(sys.argv[1])
    q = mp.Queue()
    print(open("/proc/stat").readline().strip())
    ps = [mp.Process(target=work, args=(c, secs, q)) for c in sorted(os.sched_getaffinity(0))]
    for p in ps:
        p.start()
    res = [q.get() for _ in ps]
    for p in ps:
        p.join()
    for c, n in res:
        print("count %d %d" % (c, n))
    print(open("/proc/stat").readline().strip())
