# Shared helpers sourced by every runner: cluster addresses from terraform, ssh, node and worker
# preparation, log collection. Runs from WSL with the UpCloud token in /root/.upcloud.env.
# Why: every runner must prepare and measure the nodes the same way, or the arms are not comparable.
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
H=$REPO/evaluation/l4/harness
OUT=${OUT:-$REPO/results/l4}
SSHO="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=25 -o ConnectionAttempts=6 -o ServerAliveInterval=30 -o LogLevel=ERROR -i /root/.ssh/id_rsa"
N_COPIES=${N_COPIES:-5}
OV='{"signal_refresh_ms":1000,"signal_coalesce_ms":10}'
K6="rm -f /tmp/sum*.json; ulimit -n 250000; k6 run --summary-trend-stats 'avg,min,med,max,p(90),p(95),p(99)'"

. /root/.upcloud.env
eval "$(cd "$REPO/terraform-upcloud" && terraform output -json | python3 -c '
import json,sys
o=json.load(sys.stdin)
v=lambda k: o[k]["value"]
print("SPUB=(%s)" % " ".join([v("scheduler_url")] + v("scheduler_extra_url")))
print("SPRV=(%s)" % " ".join([v("scheduler_internal")] + v("scheduler_extra_internal")))
print("CL=(%s)" % " ".join(v("client_url")))
print("WP=(%s)" % " ".join(v("worker_url")))
print("WI=(%s)" % " ".join(v("worker_internal")))
')"
NW=${#WI[@]}

sshx() { ssh $SSHO ubuntu@"$1" "${@:2}"; }
wait_net() {   # host: up to an hour for a dropped local connection to come back
  for _ in $(seq 1 120); do sshx "$1" true 2>/dev/null && return 0; sleep 30; done
  return 1
}
scpx() { scp $SSHO "$@" >/dev/null; }
usage() { sed -n '/^# usage:/,/^[^#]/p' "$0" | grep '^#'; exit 1; }

prep_sched() {   # public_ip internal_ip
  python3 "$H/mkconf.py" "/tmp/l4cfg-$2" "$2" "$N_COPIES" "${WI[@]}" >/dev/null
  sshx "$1" "sudo pkill -x hiku; rm -rf ~/hiku-src && mkdir -p ~/hiku-src; sudo apt-get -o DPkg::Lock::Timeout=600 install -y -qq sysstat >/dev/null 2>&1"
  scpx /tmp/l4src.tgz ubuntu@"$1":~/hiku-src/
  scpx "/tmp/l4cfg-$2"/l4_*.json "$H/start_sched.sh" ubuntu@"$1":~/
  sshx "$1" "cd ~/hiku-src && tar xzf l4src.tgz && cp ~/l4_p2c+hashed.json src/l4/config.json
    for _ in 1 2 3; do
      while sudo fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock >/dev/null 2>&1; do sleep 5; done
      bash scripts/setup_l4.sh > ~/setup_l4.log 2>&1 && [ -x /app/hiku ] && break
    done
    sudo cp ~/l4_*.json /app/
    echo \"scheduler $2: kernel \$(uname -r), \$(ls /app/l4_*.json | wc -l) configs, hiku \$([ -x /app/hiku ] && echo OK || echo MISSING)\""
}

prep_cluster() {   # scheduler_index...
  tar czf /tmp/l4src.tgz src scripts/setup_l4.sh
  for i in "$@"; do prep_sched "${SPUB[$i]}" "${SPRV[$i]}" & done
  wait
  for i in "$@"; do
    sshx "${SPUB[$i]}" "test -x /app/hiku" || { echo "PREP FAILED: no /app/hiku on scheduler $i"; return 1; }
  done
  scpx evaluation/load_test.js evaluation/*_function_probabilities.json ubuntu@"${CL[0]}":~
  sshx "${CL[0]}" "command -v mpstat >/dev/null || sudo apt-get -o DPkg::Lock::Timeout=600 install -y -qq sysstat >/dev/null 2>&1"
  if ! sshx "${CL[0]}" "command -v k6 >/dev/null"; then
    scpx /usr/local/bin/k6 ubuntu@"${CL[0]}":~/k6
    sshx "${CL[0]}" "sudo mv ~/k6 /usr/local/bin/k6 && sudo chmod +x /usr/local/bin/k6"
  fi
  for w in "${WP[@]}"; do
    scpx "$H/reset_ol.sh" ubuntu@"$w":~/reset_ol.sh
    sshx "$w" "command -v mpstat >/dev/null || sudo apt-get -o DPkg::Lock::Timeout=600 install -y -qq sysstat >/dev/null 2>&1" &
  done
  wait
  for h in "${SPUB[@]}" "${CL[0]}" "${WP[@]}"; do
    sshx "$h" "sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer unattended-upgrades >/dev/null 2>&1; sudo pkill -f unattended-upgrade" || true
  done
}

stop_workers() {
  for w in "${WP[@]}"; do
    sshx "$w" "sudo ./openlambda worker down -p \$(ls -d worker-* | head -1) >/dev/null 2>&1; sudo pkill -9 -x openlambda; pkill -x poolbackend; true"
  done
}

reset_workers() {   # overrides_json outfile
  local pids=() rc=0
  for i in $(seq 0 $((NW-1))); do
    sshx "${WP[$i]}" "bash ~/reset_ol.sh $((5000+i)) '$1'" >> "$2" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p" || rc=1; done
  return $rc
}

sched_logs() {   # dir scheduler_public_ip [suffix]
  sshx "$2" "sudo pkill -x mpstat; cat /tmp/mpstat.log" > "$1/mpstat$3.log" 2>/dev/null || true
  sshx "$2" "sleep 6; head -4 /tmp/sched.log; tail -2 /tmp/sched.log; sudo bpftool prog show 2>/dev/null | grep -A1 -E 'name (nat|availability) '" > "$1/sched$3.log" 2>/dev/null || true
}

worker_logs() {   # dir
  for i in $(seq 0 $((NW-1))); do
    sshx "${WP[$i]}" "sudo cat \$(ls -d ~/worker-*)/worker.out" > "$1/worker-$((i+1)).log" 2>/dev/null &
    sshx "${WP[$i]}" "cat ~/mpstat.log" > "$1/worker-$((i+1)).mpstat" 2>/dev/null &
  done
  wait
}

client_mon_start() {
  sshx "${CL[0]}" "pkill -x mpstat; setsid nohup mpstat 5 > /tmp/client_mpstat.log 2>&1 < /dev/null &"
}

client_mon_stop() {   # dir
  sshx "${CL[0]}" "pkill -x mpstat; cat /tmp/client_mpstat.log" > "$1/client.mpstat" 2>/dev/null || true
}

provenance() {   # scheduler_public_ip
  echo "commit=$(git rev-parse --short HEAD)$(git diff --quiet 2>/dev/null || echo +dirty)" \
    "src=$(git diff --quiet HEAD -- src scripts/setup_l4.sh 2>/dev/null && echo clean || echo dirty)" \
    "$(sshx "$1" "sha256sum /app/scheduler.bpf.o /app/hiku | cut -c1-12 | paste -sd,")" \
    "worker=$(sshx "${WP[0]}" "sha256sum openlambda | cut -c1-12")"
}
