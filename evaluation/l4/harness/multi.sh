#!/usr/bin/bash
# Runs 1..n in-kernel schedulers over one worker pool, at a fixed load split over K k6 instances.
# Why: shows whether the scheduler scales out. Workers signal every scheduler in every arm, so the
# arms differ only in who steers; functions are named by port, as one client cannot route the same
# function address to several schedulers.
# A cells file line is:
#   tag  n_sched  scheduler_config  coalesce_ms  vuscale
# usage: multi.sh prep | run <campaign> <reps> <config> <n_sched>... | runfile <campaign> <cells_file> <reps> [first_rep]
#   env: K (k6 instances, 4) VUSCALE (total load against the paper's profile, 1)
#        COALESCE (the workers' signal coalescing, ms, 10) FIRST (first repetition number, 1)
set -e
. "$(dirname "$0")/lib.sh"
cd "$REPO"
CLIENT=${CL[0]} K=${K:-4} VUSCALE=${VUSCALE:-1}
PEERS=$(printf '%s:9020,' "${SPRV[@]}")

overrides() {   # coalesce_ms
  local o="${OV/coalesce_ms\":10/coalesce_ms\":$1}"
  echo "${o%\}},\"scheduler_peers\":\"${PEERS%,}\"}"
}

phase_prep() {
  echo "schedulers=${SPRV[*]} client=$CLIENT workers=${WI[*]}"
  prep_cluster "${!SPUB[@]}"
  echo "PREP DONE"
}

run_one() {   # campaign rep position config n_sched tag coalesce_ms vuscale
  local ns=$5 tag=$6 d="$OUT/$1/${6}_r$2" ov env
  ov=$(overrides "$7")
  wait_net "${SPUB[0]}" || { echo "  ABORT: no network"; exit 1; }
  rm -rf "$d"; mkdir -p "$d"
  echo "--- ${tag}_r$2 (position $3) ---"
  if ! reset_workers "$ov" "$d/workers.txt"; then echo "  SKIPPED: worker reset failed"; cat "$d/workers.txt"; return 0; fi
  for i in "${!SPUB[@]}"; do
    if [ "$i" -lt "$ns" ]; then
      sshx "${SPUB[$i]}" "bash ~/start_sched.sh l4 '$4'" >> "$d/sched_start.txt" 2>&1 &
    else
      sshx "${SPUB[$i]}" "sudo pkill -x hiku; sudo pkill -x mpstat; true" &
    fi
  done
  wait
  client_mon_start
  for c in $(seq 0 $((K-1))); do
    env="-e N_COPIES=$N_COPIES -e SEED=$((1000 + c * 1000 + $2)) -e SCHEDULER_DNS=${SPRV[$((c % ns))]} -e MODE=l4"
    env="$env -e NOKA=1 -e VUSCALE=$(python3 -c "print($8/$K)")"
    sshx "$CLIENT" "$K6 $env --summary-export=/tmp/sum$c.json load_test.js" > "$d/k6-$c.log" 2>&1 &
  done
  wait
  client_mon_stop "$d"
  for c in $(seq 0 $((K-1))); do scpx ubuntu@"$CLIENT":/tmp/sum$c.json "$d/summary-$c.json" || true; done
  for i in $(seq 0 $((ns-1))); do sched_logs "$d" "${SPUB[$i]}" "-$i" & done
  wait
  worker_logs "$d"
  echo "$tag l4 $4 $ov K=$K,VUSCALE=$8 $(provenance "${SPUB[0]}")" > "$d/arm.txt"
  python3 "$H/row.py" "$OUT/$1" "$tag" "$2" "$3" "$NW" || echo "  (parse failed)"
}

phase_run() {   # campaign reps config n_sched...
  local camp=$1 reps=$2 config=$3; shift 3
  local arms=("$@") n=$#
  mkdir -p "$OUT/$camp"; printf 's%s\n' "${arms[@]}" > "$OUT/$camp/arms.txt"
  for rep in $(seq "${FIRST:-1}" $((${FIRST:-1} + reps - 1))); do
    for pos in $(seq 0 $((n-1))); do
      local a=${arms[$(((pos + rep - 1) % n))]}
      run_one "$camp" "$rep" "$((pos+1))" "$config" "$a" "s$a" "${COALESCE:-10}" "$VUSCALE"
    done
  done
  python3 "$H/summary.py" "$OUT/$camp"
}

phase_runfile() {   # campaign cells_file reps [first_rep]
  local camp=$1 reps=$3 first=${4:-1} cells=()
  mapfile -t cells < <(grep -vE '^\s*(#|$)' "$2")
  local n=${#cells[@]} step
  step=$(python3 -c "import math; print(next(s for s in range(3, $n + 3) if math.gcd(s, $n) == 1))")
  mkdir -p "$OUT/$camp"; cp "$2" "$OUT/$camp/arms.txt"
  for rep in $(seq "$first" $((first + reps - 1))); do
    for pos in $(seq 0 $((n-1))); do
      local k=$(((pos + step * ((rep - 1) / 2)) % n))
      [ $((rep % 2)) = 0 ] && k=$((n - 1 - k))
      read -r tag ns config co vs <<< "${cells[$k]}"
      run_one "$camp" "$rep" "$((pos+1))" "$config" "$ns" "$tag" "$co" "$vs"
    done
  done
  python3 "$H/summary.py" "$OUT/$camp"
}

case "${1:-}" in
  prep) phase_prep ;;
  run) shift; phase_run "$@" ;;
  runfile) shift; phase_runfile "$@" ;;
  *) usage ;;
esac
