#!/bin/bash
# Session n12 cluster gate: a fast scheduler (speed loop <= 0.40 s, as in n7) and a client with little
# CPU steal when all 16 vCPUs are busy (< 5 %). Replaces the failing server, at most 4 times; after that
# it goes on with the client as it is (the per-run steal check in sat8_loop.sh still applies).
cd /root/rt/pw
bash evaluation/l4/harness/cluster.sh up || exit 1
. evaluation/l4/harness/lib.sh
probe() {   # %steal on the client from /proc/stat with all vCPUs busy for 25 s (mpstat comes only with the setup)
  sshx "${CL[0]}" 'n=$(nproc); for i in $(seq $n); do timeout 30 sh -c "while :; do :; done" & done; sleep 3; a=$(head -1 /proc/stat); sleep 25; b=$(head -1 /proc/stat); wait; echo $a $b | awk "{t1=0; t2=0; for (i=2;i<=9;i++) {t1+=\$i; t2+=\$(i+11)}; printf \"%.1f\", 100*(\$20-\$9)/(t2-t1)}"'
}
for a in 1 2 3 4 5; do
  bash evaluation/l4/harness/cluster.sh cpu | tee /tmp/cpu.txt
  . evaluation/l4/harness/lib.sh
  s_ok=1; awk -v ip=${SPUB[0]} '$1==ip {f=1; if ($(NF-1) > 0.40) exit 1} END {if (!f) exit 1}' /tmp/cpu.txt || s_ok=0
  st=$(probe); echo "client steal under full load: $st %"
  c_ok=$(awk -v s="$st" 'BEGIN {print (s != "" && s < 5) ? 1 : 0}')
  [ $s_ok = 1 ] && [ $c_ok = 1 ] && exit 0
  [ $a = 5 ] && { [ $s_ok = 1 ] && { echo "client steal gate not met after 4 replacements, going on"; exit 0; }; exit 1; }
  t=""; [ $s_ok = 0 ] && t="$t -target=upcloud_server.scheduler"; [ $c_ok = 0 ] && t="$t -target=upcloud_server.client"
  echo "replacing:$t (attempt $a)"
  (cd terraform-upcloud && terraform destroy -auto-approve -input=false -no-color $t | tail -1; sleep 90; terraform apply -auto-approve -input=false -no-color | tail -1)
  sleep 30; bash evaluation/l4/harness/cluster.sh up > /dev/null
done
exit 1
