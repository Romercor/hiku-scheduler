#!/usr/bin/bash
# Instance-concurrency test: the same open-loop load against schedulers that do and do not know how
# many requests an instance can take, with the workers running poolbackend.go.
# Why: an OpenLambda instance serves one request at a time, so this case needs a synthetic worker.
# An arms file line is:
#   tag  arm(l7|l4)  scheduler_config  conc  [SICK=1: worker 1 listens with a backlog of 1 and aborts on overflow;
#   SICK=2: also four busy loops on worker 1 for 100 s, so that it accepts slowly]
# usage: pool.sh prep | run <campaign> <arms_file> <reps> [first_rep]
#   env: RATE (req/s, 400) or BURST (low,high,seconds) DUR (120s) WARM COLD (ms, 50 250) KEEP (s, 10)
#        PROBS (azure) NOKA (1 = one connection per request) SIGNAL (coalesce and refresh, ms)
# After a run at >= 1,000 new connections/s it waits 65 s, as the next scheduler starts its NAT port
# walk at the first port while the workers still hold those ports in TIME-WAIT.
set -e
. "$(dirname "$0")/lib.sh"
cd "$REPO"
SCHED=${SPUB[0]} SCHED_INT=${SPRV[0]} CLIENT=${CL[0]}
RATE=${RATE:-400} DUR=${DUR:-120s} WARM=${WARM:-50} COLD=${COLD:-250} KEEP=${KEEP:-10} PROBS=${PROBS:-azure}
NOKA=${NOKA:-1} SIGNAL=${SIGNAL:-10 1000} VUS="-e VUS=400 -e MAXVUS=4000"

phase_prep() {
  (cd evaluation/l4 && CGO_ENABLED=0 go build -o /tmp/poolbackend poolbackend.go)
  python3 "$H/mktrace.py" "evaluation/${PROBS}_function_probabilities.json" "$N_COPIES" /tmp/trace.json
  stop_workers
  for w in "${WP[@]}"; do scpx /tmp/poolbackend ubuntu@"$w":~/poolbackend; done
  scpx evaluation/l4/trace.js /tmp/trace.json ubuntu@"$CLIENT":~
  echo "PREP DONE"
}

run_one() {   # campaign rep position tag arm config conc [extra]
  local d="$OUT/$1/${4}_r$2" arm=$5 env pre
  wait_net "$SCHED" || { echo "  ABORT: no network"; exit 1; }
  rm -rf "$d"; mkdir -p "$d"
  echo "--- ${4}_r$2 (position $3) ---"
  for i in $(seq 0 $((NW-1))); do
    pre=""
    if [ "$i" = 0 ]; then
      if [[ "${8:-}" = SICK=* ]]; then pre="sudo sysctl -qw net.core.somaxconn=1 net.ipv4.tcp_abort_on_overflow=1;"
        [ "${8:-}" = SICK=2 ] && pre="$pre for c in 1 2 3 4; do setsid nohup timeout 100 sh -c 'while :; do :; done' > /dev/null 2>&1 < /dev/null & done;"
      else pre="sudo sysctl -qw net.core.somaxconn=4096 net.ipv4.tcp_abort_on_overflow=0;"; fi
    fi
    sshx "${WP[$i]}" "$pre pkill -x poolbackend; sleep 1; setsid nohup ./poolbackend $((5000+i)) worker-$((i+1)) $SCHED_INT $((i+1)) $WARM $COLD $KEEP $7 $SIGNAL > pool.log 2>&1 < /dev/null & sleep 1; cat pool.log" >> "$d/workers.txt" 2>&1 &
  done
  wait
  if ! sshx "$SCHED" "bash ~/start_sched.sh $arm '$6'" > "$d/sched_start.txt" 2>&1; then
    echo "  SKIPPED: scheduler failed"; cat "$d/sched_start.txt"; return 0
  fi
  env="-e FUNCS=trace.json -e MODE=$arm -e SCHED=$SCHED_INT -e RATE=$RATE -e DUR=$DUR -e BURST=$BURST"
  client_mon_start
  sshx "$CLIENT" "$K6 $env -e NOKA=$NOKA -e N_WORKERS=$NW $VUS --summary-export=/tmp/sum.json trace.js" > "$d/k6.log" 2>&1 || true
  client_mon_stop "$d"
  scpx ubuntu@"$CLIENT":/tmp/sum.json "$d/summary.json" || true
  sched_logs "$d" "$SCHED"
  for i in $(seq 0 $((NW-1))); do
    sshx "${WP[$i]}" "curl -s localhost:$((5000+i))/stats" >> "$d/stats.txt" 2>/dev/null || true
  done
  echo "$4 $arm $6 conc=$7 ${8:-} $(provenance "$SCHED")" > "$d/arm.txt"
  python3 "$H/pool_row.py" "$OUT/$1" "$4" "$2" "$3" "$7" "$NW" || echo "  (parse failed)"
  if [ "$NOKA" = 1 ] && [ "${RATE%%[!0-9]*}" -ge 1000 ]; then sleep 65; fi
}

phase_run() {   # campaign arms_file reps [first_rep]
  local camp=$1 reps=$3 first=${4:-1} arms=()
  mapfile -t arms < <(grep -vE '^\s*(#|$)' "$2")
  local n=${#arms[@]}
  mkdir -p "$OUT/$camp"; cp "$2" "$OUT/$camp/arms.txt"
  echo "rate=$RATE burst=$BURST dur=$DUR warm=$WARM cold=$COLD keep=$KEEP probs=$PROBS noka=$NOKA signal=$SIGNAL $VUS" > "$OUT/$camp/params.txt"
  for rep in $(seq "$first" $((first + reps - 1))); do
    for pos in $(seq 0 $((n-1))); do
      local k=$(((pos + 5 * (rep - 1)) % n))
      [ $((rep % 2)) = 0 ] && k=$((n - 1 - k))
      read -r tag arm config conc extra <<< "${arms[$k]}"
      run_one "$camp" "$rep" "$((pos+1))" "$tag" "$arm" "$config" "$conc" "$extra"
    done
  done
  # a SICK arm must not leak its backlog settings into the next campaign
  sshx "${WP[0]}" "sudo sysctl -qw net.core.somaxconn=4096 net.ipv4.tcp_abort_on_overflow=0"
}

case "${1:-}" in
  prep) phase_prep ;;
  run) shift; phase_run "$@" ;;
  *) usage ;;
esac
