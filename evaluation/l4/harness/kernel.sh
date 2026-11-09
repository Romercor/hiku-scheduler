#!/usr/bin/bash
# Upgrades every scheduler node to the HWE kernel and reboots it; nodes already on 6.x are left alone.
# Why: link.AttachTCX needs kernel >= 6.6, and Ubuntu 22.04 ships 5.15.
# usage: kernel.sh
. "$(dirname "$0")/lib.sh"

upgrade() {
  local h=$1 k
  for _ in $(seq 1 40); do sshx "$h" true 2>/dev/null && break; sleep 5; done
  k=$(sshx "$h" "uname -r")
  if [ "${k%%.*}" -lt 6 ]; then
    sshx "$h" "sudo cloud-init status --wait >/dev/null 2>&1; sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq linux-generic-hwe-22.04 >/dev/null 2>&1; sudo systemctl reboot"
    sleep 20
    for _ in $(seq 1 60); do sshx "$h" true 2>/dev/null && break; sleep 5; done
    k=$(sshx "$h" "uname -r")
  fi
  [ "${k%%.*}" -ge 6 ] && echo "$h kernel $k OK" || echo "$h kernel $k TOO OLD - link.AttachTCX will fail"
}

for h in "${SPUB[@]}"; do upgrade "$h" & done
wait
