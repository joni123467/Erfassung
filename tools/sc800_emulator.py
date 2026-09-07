#!/usr/bin/env python3
"""Send one documented ATTLOG-shaped request to a development server."""
import argparse
import urllib.parse
import urllib.request

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--server", default="http://127.0.0.1:8000")
p.add_argument("--serial", required=True)
p.add_argument("--user", required=True)
p.add_argument("--timestamp", required=True, help="YYYY-MM-DD HH:MM:SS")
p.add_argument("--status", default="0")
p.add_argument("--verify", default="4")
p.add_argument("--key", default="")
a = p.parse_args()
body = f"{a.user}\t{a.timestamp}\t{a.status}\t{a.verify}\t\n".encode()
url = a.server.rstrip("/") + "/iclock/cdata?" + urllib.parse.urlencode({"SN": a.serial, "table": "ATTLOG"})
headers = {"Content-Type": "text/plain"}
if a.key:
    headers["X-Terminal-Key"] = a.key
with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=10) as response:
    print(response.read().decode())
