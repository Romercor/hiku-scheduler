#!/usr/bin/bash
# Brings the cluster of terraform-upcloud up and waits until every node answers, or checks that a
# prepared cluster is healthy: scheduler kernels >= 6, free disk on the workers, the client's route
# and an idle sample of steal time on every node.
# Why: a session that starts on a node still booting, or on a host with a noisy neighbour, measures
# the host instead of the scheduler.
# usage: cluster.sh up | cpu | health
set -e
REPO=$(cd "$(dirname "$0")/../../.." && pwd)

if [ "${1:-}" = up ]; then
  . /root/.upcloud.env
  (cd "$REPO/terraform-upcloud" && terraform init -input=false >/dev/null && terraform apply -auto-approve -input=false -no-color | tail -3)
fi
. "$(dirname "$0")/lib.sh"

case "${1:-}" in
  up)
    for h in "${SPUB[@]}" "${CL[@]}" "${WP[@]}"; do
      (for _ in $(seq 1 60); do sshx "$h" true 2>/dev/null && break; sleep 5; done
       sshx "$h" "sudo cloud-init status --wait >/dev/null 2>&1; hostname") &
    done
    wait
    echo "UP ${#SPUB[@]} schedulers, ${#WP[@]} workers, ${#CL[@]} client"
    ;;
  cpu)
    for h in "${SPUB[@]}" "${CL[@]}" "${WP[@]}"; do
      echo "$h $(sshx "$h" "lscpu | sed -n 's/^Model name: *//p'; python3 -c 'import time; t = time.perf_counter(); sum(i * i for i in range(10 ** 7)); print(\"loop %.2f s\" % (time.perf_counter() - t))'" | paste -sd' ')"
    done
    ;;
  health)
    bad=0
    for h in "${SPUB[@]}"; do
      k=$(sshx "$h" "uname -r"); echo "scheduler $h kernel $k"
      [ "${k%%.*}" -ge 6 ] || bad=1
    done
    for w in "${WP[@]}"; do
      g=$(sshx "$w" "df --output=avail -BG / | tail -1 | tr -dc 0-9"); echo "worker $w free ${g} GB"
      [ "$g" -ge 100 ] || bad=1
    done
    sshx "${CL[0]}" "ip route get 10.200.0.1 | head -1; k6 version | head -1; nproc"
    for h in "${SPUB[@]}" "${CL[@]}" "${WP[@]}"; do
      s=$(sshx "$h" "mpstat 5 6 | awk '/Average/ && / all / {print \$(NF-3)}'")
      echo "steal $h $s"
      python3 -c "import sys; sys.exit(0 if float('$s' or 99) < 2 else 1)" || bad=1
    done
    [ $bad = 0 ] && echo "HEALTH OK" || { echo "HEALTH FAILED"; exit 1; }
    ;;
  *) usage ;;
esac
