// Idle-priority counter, compiled: one SCHED_IDLE process per vCPU counts busy-loop iterations for a
// fixed time and prints /proc/stat's cpu line before and after, in the format of hog.py.
// Why: hog.py's interpreted loop varied by up to 32% between idle runs of one round, too much to
// bound the kernel scheduler's cost from above.
// build: gcc -O2 -o hog hog.c   args: seconds
#define _GNU_SOURCE
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

static void cpuline(void) {
    char buf[512];
    FILE *f = fopen("/proc/stat", "r");
    if (f && fgets(buf, sizeof buf, f)) fputs(buf, stdout);
    if (f) fclose(f);
    fflush(stdout);
}

int main(int argc, char **argv) {
    double secs = argc > 1 ? atof(argv[1]) : 30;
    cpu_set_t all;
    sched_getaffinity(0, sizeof all, &all);
    int fds[CPU_SETSIZE][2], cpus[CPU_SETSIZE], n = 0;
    cpuline();
    for (int c = 0; c < CPU_SETSIZE; c++) {
        if (!CPU_ISSET(c, &all)) continue;
        pipe(fds[n]);
        cpus[n] = c;
        if (fork() == 0) {
            cpu_set_t one;
            CPU_ZERO(&one);
            CPU_SET(c, &one);
            sched_setaffinity(0, sizeof one, &one);
            struct sched_param p = {0};
            sched_setscheduler(0, SCHED_IDLE, &p);
            volatile unsigned long long k = 0;
            double end = now() + secs;
            while (now() < end)
                for (int i = 0; i < 100000; i++) k++;
            unsigned long long v = k;
            write(fds[n][1], &v, sizeof v);
            _exit(0);
        }
        n++;
    }
    unsigned long long counts[CPU_SETSIZE];
    for (int i = 0; i < n; i++) read(fds[i][0], &counts[i], sizeof counts[i]);
    while (wait(NULL) > 0) {}
    for (int i = 0; i < n; i++) printf("count %d %llu\n", cpus[i], counts[i]);
    cpuline();
    return 0;
}
