#!/usr/bin/bash
# Main runner: each arm (a scheduler and its settings) for several repetitions on real OpenLambda
# under the paper's load, one row per run.
# Why: a fair comparison needs every arm to start from cold workers and a fresh scheduler, with the
# same seed per repetition and an order that changes, so no arm keeps its position.
# An arms file line is:
#   tag  arm(l7|l4)  scheduler_config  worker_overrides_json(or -)  k6_env(K=V,K=V or -)
# for l7 the scheduler config is a balancer name, for l4 it is <strategy>+<fallback> (see mkconf.py).
# KILL_AT=<s> in the k6 env kills worker 1's OpenLambda that many seconds into the run.
# LOSS=<p> in the k6 env drops each worker's announcements (UDP to port 9020) with probability p.
# usage: matrix.sh prep | run <campaign> <arms_file> <reps> [first_rep] | fill <campaign> <arms_file> <reps>
#   fill re-runs, at position 0, every (arm, repetition) without a row with requests in runs.csv.
#   env: PROBS (popularity file: azure, huawei, ibm; azure)
#        MAXFAIL (stop after two runs in a row above this % of failed calls; EXEMPT: tag regex)
set -e
. "$(dirname "$0")/lib.sh"
cd "$REPO"
SCHED=${SPUB[0]} SCHED_INT=${SPRV[0]} CLIENT=${CL[0]} PROBS=${PROBS:-azure}

phase_prep() {
  echo "scheduler=$SCHED_INT client=$CLIENT workers=${WI[*]}"
  prep_cluster 0
  sshx "$SCHED" "ls ~/worker_config/ 2>/dev/null || echo NO BALANCER CONFIGS"
  sshx "$CLIENT" "sudo ip route replace 10.200.0.0/16 via $SCHED_INT; ip route get 10.200.0.1 | head -1; k6 version"
  echo "PREP DONE"
}

run_one() {   # campaign rep position tag arm config overrides k6env
  local d="$OUT/$1/${4}_r$2" arm=$5 mode=l7 ov=$7 env="-e PROBS=${PROBS}_function_probabilities.json"
  wait_net "$SCHED" || { echo "  ABORT: no network"; exit 1; }
  rm -rf "$d"; mkdir -p "$d"
  echo "--- ${4}_r$2 (position $3) ---"
  [ "$ov" = "-" ] && ov=$OV
  if ! reset_workers "$ov" "$d/workers.txt"; then echo "  SKIPPED: worker reset failed"; cat "$d/workers.txt"; return 0; fi
  if ! sshx "$SCHED" "bash ~/start_sched.sh $arm '$6'" > "$d/sched_start.txt" 2>&1; then
    echo "  SKIPPED: scheduler failed"; cat "$d/sched_start.txt"; return 0
  fi
  [ "$arm" = "l4" ] && mode=l4addr
  [ "$8" != "-" ] && env="$env -e ${8//,/ -e }"
  env="-e N_COPIES=$N_COPIES -e SEED=$((1000 + $2)) -e SCHEDULER_DNS=$SCHED_INT -e MODE=$mode $env"
  client_mon_start
  kill_at=$(grep -o 'KILL_AT=[0-9]*' <<< "$8" | cut -d= -f2)
  [ -n "$kill_at" ] && (sleep "$kill_at"; sshx "${WP[0]}" "sudo pkill -9 -x openlambda; date +%T.%N" > "$d/killed.txt" 2>&1) &
  loss=$(grep -o 'LOSS=[0-9.]*' <<< "$8" | cut -d= -f2)
  rule="OUTPUT -p udp --dport 9020 -m statistic --mode random --probability $loss -j DROP"
  if [ -n "$loss" ]; then for w in "${WP[@]}"; do sshx "$w" "sudo iptables -I $rule"; done; fi
  timeout 900 ssh $SSHO ubuntu@"$CLIENT" "$K6 $env --summary-export=/tmp/sum.json load_test.js" > "$d/k6.log" 2>&1 || true
  wait
  if [ -n "$loss" ]; then
    for w in "${WP[@]}"; do sshx "$w" "sudo iptables -L OUTPUT -v -x -n | grep statistic; sudo iptables -D $rule" >> "$d/loss.txt" 2>&1; done
  fi
  client_mon_stop "$d"
  scpx ubuntu@"$CLIENT":/tmp/sum.json "$d/summary.json" || true
  sched_logs "$d" "$SCHED"
  worker_logs "$d"
  echo "$4 $arm $6 $ov $8 probs=$PROBS seed=$((1000 + $2)) $(provenance "$SCHED")" > "$d/arm.txt"
  python3 "$H/row.py" "$OUT/$1" "$4" "$2" "$3" "$NW" || echo "  (parse failed)"
}

phase_run() {   # campaign arms_file reps [first_rep]
  local camp=$1 reps=$3 first=${4:-1} arms=()
  mapfile -t arms < <(grep -vE '^\s*(#|$)' "$2")
  local n=${#arms[@]} step
  step=$(python3 -c "import math; print(next(s for s in range(3, $n + 3) if math.gcd(s, $n) == 1))")
  mkdir -p "$OUT/$camp"; cp "$2" "$OUT/$camp/arms.txt"
  for rep in $(seq "$first" $((first + reps - 1))); do
    for pos in $(seq 0 $((n-1))); do
      local k=$(((pos + step * ((rep - 1) / 2)) % n))
      [ $((rep % 2)) = 0 ] && k=$((n - 1 - k))
      read -r tag arm config ov env <<< "${arms[$k]}"
      run_one "$camp" "$rep" "$((pos+1))" "$tag" "$arm" "$config" "$ov" "$env"
      [ -z "${MAXFAIL:-}" ] || python3 -c "
import csv, os, re, sys
p = '$OUT/$camp/runs.csv'
r = list(csv.DictReader(open(p)))[-2:] if os.path.exists(p) else []
sys.exit(len(r) == 2 and all(float(x['fail_pct']) > $MAXFAIL and not re.search('${EXEMPT:-^$}', x['tag']) for x in r))" ||
        { echo "  ABORT: two runs in a row above $MAXFAIL % failed calls"; exit 1; }
    done
  done
  python3 "$H/summary.py" "$OUT/$camp"
}

phase_fill() {   # campaign arms_file reps
  local camp=$1 arms=() line tag
  mapfile -t arms < <(grep -vE '^\s*(#|$)' "$2")
  for rep in $(seq 1 "$3"); do
    for line in "${arms[@]}"; do
      read -r tag arm config ov env <<< "$line"
      awk -F, -v t="$tag" -v r="$rep" '$1 == t && $2 == r && $4 > 0 {f = 1} END {exit !f}' "$OUT/$camp/runs.csv" 2>/dev/null && continue
      awk -F, -v t="$tag" -v r="$rep" '!($1 == t && $2 == r)' "$OUT/$camp/runs.csv" > /tmp/fill.csv && cp /tmp/fill.csv "$OUT/$camp/runs.csv"
      run_one "$camp" "$rep" 0 "$tag" "$arm" "$config" "$ov" "$env"
    done
  done
  python3 "$H/summary.py" "$OUT/$camp"
}

case "${1:-}" in
  prep) phase_prep ;;
  run) shift; phase_run "$@" ;;
  fill) shift; phase_fill "$@" ;;
  *) usage ;;
esac
