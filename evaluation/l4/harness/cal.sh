#!/usr/bin/bash
# Calibration rounds for the scheduler's CPU on the synthetic backend: per round and load condition
# Hiku pull-based and the kernel scheduler under an idle-priority counter (hog) and under an irq
# tracer (trace), the kernel scheduler once more with the kernel's BPF statistics on (stats), and
# idle runs as the baseline, in an order that rotates with the round. Needs matrix.sh prep and
# pool.sh prep first. Writes <name>/<arm>_<cond>_r<round>.<mode>.txt for cpu_cal.py and the
# load runs as pool.sh campaigns <name>_<arm>_<cond>_<mode>.
# Why: mpstat does not see the kernel scheduler's work, which runs in softirq; each of these
# measures covers part of it, and only rounds with both arms can be compared.
# usage: cal.sh <name> <rounds> [first_round]
#   env: MODES (measures per arm, "hog trace stats"); the hog is hog.c, compiled on the scheduler
#        ONLY (one condition, e.g. noka_3000)
set -e
. "$(dirname "$0")/lib.sh"
cd "$REPO"
SCHED=${SPUB[0]} CLIENT=${CL[0]}
name=$1 rounds=$2 first=${3:-1} d="$OUT/$1"
CONDS=("noka_3000 1 3000" "ka_6000 0 6000" "ka_12000 0 12000")
[ -n "${ONLY:-}" ] && mapfile -t CONDS < <(printf '%s
' "${CONDS[@]}" | grep "^$ONLY ")
n=${#CONDS[@]}
mkdir -p "$d"
printf 'l7-pull l7 pull-based 8\n' > /tmp/cal_l7.txt
printf 'l4-ord-least l4 ordered+least-loaded 8\n' > /tmp/cal_l4.txt
MODES=${MODES:-hog trace stats}
scpx "$H/hog.c" "$H/irq.bt" ubuntu@"$SCHED":~
sshx "$SCHED" "command -v gcc >/dev/null || sudo apt-get -o DPkg::Lock::Timeout=600 install -y -qq gcc >/dev/null 2>&1; gcc -O2 -o ~/hog ~/hog.c"
sshx "$SCHED" "command -v bpftrace >/dev/null || sudo apt-get -o DPkg::Lock::Timeout=600 install -y -qq bpftrace >/dev/null 2>&1; command -v bpftool >/dev/null || sudo apt-get -o DPkg::Lock::Timeout=600 install -y -qq linux-tools-\$(uname -r) >/dev/null 2>&1; bpftrace --version"

measure() {   # mode outfile
  case $1 in
    hog) sshx "$SCHED" "~/hog 30" > "$2" ;;
    trace) sshx "$SCHED" "sudo timeout 45 bpftrace ~/irq.bt" > "$2" ;;
    stats) sshx "$SCHED" "sudo sysctl -qw kernel.bpf_stats_enabled=1; sudo bpftool prog show -j; sleep 30; sudo bpftool prog show -j; sudo sysctl -qw kernel.bpf_stats_enabled=0" > "$2" ;;
  esac
}

idle() {   # tag round
  sshx "$SCHED" "sudo pkill -x hiku; sudo pkill -x mpstat; true"
  for m in hog trace; do measure $m "$d/idle_$1_r$2.$m.txt"; done
}

loaded() {   # arm cond noka rate mode round
  (for _ in $(seq 1 180); do sshx "$CLIENT" "pgrep -x k6 >/dev/null" && break; sleep 1; done
   sleep 15; measure "$5" "$d/$1_$2_r$6.$5.txt") &
  RATE=$4 NOKA=$3 WARM=2 COLD=0 KEEP=600 DUR=60s bash "$H/pool.sh" run "${name}_$1_$2_$5" /tmp/cal_$1.txt 1 "$6"
  wait
}

for r in $(seq "$first" $((first + rounds - 1))); do
  idle a "$r"
  for i in $(seq 0 $((n - 1))); do
    read -r cond noka rate <<< "${CONDS[$(((i + r) % n))]}"
    for m in $MODES; do
      [ "$m" = stats ] && continue
      if [ $((r % 2)) = 0 ]; then order="l4 l7"; else order="l7 l4"; fi
      for arm in $order; do loaded "$arm" "$cond" "$noka" "$rate" "$m" "$r"; done
    done
    if [[ " $MODES " = *" stats "* ]]; then loaded l4 "$cond" "$noka" "$rate" stats "$r"; fi
    idle "$(echo b c d | cut -d' ' -f$((i + 1)))" "$r"
  done
done
echo "CAL DONE"
