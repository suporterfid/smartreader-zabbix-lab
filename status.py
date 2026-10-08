"""Show what the lab is collecting for the bench reader.

  python status.py           # current state
  python status.py --wait    # first wait (up to 4 minutes) until every item has reported once
"""
import sys
import time

import provision
from lablib import ENV
from provision import HOST, call

provision.TOKEN = call("user.login", {"username": ENV["ZBX_WEB_USER"], "password": ENV["ZBX_WEB_PASSWORD"]})
hostid = call("host.get", {"filter": {"host": [HOST]}, "output": ["hostid"]})[0]["hostid"]


def items():
    return call("item.get", {"hostids": hostid, "output": ["name", "key_", "lastvalue", "lastclock", "state",
                                                           "error", "units", "type", "value_type"],
                             "sortfield": "name"})


if "--wait" in sys.argv:
    deadline = time.time() + 240
    while time.time() < deadline:
        pending = [i for i in items() if i["type"] not in ("17",) and i["lastclock"] == "0" and i["state"] == "0"
                   and i["value_type"] != "4"]
        if not pending:
            break
        print(f"waiting for {len(pending)} items ...", flush=True)
        time.sleep(15)

all_items = items()
unsupported = [i for i in all_items if i["state"] == "1"]
print(f"\n{len(all_items)} items, {len(unsupported)} not supported")
for i in unsupported:
    print(f"  UNSUPPORTED {i['key_']}: {i['error'][:160]}")

print("\nLatest values (text items and raw masters hidden):")
for i in all_items:
    if i["value_type"] in ("2", "4") or i["state"] == "1":
        continue
    value = i["lastvalue"] if i["lastclock"] != "0" else "(no data yet)"
    print(f"  {i['name'][:55]:55} {value} {i['units']}")

print("\nTrap items:")
for i in all_items:
    if i["type"] == "17":
        print(f"  {i['name']:40} {'last ' + time.strftime('%H:%M:%S', time.localtime(int(i['lastclock']))) if i['lastclock'] != '0' else 'no trap yet'}")

print("\nOpen problems:")
for p in call("problem.get", {"hostids": hostid, "output": ["name", "severity", "opdata"], "sortfield": ["eventid"],
                              "sortorder": "DESC"}):
    sev = ["n/c", "info", "warning", "average", "high", "disaster"][int(p["severity"])]
    print(f"  [{sev}] {p['name']}  {p.get('opdata', '')}")

host = call("host.get", {"hostids": hostid, "output": ["host"], "selectInterfaces": ["ip", "available", "error"],
                         "selectInventory": ["name", "serialno_a", "hardware", "os", "software_app_a", "location"]})[0]
print("\nInterfaces:", [(i["ip"], {"0": "unknown", "1": "available", "2": "unavailable"}[i["available"]])
                        for i in host["interfaces"]])
print("Inventory:", {k: v for k, v in host["inventory"].items() if v})
