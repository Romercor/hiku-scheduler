#!/usr/bin/bash
# Starts one scheduler arm (L7 or L4) on a scheduler node, with CPU sampling alongside.
# Why: a restart empties every BPF map, so no arm inherits the state of the one before. It is a
# file on the node because backgrounding inside an inline ssh command keeps the caller hanging.
# args: arm(l7|l4) config
cd "$HOME" || exit 1
sudo pkill -x hiku >/dev/null 2>&1
sudo pkill -x mpstat >/dev/null 2>&1
sleep 2

if [ "$1" = "l7" ]; then
  setsid nohup /app/hiku start --config="worker_config/$2.json" > /tmp/sched.log 2>&1 < /dev/null &
  sleep 4
  if ss -lnt | grep -q ':9020 '; then echo "L7 $2 UP"; else echo "L7 $2 FAILED"; tail -10 /tmp/sched.log; exit 1; fi
else
  sudo mount -t bpf bpf /sys/fs/bpf 2>/dev/null
  sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null
  sudo setsid nohup /app/hiku l4 -c "/app/l4_$2.json" > /tmp/sched.log 2>&1 < /dev/null &
  sleep 6
  if pgrep -x hiku >/dev/null; then echo "L4 $2 UP"; else echo "L4 $2 FAILED"; tail -15 /tmp/sched.log; exit 1; fi
fi
setsid nohup mpstat 5 > /tmp/mpstat.log 2>&1 < /dev/null &
