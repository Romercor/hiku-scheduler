#!/usr/bin/bash
# Scheduler node: compile the steering object, build the hiku binary (L4 mode), and
# enable IP forwarding (the kernel forwards the rewritten packets to the worker /
# back to the client). Run on the scheduler after the repo is deployed.
set -e
GO_VER=1.22.6

sudo apt-get update -qq
sudo apt-get install -y -qq clang llvm libbpf-dev linux-libc-dev gcc make >/dev/null

if ! command -v /usr/local/go/bin/go >/dev/null; then
  curl -sSL "https://go.dev/dl/go${GO_VER}.linux-amd64.tar.gz" | sudo tar -C /usr/local -xz
fi
export PATH=$PATH:/usr/local/go/bin

sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null

sudo mkdir -p /app
ARCH=$(uname -m)
clang -O2 -g -Wall -target bpf -I"/usr/include/${ARCH}-linux-gnu" \
  -c src/steer/bpf/steer.bpf.c -o /tmp/steer.bpf.o
sudo cp /tmp/steer.bpf.o /app/steer.bpf.o

(
cd src || exit 1
./deps.sh
./build.sh
)
sudo cp src/bin/hiku /app/hiku
sudo cp steer.json /app/steer.json
echo "setup done: sudo /app/hiku steer -c /app/steer.json"
