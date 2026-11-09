#!/usr/bin/bash
# Runs one unattended cluster session: the steps of a session file in order, stopping at the first
# that fails, and destroys the cluster at the end whatever happened, then checks through the API
# that no server or storage is left and logs the remaining credit.
# Why: a chain that dies before its destroy leaves a paid cluster idle until someone notices.
# A session file holds one shell command per line, run from the repository root.
# usage: chain.sh <session_file>
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$REPO"
. /root/.upcloud.env

api() { curl -s -m 30 -H "Authorization: Bearer $UPCLOUD_TOKEN" "https://api.upcloud.com/1.3/$1"; }

finish() {
  trap - EXIT INT TERM HUP
  echo "=== $(date -u +%FT%TZ) destroy"
  for _ in $(seq 1 120); do
    (cd terraform-upcloud && terraform destroy -auto-approve -input=false -no-color | tail -1) &&
      [ "$(api server | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["servers"]["server"]))' 2>/dev/null)" = 0 ] && break
    echo "destroy not confirmed, retrying in 60 s"
    sleep 60
  done
  echo "=== servers: $(api server | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["servers"]["server"]))')" \
    "storages: $(api storage/private | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["storages"]["storage"]))')" \
    "credits: $(api account | python3 -c 'import json,sys; print(json.load(sys.stdin)["account"]["credits"] / 100)')"
}
trap finish EXIT
trap 'echo "=== interrupted"; exit 1' INT TERM HUP

while IFS= read -r step; do
  [[ "$step" =~ ^[[:space:]]*(#|$) ]] && continue
  echo "=== $(date -u +%FT%TZ) $step"
  if ! bash -c "$step" < /dev/null; then
    echo "=== $(date -u +%FT%TZ) STEP FAILED, ending the session"
    exit 1
  fi
done < "$1"
echo "=== $(date -u +%FT%TZ) SESSION DONE"
