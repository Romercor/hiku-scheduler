# nginx gateway configs for the gateway arms: gw_l7 forwards to Hiku over kept-open connections, gw_l4 maps
# each function to its port on the L4 scheduler and opens one connection per call (nginx's default).
# args: trace_json scheduler_ip out_dir
import json, sys
funcs, sched, out = json.load(open(sys.argv[1])), sys.argv[2], sys.argv[3]
head = """worker_processes auto;
worker_rlimit_nofile 200000;
events { worker_connections 65536; }
http {
  access_log off;
  error_log /var/log/nginx/error.log crit;
"""
srv = "  server {\n    listen 127.0.0.1:9020 backlog=65535;\n    location / { %s }\n  }\n}\n"
open(out + "/gw_l7.conf", "w").write(head + "  upstream hiku { server %s:9020; keepalive 1024; }\n" % sched +
    srv % "proxy_pass http://hiku; proxy_http_version 1.1; proxy_set_header Connection \"\";")
m = "  map $uri $fport {\n    default 1;\n" + "".join("    /run/%s %d;\n" % (f["name"], f["port"]) for f in funcs) + "  }\n"
open(out + "/gw_l4.conf", "w").write(head + m + srv % ("proxy_pass http://%s:$fport;" % sched))
print(len(funcs), "functions")
