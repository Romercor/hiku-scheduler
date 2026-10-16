#!/usr/bin/bash
# Prepares a scheduler node; run from the repo root after the repo is deployed.
# N_WORKERS is compiled into the kernel program, so it comes from the scheduler's config.
set -e
GO_VER=1.25.0
N_WORKERS=${N_WORKERS:-$(python3 -c 'import json;print(len(json.load(open("src/l4/config.json"))["workers"]))')}

sudo apt-get update -qq
sudo apt-get install -y -qq clang llvm libbpf-dev linux-libc-dev gcc make >/dev/null

if ! command -v /usr/local/go/bin/go >/dev/null; then
  curl -sSL "https://go.dev/dl/go${GO_VER}.linux-amd64.tar.gz" | sudo tar -C /usr/local -xz
fi
export PATH=$PATH:/usr/local/go/bin

sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null

sudo mkdir -p /app
ARCH=$(uname -m)
clang -O2 -g -Wall -target bpf -mcpu=v3 -I"/usr/include/${ARCH}-linux-gnu" \
  -DN_WORKERS="${N_WORKERS}" -DFN_MAX="${FN_MAX:-65536}" -DIDLE_MAX="${IDLE_MAX:-4096}" \
  -c src/l4/bpf/scheduler.bpf.c -o /tmp/scheduler.bpf.o
sudo cp /tmp/scheduler.bpf.o /app/scheduler.bpf.o

(
cd src || exit 1
./deps.sh
./build.sh
)
sudo cp src/bin/hiku /app/hiku
sudo cp src/l4/config.json /app/l4.json
echo "setup done: sudo /app/hiku l4 -c /app/l4.json"
