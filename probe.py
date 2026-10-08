"""Read-only look at the bench reader before the lab changes anything."""
import json

from lablib import as_json, cap_get, reader_get, rshell


def section(title):
    print(f"\n=== {title} ===")


section("RShell: show snmp summary")
print(rshell("show snmp summary").strip())

section("Reader REST: /status and /system/image")
for path in ("/status", "/system/image"):
    try:
        status, body = reader_get(path)
        print(path, status, json.dumps(as_json(body))[:400])
    except Exception as exc:  # noqa: BLE001 - report and keep probing
        print(path, "ERROR", exc)

section("CAP: /metrics (names only)")
try:
    status, body = cap_get("/metrics")
    names = [line.split()[0] for line in body.splitlines() if line and not line.startswith("#")]
    print(status, len(names), "metrics")
    for name in names:
        print("  ", name)
except Exception as exc:  # noqa: BLE001
    print("ERROR", exc)

section("CAP: /api/status/overview")
try:
    status, body = cap_get("/api/status/overview")
    data = as_json(body)
    print(status)
    for item in data.get("items", []):
        print(f"   {item.get('key'):18} {item.get('state'):7} {item.get('detail')}")
except Exception as exc:  # noqa: BLE001
    print("ERROR", exc)

section("CAP: /api/getstatus")
try:
    status, body = cap_get("/api/getstatus")
    print(status, json.dumps(as_json(body))[:300])
except Exception as exc:  # noqa: BLE001
    print("ERROR", exc)
