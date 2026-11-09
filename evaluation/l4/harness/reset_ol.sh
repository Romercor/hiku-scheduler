#!/usr/bin/bash
# Brings one OpenLambda worker back to a cold state with this run's settings, without reinstalling.
# Why: every arm must start cold with only its own settings. A plain restart fails on a held port, a
# stale worker.pid or the old sandbox cgroup tree, and would keep the last arm's settings.
# args: worker_port [config_overrides_json]
cd "$HOME" || exit 1
D=$(ls -d worker-* 2>/dev/null | head -1)
[ -z "$D" ] && { echo "NO WORKER DIR"; exit 1; }

sudo ./openlambda worker down -p "$D" >/dev/null 2>&1
sudo pkill -9 -f openlambda >/dev/null 2>&1
sudo pkill -9 -f 'fastbackend|poolbackend' >/dev/null 2>&1

sudo rm -rf "$D/worker/scratch" 2>/dev/null
sudo mkdir -p "$D/worker/scratch" 2>/dev/null

avail=$(df --output=avail -k / | tail -1)
if [ "${avail:-0}" -lt 10485760 ]; then
  echo "worker :$1 LOW DISK ($((avail / 1048576)) GB free)"; exit 1
fi

for _ in $(seq 1 30); do
  pgrep -f "openlambda|fastbackend|poolbackend" >/dev/null && { sleep 1; continue; }
  ss -lnt | grep -q ":$1 " || break
  sleep 1
done
if ss -lnt | grep -q ":$1 "; then
  echo "worker :$1 PORT STILL HELD"; exit 1
fi

if ! pgrep -f openlambda >/dev/null; then
  sudo rm -f "$D/worker/worker.pid" 2>/dev/null
  cg="/sys/fs/cgroup/$D-sandboxes"
  if [ -d "$cg" ]; then
    sudo find "$cg" -name cgroup.kill -exec sh -c 'echo 1 > "$1"' _ {} \; 2>/dev/null
    sleep 1
    sudo find "$cg" -mindepth 1 -depth -type d -exec rmdir {} \; 2>/dev/null
    sudo rmdir "$cg" 2>/dev/null
  fi
  if [ -d "$cg" ]; then
    echo "worker :$1 CGROUP NOT CLEARED"; exit 1
  fi
fi

DEFAULTS='{"max_conn_requests":0,"scheduler_peers":"","signal_refresh_ms":0,"signal_coalesce_ms":0,"close_when_busy":false,"signal_reports_warm":false}'
if jq --argjson d "$DEFAULTS" --argjson ov "${2:-{\}}" '. * $d * $ov' "$D/config.json" > /tmp/olcfg.json 2>/dev/null; then
  sudo cp /tmp/olcfg.json "$D/config.json"
else
  echo "worker :$1 CONFIG EDIT FAILED"; exit 1
fi

sudo bash -c ": > $D/worker.out"
sudo ./openlambda worker up -d -p "$D" -i ol-min >/dev/null 2>&1

for _ in $(seq 1 30); do
  ss -lnt | grep -q ":$1 " && break
  sleep 1
done
if sudo grep -q "address already in use" "$D/worker.out" 2>/dev/null; then
  echo "worker :$1 BIND FAILED"; exit 1
elif ss -lnt | grep -q ":$1 "; then
  pkill -x mpstat; setsid nohup mpstat 5 > "$HOME/mpstat.log" 2>&1 < /dev/null &
  echo "worker :$1 UP $(jq -c --argjson d "$DEFAULTS" 'with_entries(select(.key | in($d)))' "$D/config.json")"
else
  echo "worker :$1 FAILED"; sudo tail -5 "$D/worker.out"; exit 1
fi
