"""Create (or re-create) the lab's Zabbix templates, triggers and the bench reader host through the Zabbix API.

Safe to re-run: it deletes the lab's own templates and host first, then builds them again.
  python provision.py
"""
import json
import time
import urllib.request

from lablib import ENV

API = "http://localhost:8080/api_jsonrpc.php"
TOKEN = None

T_SNMP = "Impinj R700 by SNMP"
T_CAP = "SmartReader CAP by HTTP"
T_REST = "Impinj R700 REST API"
T_SR3 = "SmartReader CAP by SNMPv3"
HOST = "r700-bench"
SIM_HOST = "smartreader-snmpv3-sim"
SIM_IP = "172.31.67.20"  # pinned in docker-compose.yml
# Address Zabbix sees as the source of the reader's traps. Docker Desktop rewrites it to the gateway of the
# lab network (see docker-compose.yml); set TRAP_SOURCE_IP to the reader's own IP, or leave it empty, where
# the source address is kept (Docker Engine on Linux, or a native proxy).
TRAP_SOURCE_IP = ENV.get("TRAP_SOURCE_IP", "172.31.67.1")

# SmartReader's own SNMPv3 agent (off unless .env turns it on): see docs/smartreader-snmpv3.md.
SR3_ON_READER = ENV.get("SR_SNMPV3_ENABLED", "0") == "1"
SR3_SIMULATOR = ENV.get("SR_SNMPV3_SIMULATOR", "0") == "1"
SR3_PORT = ENV.get("SR_SNMPV3_PORT", "1161")
SR3_ROOT = ENV.get("SR_SNMP_ROOT", "1.3.6.1.4.1.8072.9999.9999.7").strip(".")
AUTH_PROTOCOLS = {"SHA1": 1, "SHA224": 2, "SHA256": 3, "SHA384": 4, "SHA512": 5}
PRIV_PROTOCOLS = {"AES128": 1, "AES192": 2, "AES256": 3}
# Every SmartReader notification sits under {$SR.SNMP.ROOT}.0; snmptrapd prints it by name or number.
SR3_TRAP_KEY = 'snmptrap["netSnmpPlaypen\\.7\\.0\\.|8072\\.9999\\.9999\\.7\\.0\\."]'

# Item types, value types and preprocessing step types from the Zabbix 7.0 API.
SNMP, TRAP, SIMPLE, INTERNAL, DEPENDENT, HTTP = 20, 17, 3, 5, 18, 19
FLOAT, CHAR, LOG, UINT, TEXT = 0, 1, 2, 3, 4
MULT, BOOL2DEC, CHANGE_SEC, JSONPATH, JAVASCRIPT, PROM, WALK_VALUE, WALK_JSON = 1, 6, 10, 12, 21, 22, 28, 29
INFO, WARNING, AVERAGE, HIGH = 1, 2, 3, 4
INV_NAME, INV_SERIAL_A, INV_HARDWARE, INV_OS, INV_SOFTWARE_APP_A, INV_LOCATION = 3, 8, 14, 5, 18, 24


def call(method, params):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json-rpc"})
    if TOKEN and method not in ("user.login", "apiinfo.version"):
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.load(resp)
    if "error" in out:
        raise RuntimeError(f"{method}: {out['error'].get('data') or out['error']}")
    return out["result"]


def step(kind, params="", on_fail=0, fail_value=""):
    return {"type": kind, "params": params, "error_handler": on_fail, "error_handler_params": fail_value}


def updown_map(tid):
    return call("valuemap.create", {"hostid": tid, "name": "Up/Down", "mappings": [
        {"value": "0", "newvalue": "Down"}, {"value": "1", "newvalue": "Up"}]})["valuemapids"][0]


def tags(**kv):
    return [{"tag": k, "value": v} for k, v in kv.items()]


class Builder:
    """Collects item ids by key so triggers and dependent items can refer to them."""

    def __init__(self, hostid):
        self.hostid = hostid
        self.items = {}

    def item(self, name, key, kind, value_type, **extra):
        params = {"hostid": self.hostid, "name": name, "key_": key, "type": kind, "value_type": value_type}
        params.setdefault("delay", "0" if kind in (DEPENDENT, TRAP) else "1m")
        params.update(extra)
        if kind in (DEPENDENT, TRAP):
            params["delay"] = "0"
        if "master" in params:
            params["master_itemid"] = self.items[params.pop("master")]
        self.items[key] = call("item.create", params)["itemids"][0]
        return self.items[key]

    def dep(self, name, key, master, value_type, preprocessing, **extra):
        return self.item(name, key, DEPENDENT, value_type, master=master, preprocessing=preprocessing, **extra)


def wait_for_api():
    for _ in range(90):
        try:
            return call("apiinfo.version", {})
        except Exception:  # noqa: BLE001 - server still starting
            time.sleep(2)
    raise SystemExit("Zabbix API did not come up on http://localhost:8080")


def cleanup():
    hosts = call("host.get", {"filter": {"host": [HOST, SIM_HOST]}, "output": ["hostid"]})
    if hosts:
        call("host.delete", [h["hostid"] for h in hosts])
    templates = call("template.get", {"filter": {"host": [T_SNMP, T_CAP, T_REST, T_SR3]}, "output": ["templateid"]})
    if templates:
        call("template.delete", [t["templateid"] for t in templates])


def group(kind, name):
    found = call(f"{kind}.get", {"filter": {"name": [name]}, "output": ["groupid"]})
    return found[0]["groupid"] if found else call(f"{kind}.create", {"name": name})["groupids"][0]


def template(name, groupid, description, macros=(), visible_name=None):
    return call("template.create", {
        "host": name, "name": visible_name or name, "groups": [{"groupid": groupid}], "description": description,
        "macros": list(macros),
    })["templateids"][0]


def trigger(description, expression, priority, **extra):
    params = {"description": description, "expression": expression, "priority": priority}
    params.update(extra)
    return call("trigger.create", params)["triggerids"][0]


# ---------------------------------------------------------------- Impinj R700 by SNMP

def build_snmp_template(groupid):
    tid = template(T_SNMP, groupid, "Bench R700 over SNMP v2c: system, RFID status, per-antenna status, traps. "
                   "Built from the partner Zabbix guide and checked against a real snmpwalk (fw 10.4).",
                   macros=[{"macro": "{$R700.ANTENNAS}", "value": ".*",
                            "description": "Regex of antenna port numbers to discover and alert on"}])
    epcg = call("valuemap.create", {"hostid": tid, "name": "EPCglobal status", "mappings": [
        {"value": "1", "newvalue": "unknown"}, {"value": "2", "newvalue": "other"},
        {"value": "3", "newvalue": "up"}, {"value": "4", "newvalue": "down"}]})["valuemapids"][0]
    updown = updown_map(tid)
    b = Builder(tid)
    T = T_SNMP

    b.item("Reachability (ICMP)", "icmpping", SIMPLE, UINT, valuemapid=updown, tags=tags(component="network"))
    b.item("ICMP response time", "icmppingsec", SIMPLE, FLOAT, units="s", tags=tags(component="network"))
    b.item("SNMP availability", "zabbix[host,snmp,available]", INTERNAL, UINT, tags=tags(component="snmp"))
    # sysUpTime is the SNMP agent's uptime: it restarts whenever SNMP settings change. Reader uptime comes
    # from the CAP template (/proc/uptime) and the REST template instead.
    b.item("SNMP agent uptime", "r700.snmp.uptime", SNMP, FLOAT, snmp_oid="1.3.6.1.2.1.1.3.0", units="uptime",
           preprocessing=[step(MULT, "0.01")], tags=tags(component="snmp"))
    b.item("System description", "r700.sysdescr", SNMP, CHAR, snmp_oid="1.3.6.1.2.1.1.1.0", delay="1h",
           inventory_link=INV_HARDWARE, tags=tags(component="system"))
    b.item("System object ID", "r700.sysobjectid", SNMP, CHAR, snmp_oid="1.3.6.1.2.1.1.2.0", delay="1h",
           tags=tags(component="system"))
    b.item("System name", "r700.sysname", SNMP, CHAR, snmp_oid="1.3.6.1.2.1.1.5.0", delay="1h",
           inventory_link=INV_NAME, tags=tags(component="system"))
    b.item("System location", "r700.syslocation", SNMP, CHAR, snmp_oid="1.3.6.1.2.1.1.6.0", delay="1h",
           inventory_link=INV_LOCATION, tags=tags(component="system"))
    b.item("Serial number", "r700.serial", SNMP, CHAR, snmp_oid="1.3.6.1.4.1.22695.1.1.1.1.1.4.0", delay="1h",
           inventory_link=INV_SERIAL_A, tags=tags(component="system"))
    b.item("Device role", "r700.role", SNMP, CHAR, snmp_oid="1.3.6.1.4.1.22695.1.1.1.1.1.2.0", delay="1h",
           tags=tags(component="system"))
    b.item("RFID operational status", "r700.rfid.oper", SNMP, UINT, snmp_oid="1.3.6.1.4.1.22695.1.1.1.1.3.1.0",
           valuemapid=epcg, tags=tags(component="rfid"))

    # Global counters (epcgGlobalCountersTable, column 2 indexed by counter number).
    b.item("Global counters (walk)", "r700.counters.walk", SNMP, TEXT,
           snmp_oid="walk[1.3.6.1.4.1.22695.1.1.1.1.2.1.2]", history="1h", tags=tags(component="rfid"))
    for name, key, n in (("Tags identified (all antennas)", "r700.tags.identified", 1),
                         ("Memory read failures (all antennas)", "r700.reads.failed", 3),
                         ("Memory read operations (all antennas)", "r700.reads.ops", 18)):
        b.dep(name, key, "r700.counters.walk", UINT,
              [step(WALK_VALUE, f"1.3.6.1.4.1.22695.1.1.1.1.2.1.2.{n}\n0")], tags=tags(component="rfid"))

    # Per-antenna discovery from the read point and antenna read point tables.
    walk_key = "r700.antennas.walk"
    b.item("Antenna tables (walk)", walk_key, SNMP, TEXT,
           snmp_oid="walk[1.3.6.1.4.1.22695.1.1.1.2.1,1.3.6.1.4.1.22695.1.1.1.3.1]", history="1h",
           tags=tags(component="antenna"))
    rule = call("discoveryrule.create", {
        "hostid": tid, "name": "Antenna discovery", "key_": "r700.antenna.discovery", "type": DEPENDENT,
        "master_itemid": b.items[walk_key], "delay": "0", "lifetime": "1d",
        "preprocessing": [step(WALK_JSON, "{#RPNAME}\n1.3.6.1.4.1.22695.1.1.1.2.1.1.2\n0")],
        "filter": {"evaltype": 0, "conditions": [
            {"macro": "{#SNMPINDEX}", "value": "{$R700.ANTENNAS}", "operator": 8}]},
    })["itemids"][0]

    def proto(name, key, value_type, oid_prefix, extra_steps=(), **extra):
        params = {"ruleid": rule, "hostid": tid, "name": name, "key_": key, "type": DEPENDENT, "delay": "0",
                  "value_type": value_type, "master_itemid": b.items[walk_key],
                  "preprocessing": [step(WALK_VALUE, f"{oid_prefix}.{{#SNMPINDEX}}\n0"), *extra_steps],
                  "tags": tags(component="antenna", antenna="{#SNMPINDEX}")}
        params.update(extra)
        return call("itemprototype.create", params)["itemids"][0]

    proto("Antenna {#SNMPINDEX}: operational status", "r700.antenna.oper[{#SNMPINDEX}]", UINT,
          "1.3.6.1.4.1.22695.1.1.1.2.1.1.5", valuemapid=epcg)
    proto("Antenna {#SNMPINDEX}: tags identified", "r700.antenna.tags[{#SNMPINDEX}]", UINT,
          "1.3.6.1.4.1.22695.1.1.1.3.1.1.1")
    proto("Antenna {#SNMPINDEX}: memory read operations", "r700.antenna.readops[{#SNMPINDEX}]", UINT,
          "1.3.6.1.4.1.22695.1.1.1.3.1.1.25")
    proto("Antenna {#SNMPINDEX}: memory read failures", "r700.antenna.readfail[{#SNMPINDEX}]", UINT,
          "1.3.6.1.4.1.22695.1.1.1.3.1.1.3")
    proto("Antenna {#SNMPINDEX}: transmit power", "r700.antenna.power[{#SNMPINDEX}]", FLOAT,
          "1.3.6.1.4.1.22695.1.1.1.3.1.1.22", extra_steps=[step(MULT, "0.01")], units="dBm")
    proto("Antenna {#SNMPINDEX}: time energized", "r700.antenna.energized[{#SNMPINDEX}]", FLOAT,
          "1.3.6.1.4.1.22695.1.1.1.3.1.1.24", extra_steps=[step(MULT, "0.001")], units="uptime")
    call("triggerprototype.create", {
        "description": "Antenna {#SNMPINDEX} is down (disconnected or faulty)",
        "expression": f"last(/{T}/r700.antenna.oper[{{#SNMPINDEX}}])=4", "priority": AVERAGE})

    # Traps. On this lab they arrive from the Docker gateway, so the host binds them to a trap-only interface.
    for name, key in (
        ("Trap: unexpected restart", 'snmptrap["25882\\.4\\.1|impUnexpectedRestart"]'),
        ("Trap: authentication failure", 'snmptrap["authenticationFailure|6\\.3\\.1\\.1\\.5\\.5"]'),
        ("Trap: planned shutdown", 'snmptrap["nsNotifyShutdown|8072\\.4\\.0\\.2"]'),
        ("Trap: SNMP service restarted", 'snmptrap["coldStart|nsNotifyRestart|6\\.3\\.1\\.1\\.5\\.1|8072\\.4\\.0\\.3"]'),
        ("Trap: other", "snmptrap.fallback"),
    ):
        b.item(name, key, TRAP, LOG, tags=tags(component="traps"))

    unreachable = trigger("R700 unreachable (no ICMP reply)", f"max(/{T}/icmpping,#3)=0", HIGH)
    dep = [{"triggerid": unreachable}]
    trigger("No SNMP data from the reader", f"max(/{T}/zabbix[host,snmp,available],10m)=0", AVERAGE,
            dependencies=dep)
    trigger("RFID subsystem down", f"last(/{T}/r700.rfid.oper)=4", HIGH, dependencies=dep)
    trigger("RFID status unknown for 15 minutes", f'count(/{T}/r700.rfid.oper,15m,"ne","1")=0', WARNING,
            dependencies=dep)
    trigger("SNMP agent restarted (settings changed or reader rebooted)", f"last(/{T}/r700.snmp.uptime)<600",
            INFO, dependencies=dep)
    trap_triggers = (
        ("Reader restarted unexpectedly (trap)", 'snmptrap["25882\\.4\\.1|impUnexpectedRestart"]', HIGH),
        ("SNMP authentication failure (trap)", 'snmptrap["authenticationFailure|6\\.3\\.1\\.1\\.5\\.5"]', WARNING),
        ("Reader shutdown requested (trap)", 'snmptrap["nsNotifyShutdown|8072\\.4\\.0\\.2"]', INFO),
        ("Unrecognised SNMP trap received", "snmptrap.fallback", INFO),
    )
    for description, key, prio in trap_triggers:
        trigger(description, f"nodata(/{T}/{key},15m)=0", prio, manual_close=1,
                comments="Raised for 15 minutes after the trap arrives; close it manually once handled.")
    return tid


# ---------------------------------------------------------------- SmartReader CAP by HTTP

def build_cap_template(groupid):
    tid = template(T_CAP, groupid, "SmartReader CAP health over HTTPS 8443: /metrics, /api/status/overview, "
                   "/api/getstatus, /api/reader-rest-health.", macros=[
                       {"macro": "{$CAP.PORT}", "value": "8443"},
                       {"macro": "{$CAP.USER}", "value": "admin"},
                       {"macro": "{$CAP.PASSWORD}", "value": "", "type": 1},
                       {"macro": "{$CAP.DISK.MAX}", "value": "85"},
                       {"macro": "{$CAP.PENDING.MAX}", "value": "100"},
                       {"macro": "{$CAP.TEMP.MARGIN}", "value": "5"},
                   ])
    updown = updown_map(tid)
    capstate = call("valuemap.create", {"hostid": tid, "name": "CAP component state", "mappings": [
        {"value": "0", "newvalue": "Off"}, {"value": "1", "newvalue": "OK"},
        {"value": "2", "newvalue": "Warning"}, {"value": "3", "newvalue": "Error"}]})["valuemapids"][0]
    b = Builder(tid)
    T = T_CAP
    http = {"authtype": 1, "username": "{$CAP.USER}", "password": "{$CAP.PASSWORD}", "verify_peer": 0,
            "verify_host": 0, "timeout": "10s", "status_codes": "200", "history": "1h", "trends": "0"}

    def cap_url(path):
        return f"https://{{HOST.CONN}}:{{$CAP.PORT}}{path}"

    b.item("CAP /metrics (raw)", "cap.metrics.raw", HTTP, TEXT, url=cap_url("/metrics"), **http,
           tags=tags(component="cap"))
    metrics = (
        ("CAP connected to MQTT broker", "cap.mqtt.connected", "mqttservice_mqtt_connected", UINT, "", []),
        ("CAP MQTT messages pending", "cap.mqtt.pending", "mqttservice_messages_pending", UINT, "", []),
        ("CAP application uptime", "cap.app.uptime",
         "metricsmonitoringservice_system_application_uptime__seconds_", FLOAT, "uptime", []),
        ("Reader OS uptime (from CAP)", "cap.os.uptime",
         "metricsmonitoringservice_system_os_uptime__seconds_", FLOAT, "uptime", []),
        ("CAP process memory", "cap.memory", "metricsmonitoringservice_system_memory_usage__mb_", FLOAT, "B",
         [step(MULT, "1048576")]),
        ("CAP file system used", "cap.disk.pused", "metricsmonitoringservice_system_disk_usage____", FLOAT, "%",
         []),
        ("CPU temperature", "cap.cpu.temp", "metricsmonitoringservice_system_cpu_temperature___c_", FLOAT, "°C",
         []),
        ("CPU temperature limit", "cap.cpu.temp.max",
         "metricsmonitoringservice_system_cpu_max_allowed_temp___c_", FLOAT, "°C", []),
        # CAP 4.0.1.109 reports a since-boot average here; later releases the load over the last 10 s.
        ("CAP process CPU", "cap.cpu.avg", "metricsmonitoringservice_system_cpu_usage____", FLOAT, "%",
         []),
        ("eth0 received", "cap.net.rx", "metricsmonitoringservice_system_network_rx_bytes", FLOAT, "bps",
         [step(CHANGE_SEC), step(MULT, "8")]),
        ("eth0 sent", "cap.net.tx", "metricsmonitoringservice_system_network_tx_bytes", FLOAT, "bps",
         [step(CHANGE_SEC), step(MULT, "8")]),
        ("Socket output: connected clients", "cap.socket.clients", "tcpsocketservice_connected_clients", UINT, "",
         []),
    )
    for name, key, metric, vtype, units, extra in metrics:
        b.dep(name, key, "cap.metrics.raw", vtype, [step(PROM, f"{metric}\nvalue\n"), *extra], units=units,
              tags=tags(component="cap"))
    call("item.update", {"itemid": b.items["cap.mqtt.connected"], "valuemapid": updown})
    for stat in ("rx_errors", "tx_errors", "rx_dropped", "tx_dropped"):
        # These counters only appear in /metrics once they are above zero.
        b.dep(f"eth0 {stat.replace('_', ' ')}", f"cap.net.{stat}", "cap.metrics.raw", UINT,
              [step(PROM, f"metricsmonitoringservice_system_network_{stat}\nvalue\n", on_fail=2, fail_value="0")],
              tags=tags(component="network"))

    b.item("CAP status overview (raw)", "cap.overview.raw", HTTP, TEXT, url=cap_url("/api/status/overview"),
           **http, tags=tags(component="cap"))
    rule = call("discoveryrule.create", {
        "hostid": tid, "name": "CAP component discovery", "key_": "cap.overview.discovery", "type": DEPENDENT,
        "master_itemid": b.items["cap.overview.raw"], "delay": "0", "lifetime": "1d",
        "preprocessing": [step(JSONPATH, "$.items")],
        "lld_macro_paths": [{"lld_macro": "{#KEY}", "path": "$.key"}, {"lld_macro": "{#LABEL}", "path": "$.label"}],
    })["itemids"][0]
    for field in ("state", "detail"):
        call("itemprototype.create", {
            "ruleid": rule, "hostid": tid, "name": f"CAP {{#LABEL}}: {field}", "key_": f"cap.{field}[{{#KEY}}]",
            "type": DEPENDENT, "delay": "0", "value_type": CHAR, "master_itemid": b.items["cap.overview.raw"],
            "preprocessing": [step(JSONPATH, f"$.items[?(@.key=='{{#KEY}}')].{field}.first()")],
            "tags": tags(component="cap", cap_component="{#KEY}")})
    # Numeric twin of the state, so dashboards can colour it: gray 0, green 1, yellow/amber 2, red 3.
    call("itemprototype.create", {
        "ruleid": rule, "hostid": tid, "name": "CAP {#LABEL}: level", "key_": "cap.level[{#KEY}]",
        "type": DEPENDENT, "delay": "0", "value_type": UINT, "master_itemid": b.items["cap.overview.raw"],
        "valuemapid": capstate,
        "preprocessing": [
            step(JSONPATH, "$.items[?(@.key=='{#KEY}')].state.first()"),
            step(JAVASCRIPT, "var m = {gray: 0, green: 1, yellow: 2, amber: 2, red: 3};\n"
                             "return m.hasOwnProperty(value) ? m[value] : 0;"),
        ],
        "tags": tags(component="cap", cap_component="{#KEY}")})
    call("triggerprototype.create", {
        "description": "CAP {#LABEL} is red", "priority": HIGH, "opdata": "{ITEM.LASTVALUE2}",
        "expression": f'last(/{T}/cap.state[{{#KEY}}])="red" and length(last(/{T}/cap.detail[{{#KEY}}]))>=0'})
    call("triggerprototype.create", {
        "description": "CAP {#LABEL} is yellow for 15 minutes", "priority": WARNING, "opdata": "{ITEM.LASTVALUE2}",
        "expression": f'count(/{T}/cap.state[{{#KEY}}],15m,"ne","yellow")=0'
                      f' and length(last(/{T}/cap.detail[{{#KEY}}]))>=0'})

    b.item("CAP inventory status (raw)", "cap.getstatus.raw", HTTP, TEXT, url=cap_url("/api/getstatus"), **http,
           tags=tags(component="cap"))
    b.dep("CAP inventory status", "cap.inventory.status", "cap.getstatus.raw", CHAR, [step(JSONPATH, "$[0].status")],
          tags=tags(component="cap"))
    b.item("CAP link to reader REST API (raw)", "cap.readerhealth.raw", HTTP, TEXT,
           url=cap_url("/api/reader-rest-health"), **dict(http, history="1h"), delay="5m", tags=tags(component="cap"))
    b.dep("CAP link to reader REST API healthy", "cap.readerrest.healthy", "cap.readerhealth.raw", UINT,
          [step(JSONPATH, "$.healthy"), step(BOOL2DEC)], valuemapid=updown, tags=tags(component="cap"))
    b.dep("CAP link to reader REST API status", "cap.readerrest.status", "cap.readerhealth.raw", CHAR,
          [step(JSONPATH, "$.status")], tags=tags(component="cap"))

    down = trigger("CAP not answering on /metrics", f"nodata(/{T}/cap.app.uptime,5m)=1", HIGH)
    dep = [{"triggerid": down}]
    trigger("CAP restarted", f"last(/{T}/cap.app.uptime)<600", WARNING, dependencies=dep)
    trigger("Reader rebooted (OS uptime from CAP)", f"last(/{T}/cap.os.uptime)<600", WARNING, dependencies=dep)
    trigger("CAP lost the MQTT broker", f"max(/{T}/cap.mqtt.connected,5m)=0", HIGH, dependencies=dep)
    trigger("CAP MQTT messages backing up", f"min(/{T}/cap.mqtt.pending,10m)>{{$CAP.PENDING.MAX}}", AVERAGE,
            dependencies=dep)
    trigger("CAP file system above {$CAP.DISK.MAX}%", f"last(/{T}/cap.disk.pused)>{{$CAP.DISK.MAX}}", WARNING,
            dependencies=dep)
    trigger("Reader CPU running hot", f"last(/{T}/cap.cpu.temp)>last(/{T}/cap.cpu.temp.max)-{{$CAP.TEMP.MARGIN}}",
            WARNING, dependencies=dep)
    trigger("Inventory stopped", f'last(/{T}/cap.inventory.status)="STOPPED"', AVERAGE, dependencies=dep)
    trigger("CAP cannot use the reader REST API",
            f"last(/{T}/cap.readerrest.healthy)=0 and length(last(/{T}/cap.readerrest.status))>=0", HIGH,
            opdata="{ITEM.LASTVALUE2}", dependencies=dep)
    return tid


# ---------------------------------------------------------------- Impinj R700 REST API

def build_rest_template(groupid):
    tid = template(T_REST, groupid, "Values only the reader's own REST API offers: current CPU and memory, "
                   "temperature, uptime, firmware and installed CAP image.", macros=[
                       {"macro": "{$READER.USER}", "value": "root"},
                       {"macro": "{$READER.PASSWORD}", "value": "", "type": 1},
                   ])
    b = Builder(tid)
    T = T_REST
    http = {"authtype": 1, "username": "{$READER.USER}", "password": "{$READER.PASSWORD}", "verify_peer": 0,
            "verify_host": 0, "timeout": "10s", "status_codes": "200", "history": "1h", "trends": "0"}

    def url(path):
        return f"https://{{HOST.CONN}}/api/v1{path}"

    b.item("Reader REST /status (raw)", "r700rest.status.raw", HTTP, TEXT, url=url("/status"), **http,
           tags=tags(component="rest"))
    b.dep("Reader inventory status (REST)", "r700rest.status", "r700rest.status.raw", CHAR,
          [step(JSONPATH, "$.status")], tags=tags(component="rest"))
    b.dep("Reader active preset", "r700rest.preset", "r700rest.status.raw", CHAR,
          [step(JSONPATH, "$.activePreset.id", on_fail=2, fail_value="none")], tags=tags(component="rest"))
    b.item("Reader REST /system/utilization (raw)", "r700rest.util.raw", HTTP, TEXT, url=url("/system/utilization"),
           **http, tags=tags(component="rest"))
    b.dep("Reader CPU utilization", "r700rest.cpu", "r700rest.util.raw", FLOAT, [step(JSONPATH, "$.cpuUtilization")],
          units="%", tags=tags(component="rest"))
    b.dep("Reader memory utilization", "r700rest.memory", "r700rest.util.raw", FLOAT,
          [step(JSONPATH, "$.memoryUtilization")], units="%", tags=tags(component="rest"))
    b.item("Reader REST /system/temperature (raw)", "r700rest.temp.raw", HTTP, TEXT, url=url("/system/temperature"),
           **http, delay="5m", tags=tags(component="rest"))
    b.dep("Reader system temperature", "r700rest.temp", "r700rest.temp.raw", FLOAT,
          [step(JSONPATH, "$.systemTemperature")], units="°C", tags=tags(component="rest"))
    b.item("Reader REST /system/time (raw)", "r700rest.time.raw", HTTP, TEXT, url=url("/system/time"), **http,
           tags=tags(component="rest"))
    b.dep("Reader uptime (REST)", "r700rest.uptime", "r700rest.time.raw", FLOAT, [step(JSONPATH, "$.upTime")],
          units="uptime", tags=tags(component="rest"))
    b.item("Reader REST /system/image (raw)", "r700rest.image.raw", HTTP, TEXT, url=url("/system/image"),
           **dict(http, history="1d"), delay="1h", tags=tags(component="rest"))
    b.dep("Reader firmware", "r700rest.firmware", "r700rest.image.raw", CHAR, [step(JSONPATH, "$.primaryFirmware")],
          inventory_link=INV_OS, tags=tags(component="rest"))
    b.dep("Installed CAP image", "r700rest.cap", "r700rest.image.raw", CHAR, [step(JSONPATH, "$.primaryCustomer")],
          inventory_link=INV_SOFTWARE_APP_A, tags=tags(component="rest"))

    trigger("Reader CPU above 90% for 15 minutes", f"min(/{T}/r700rest.cpu,15m)>90", WARNING)
    trigger("Reader rebooted (REST uptime)", f"last(/{T}/r700rest.uptime)<600", WARNING)
    trigger("Reader REST API not answering", f"nodata(/{T}/r700rest.uptime,5m)=1", AVERAGE)
    trigger("Installed CAP image changed", f"change(/{T}/r700rest.cap)<>0", INFO, manual_close=1)
    return tid


# ---------------------------------------------------------------- SmartReader CAP by SNMPv3

# The informs of SmartReader's agent (SMARTREADER-MIB, smartReaderNotifications): number, name, severity, text.
# One trap item and one trigger each; the others reach the catch-all item below. snmptrapd prints an OID by name or
# by number, so the key accepts both.
SR3_NOTIFICATIONS = (
    (1, "capStarted", INFO, "SmartReader CAP started (inform)"),
    (3, "mqttDisconnected", WARNING, "SmartReader CAP lost its MQTT broker (inform)"),
    (4, "mqttConnectFailed", WARNING, "SmartReader CAP cannot connect to its MQTT broker (inform)"),
    (7, "readerLifecycleFault", HIGH, "SmartReader CAP cannot work with the reader (inform)"),
    (9, "readerRestUnhealthy", HIGH, "Reader REST API unhealthy (inform)"),
    (11, "networkLost", HIGH, "Reader lost its network (inform)"),
    (13, "thresholdCrossed", WARNING, "Reader CPU, memory, disk or temperature over its limit (inform)"),
    (15, "certificateExpiring", WARNING, "SmartReader certificate expires in under 30 days (inform)"),
    (16, "certificateExpired", AVERAGE, "SmartReader certificate expired (inform)"),
    (17, "antennaStatusChanged", WARNING, "Antenna operational status changed (inform)"),
    (18, "bootReasonChanged", INFO, "Reader booted again (inform)"),
)


def sr3_trap_key(number, name):
    return f'snmptrap["(netSnmpPlaypen\\.7\\.0\\.|8072\\.9999\\.9999\\.7\\.0\\.){number}(\\D|$)|{name}"]'


def build_sr3_template(groupid):
    """SmartReader's own SNMPv3 agent: CAP health without HTTP credentials in Zabbix.

    The OIDs follow SMARTREADER-MIB (docs/Snmp/MIB-REFERENCE.md in the SmartReader repository) and sit under the
    root in {$SR.SNMP.ROOT}. The root is provisional until Impinj allocates the arc; then only that macro and the
    trap keys change.
    """
    tid = template(T_SR3, groupid, "SmartReader CAP health from the CAP's own SNMPv3 agent (authPriv, read-only): "
                   "CPU, memory, disk, temperatures, uptimes, MQTT, the antennas and components (low-level "
                   "discovery), the agent's counters and SmartReader's SNMPv3 informs. The CAP admin password and "
                   "the reader's root password are not needed. The interface is SNMPv3 on UDP 1161. The OIDs sit "
                   "under a provisional root until Impinj allocates the arc.", macros=[
                       {"macro": "{$SR.SNMP.ROOT}", "value": SR3_ROOT,
                        "description": "Root of SMARTREADER-MIB (provisional)"},
                       {"macro": "{$SR.DISK.MAX}", "value": "85"},
                       {"macro": "{$SR.PENDING.MAX}", "value": "100"},
                       {"macro": "{$SR.TEMP.MARGIN}", "value": "5"},
                   ])
    updown = updown_map(tid)
    b = Builder(tid)
    T = T_SR3
    root = "{$SR.SNMP.ROOT}"
    obj = f"{root}.2"  # smartReaderObjects
    t3 = tags(component="smartreader-snmpv3")

    # Created disabled: on a host with two SNMP interfaces Zabbix links them to the main (v2c) one and may
    # poll them there before they are moved. point_sr3_items / build_sim_host enable them on the right one.
    def snmp(name, key, oid, vtype, delay="1m", **extra):
        return b.item(name, key, SNMP, vtype, snmp_oid=oid, delay=delay, tags=t3, status=1, **extra)

    # The agent's own identity. sysUpTime is the agent's uptime, by definition (RFC 3418).
    snmp("SNMPv3 agent uptime", "sr3.agent.uptime", "1.3.6.1.2.1.1.3.0", FLOAT, units="uptime",
         preprocessing=[step(MULT, "0.01")])
    snmp("SNMPv3 agent description", "sr3.sysdescr", "1.3.6.1.2.1.1.1.0", CHAR, delay="1h")
    snmp("SNMPv3 agent object ID", "sr3.sysobjectid", "1.3.6.1.2.1.1.2.0", CHAR, delay="1h")
    snmp("SNMPv3 engine ID", "sr3.engine.id", "1.3.6.1.6.3.10.2.1.1.0", CHAR, delay="1h")
    snmp("SNMPv3 engine boots", "sr3.engine.boots", "1.3.6.1.6.3.10.2.1.2.0", UINT, delay="5m")

    # Health, as the CAP already collects it (the same sources as /metrics): srSystem.
    health = (
        ("CAP process CPU", "sr3.cpu", "1.4", FLOAT, "%", [step(MULT, "0.01")]),
        ("CAP process memory", "sr3.memory", "1.5", FLOAT, "B", [step(MULT, "1048576")]),
        ("CAP file system used", "sr3.disk.pused", "1.6", FLOAT, "%", [step(MULT, "0.01")]),
        ("Reader OS uptime", "sr3.os.uptime", "1.3", FLOAT, "uptime", []),
        ("CAP application uptime", "sr3.app.uptime", "1.2", FLOAT, "uptime", []),
        ("CPU temperature", "sr3.cpu.temp", "1.7", FLOAT, "°C", [step(MULT, "0.1")]),
        ("CPU temperature limit", "sr3.cpu.temp.max", "1.8", FLOAT, "°C", [step(MULT, "0.1")]),
        ("CPU temperature peak", "sr3.cpu.temp.peak", "1.9", FLOAT, "°C", [step(MULT, "0.1")]),
        # srOutputs: TruthValue, 1 true and 2 false; the trigger and the Up/Down map want 1 and 0.
        ("CAP connected to MQTT broker", "sr3.mqtt.connected", "3.1", UINT, "",
         [step(JAVASCRIPT, "return value == 1 ? 1 : 0;")]),
        ("CAP MQTT messages pending", "sr3.mqtt.pending", "3.2", UINT, "", []),
    )
    for name, key, index, vtype, units, pre in health:
        snmp(name, key, f"{obj}.{index}.0", vtype, units=units, preprocessing=pre)
    call("item.update", {"itemid": b.items["sr3.mqtt.connected"], "valuemapid": updown})
    snmp("CAP version", "sr3.cap.version", f"{obj}.1.1.0", CHAR, delay="1h")
    snmp("Reader firmware version", "sr3.reader.firmware", f"{obj}.2.6.0", CHAR, delay="1h")
    snmp("Reader model", "sr3.reader.model", f"{obj}.2.7.0", CHAR, delay="1h")
    snmp("Reader serial number", "sr3.reader.serial", f"{obj}.2.8.0", CHAR, delay="1h")
    snmp("Reader MAC address", "sr3.reader.mac", f"{obj}.2.9.0", CHAR, delay="1h")

    # The agent's own counters (srAgent), as rates.
    counters = (
        ("SNMPv3 requests", "sr3.requests", 1),
        ("SNMPv3 unknown user names", "sr3.unknown.users", 4),
        ("SNMPv3 wrong digests (authentication failures)", "sr3.wrong.digests", 6),
        ("SNMPv3 decryption errors", "sr3.decryption.errors", 7),
        ("SNMPv3 requests outside the time window", "sr3.time.window", 8),
        ("SNMPv3 requests dropped by the rate limit", "sr3.rate.limited", 11),
        ("SNMPv3 SET requests refused", "sr3.set.refused", 13),
    )
    for name, key, index in counters:
        snmp(f"{name} per second", key, f"{obj}.10.{index}.0", FLOAT, units="rps",
             preprocessing=[step(CHANGE_SEC)])

    # Informs the CAP sent, and the ones it had to drop because a target was down (srOutputs).
    snmp("SmartReader informs failed", "sr3.informs.failed", f"{obj}.3.14.0", UINT)
    snmp("SmartReader informs dropped", "sr3.informs.dropped", f"{obj}.3.15.0", UINT)

    # RFID statistics: what the CAP's status collector reads with RShell `show rfid stat`.
    rfid_status = call("valuemap.create", {"hostid": tid, "name": "SmartReader RFID status", "mappings": [
        {"value": "1", "newvalue": "enabled"}, {"value": "2", "newvalue": "disabled"},
        {"value": "3", "newvalue": "other"}]})["valuemapids"][0]
    yes_no = call("valuemap.create", {"hostid": tid, "name": "SmartReader yes/no", "mappings": [
        {"value": "1", "newvalue": "yes"}, {"value": "2", "newvalue": "no"}]})["valuemapids"][0]
    collection = call("valuemap.create", {"hostid": tid, "name": "SmartReader collection status", "mappings": [
        {"value": "0", "newvalue": "not collected yet"}, {"value": "1", "newvalue": "ok"},
        {"value": "2", "newvalue": "timeout"}, {"value": "3", "newvalue": "paused: the reader rejects the CAP's credentials"},
        {"value": "4", "newvalue": "error"}]})["valuemapids"][0]
    component_state = call("valuemap.create", {"hostid": tid, "name": "SmartReader component state", "mappings": [
        {"value": "1", "newvalue": "OK"}, {"value": "2", "newvalue": "Warning"}, {"value": "3", "newvalue": "Error"},
        {"value": "4", "newvalue": "Off"}, {"value": "5", "newvalue": "Amber"}]})["valuemapids"][0]
    snmp("Reader administrative status", "sr3.reader.admin", f"{obj}.2.20.0", UINT, valuemapid=rfid_status)
    snmp("Reader operational status", "sr3.reader.oper", f"{obj}.2.21.0", UINT, valuemapid=rfid_status)
    snmp("RFID statistics since last reset", "sr3.rfid.reset", f"{obj}.2.22.0", FLOAT, units="uptime")
    # srCollectorGroupTable row 1 is the RfidStatistics group.
    snmp("RFID statistics age", "sr3.rfid.age", f"{obj}.9.2.1.4.1", FLOAT, units="s")
    snmp("RFID statistics collection", "sr3.rfid.collection", f"{obj}.9.2.1.3.1", UINT, valuemapid=collection)

    # Antenna table (srAntennaTable): one row per port, `show rfid stat` figures plus SmartReader's own settings.
    walk_key = "sr3.antennas.walk"
    antennas = f"{obj}.5.1.1"
    snmp("Antenna table (walk)", walk_key, f"walk[{antennas}]", TEXT, history="1h")
    rule = call("discoveryrule.create", {
        "hostid": tid, "name": "SmartReader antenna discovery", "key_": "sr3.antenna.discovery", "type": DEPENDENT,
        "master_itemid": b.items[walk_key], "delay": "0", "lifetime": "1d",
        "preprocessing": [step(WALK_JSON, f"{{#ZONE}}\n{antennas}.21\n0\n{{#CONFIGURED}}\n{antennas}.20\n0")],
    })["itemids"][0]

    def antenna(name, field, column, vtype, units="", extra=(), **kw):
        params = {"ruleid": rule, "hostid": tid, "name": f"Antenna {{#SNMPINDEX}} ({{#ZONE}}): {name}",
                  "key_": f"sr3.antenna.{field}[{{#SNMPINDEX}}]", "type": DEPENDENT, "delay": "0",
                  "value_type": vtype, "master_itemid": b.items[walk_key], "units": units,
                  "preprocessing": [step(WALK_VALUE, f"{antennas}.{column}.{{#SNMPINDEX}}\n0"), *extra],
                  "tags": tags(component="smartreader-antenna", antenna="{#SNMPINDEX}")}
        params.update(kw)
        return call("itemprototype.create", params)["itemids"][0]

    antenna("administrative status", "admin", 2, UINT, valuemapid=rfid_status)
    antenna("operational status", "oper", 3, UINT, valuemapid=rfid_status)
    antenna("last power level", "power", 4, FLOAT, "dBm", [step(MULT, "0.01")])
    antenna("last noise level", "noise", 5, FLOAT)
    antenna("time energized", "energized", 6, FLOAT, "uptime", [step(MULT, "0.001")])
    antenna("unique tags inventoried", "unique", 7, UINT)
    antenna("tags inventoried", "inventory", 8, UINT)
    antenna("tags inventoried per second", "inventory.rate", 8, FLOAT, "tags/s", [step(CHANGE_SEC)])
    for name, field, column in (("failed inventories", "inventory.failed", 9), ("tag reads", "reads", 10),
                                ("failed tag reads", "reads.failed", 11), ("tag writes", "writes", 12),
                                ("failed tag writes", "writes.failed", 13), ("tag locks", "locks", 14),
                                ("failed tag locks", "locks.failed", 15), ("tag kills", "kills", 16),
                                ("failed tag kills", "kills.failed", 17), ("tag erases", "erases", 18),
                                ("failed tag erases", "erases.failed", 19)):
        antenna(name, field, column, UINT)
    antenna("enabled in SmartReader", "enabled", 20, UINT, valuemapid=yes_no)
    antenna("zone", "zone", 21, CHAR)
    antenna("configured transmit power", "txpower", 22, FLOAT, "dBm", [step(MULT, "0.01")])
    antenna("configured receive sensitivity", "rxsensitivity", 23, FLOAT, "dBm")

    # Component table (srComponentTable): one row per item of the CAP's status overview.
    components_key = "sr3.components.walk"
    components = f"{obj}.4.1.1"
    snmp("Component table (walk)", components_key, f"walk[{components}]", TEXT, history="1h")
    comp_rule = call("discoveryrule.create", {
        "hostid": tid, "name": "SmartReader component discovery", "key_": "sr3.component.discovery", "type": DEPENDENT,
        "master_itemid": b.items[components_key], "delay": "0", "lifetime": "1d",
        "preprocessing": [step(WALK_JSON, f"{{#KEY}}\n{components}.2\n0\n{{#LABEL}}\n{components}.3\n0")],
    })["itemids"][0]

    def component(name, field, column, vtype, **kw):
        params = {"ruleid": comp_rule, "hostid": tid, "name": f"CAP component {{#LABEL}}: {name}",
                  "key_": f"sr3.component.{field}[{{#SNMPINDEX}}]", "type": DEPENDENT, "delay": "0",
                  "value_type": vtype, "master_itemid": b.items[components_key],
                  "preprocessing": [step(WALK_VALUE, f"{components}.{column}.{{#SNMPINDEX}}\n0")],
                  "tags": tags(component="smartreader-component", key="{#KEY}")}
        params.update(kw)
        return call("itemprototype.create", params)["itemids"][0]

    component("state", "state", 4, UINT, valuemapid=component_state)
    component("detail", "detail", 5, CHAR, history="7d", trends="0")

    # Informs, one item each: they are what makes the CAP's own events visible without polling.
    b.item("Trap: SmartReader SNMPv3 notification (any)", SR3_TRAP_KEY, TRAP, LOG, tags=tags(component="traps"))
    for number, name, severity, text in SR3_NOTIFICATIONS:
        b.item(f"Trap: {name}", sr3_trap_key(number, name), TRAP, LOG, tags=tags(component="traps", notification=name))

    down = trigger("SmartReader SNMPv3 agent not answering", f"nodata(/{T}/sr3.agent.uptime,5m)=1", AVERAGE,
                   comments="The \"CAP is down\" alarm: when SmartReader stops, so does its agent. Keep the ICMP check of the "
                            "reader template as well.")
    dep = [{"triggerid": down}]
    trigger("CAP lost the MQTT broker (SNMPv3)", f"max(/{T}/sr3.mqtt.connected,5m)=0", HIGH, dependencies=dep)
    trigger("CAP MQTT messages backing up (SNMPv3)", f"min(/{T}/sr3.mqtt.pending,10m)>{{$SR.PENDING.MAX}}",
            AVERAGE, dependencies=dep)
    trigger("CAP file system above {$SR.DISK.MAX}% (SNMPv3)", f"last(/{T}/sr3.disk.pused)>{{$SR.DISK.MAX}}",
            WARNING, dependencies=dep)
    trigger("Reader CPU running hot (SNMPv3)",
            f"last(/{T}/sr3.cpu.temp)>last(/{T}/sr3.cpu.temp.max)-{{$SR.TEMP.MARGIN}}", WARNING, dependencies=dep)
    trigger("Reader rebooted (OS uptime via SNMPv3)", f"last(/{T}/sr3.os.uptime)<600", WARNING, dependencies=dep)
    trigger("CAP restarted (SNMPv3)", f"last(/{T}/sr3.app.uptime)<600", WARNING, dependencies=dep)
    trigger("SmartReader SNMP engine restarted", f"change(/{T}/sr3.engine.boots)>0", INFO, manual_close=1,
            dependencies=dep)
    trigger("SNMPv3 requests with a wrong key against SmartReader",
            f"max(/{T}/sr3.wrong.digests,5m)>0 or max(/{T}/sr3.decryption.errors,5m)>0", WARNING,
            dependencies=dep, comments="Someone is trying the agent with a wrong key; check who can reach UDP 1161.")
    trigger("SmartReader informs are being dropped", f"change(/{T}/sr3.informs.dropped)>0", WARNING,
            manual_close=1, comments="An inform target was down long enough for the CAP's queue to fill.")
    trigger("Reader RFID not operational (SNMPv3)", f"last(/{T}/sr3.reader.oper)<>1", HIGH, dependencies=dep)
    trigger("SmartReader RFID statistics older than 5 minutes", f"last(/{T}/sr3.rfid.age)>300", WARNING,
            dependencies=dep, comments="The CAP collects them every minute; see the collection status item for why.")
    trigger("SmartReader cannot collect RFID statistics", f'count(/{T}/sr3.rfid.collection,10m,"eq","1")=0',
            WARNING, dependencies=dep)
    call("triggerprototype.create", {
        "description": "Antenna {#SNMPINDEX} ({#ZONE}) is enabled in SmartReader but not operational",
        "expression": f"last(/{T}/sr3.antenna.oper[{{#SNMPINDEX}}])<>1"
                      f" and last(/{T}/sr3.antenna.enabled[{{#SNMPINDEX}}])=1",
        "priority": AVERAGE, "opdata": "{ITEM.LASTVALUE1}"})
    call("triggerprototype.create", {
        "description": "CAP component {#LABEL} is in error",
        "expression": f"last(/{T}/sr3.component.state[{{#SNMPINDEX}}])=3",
        "priority": AVERAGE, "opdata": "{ITEM.LASTVALUE1}", "dependencies": []})
    trigger("SmartReader SNMPv3 notification received", f"nodata(/{T}/{SR3_TRAP_KEY},15m)=0", INFO,
            manual_close=1, comments="Raised for 15 minutes after an inform arrives; close it manually once handled.")
    for number, name, severity, text in SR3_NOTIFICATIONS:
        trigger(text, f"nodata(/{T}/{sr3_trap_key(number, name)},15m)=0", severity, manual_close=1,
                comments=f"Raised for 15 minutes after the inform {name} arrives; close it manually once handled.")
    return tid


def sr3_interface(ip, main):
    """An SNMPv3 interface on SmartReader's agent port; the credentials come from secret host macros."""
    return {"type": 2, "main": main, "useip": 1, "ip": ip, "dns": "", "port": SR3_PORT,
            "details": {"version": 3, "bulk": 1, "max_repetitions": 10, "contextname": "",
                        "securityname": "{$SR.SNMPV3.USER}", "securitylevel": 2,
                        "authprotocol": AUTH_PROTOCOLS[ENV.get("SR_SNMPV3_AUTH_PROTOCOL", "SHA256")],
                        "authpassphrase": "{$SR.SNMPV3.AUTHPASS}",
                        "privprotocol": PRIV_PROTOCOLS[ENV.get("SR_SNMPV3_PRIV_PROTOCOL", "AES128")],
                        "privpassphrase": "{$SR.SNMPV3.PRIVPASS}"}}


def sr3_macros():
    return [
        {"macro": "{$SR.SNMPV3.USER}", "value": ENV.get("SR_SNMPV3_USER", "")},
        {"macro": "{$SR.SNMPV3.AUTHPASS}", "value": ENV.get("SR_SNMPV3_AUTH_PASSPHRASE", ""), "type": 1},
        {"macro": "{$SR.SNMPV3.PRIVPASS}", "value": ENV.get("SR_SNMPV3_PRIV_PASSPHRASE", ""), "type": 1},
    ]


def point_sr3_items(hostid, ip):
    """Move the SNMPv3 items to SmartReader's interface (a host with two SNMP interfaces links every SNMP item
    to the main one) and enable them there."""
    interfaces = call("hostinterface.get", {"hostids": hostid, "output": ["interfaceid", "ip", "port"]})
    sr3_if = next(i["interfaceid"] for i in interfaces if i["ip"] == ip and i["port"] == SR3_PORT)
    items = call("item.get", {"hostids": hostid, "filter": {"type": SNMP}, "search": {"key_": "sr3."},
                              "startSearch": True, "output": ["itemid"]})
    for it in items:
        call("item.update", {"itemid": it["itemid"], "interfaceid": sr3_if, "status": 0})
    # An item enabled now is first polled somewhere inside its interval (an hour for the identity items).
    call("task.create", [{"type": 6, "request": {"itemid": it["itemid"]}} for it in items])
    return len(items)


def build_sim_host(hostgroup, templateid):
    hostid = call("host.create", {
        "host": SIM_HOST, "name": "SmartReader SNMPv3 simulator",
        "groups": [{"groupid": hostgroup}], "templates": [{"templateid": templateid}],
        "interfaces": [sr3_interface(SIM_IP, 1)], "macros": sr3_macros(),
        "tags": tags(site="lab", role="simulator"),
    })["hostids"][0]
    point_sr3_items(hostid, SIM_IP)
    return hostid


# ---------------------------------------------------------------- host

def build_host(hostgroup, templateids):
    separate_trap_if = bool(TRAP_SOURCE_IP) and TRAP_SOURCE_IP != ENV["READER_HOST"]
    hostid = call("host.create", {
        "host": HOST, "name": "R700 bench",
        "groups": [{"groupid": hostgroup}],
        "templates": [{"templateid": t} for t in templateids],
        "inventory_mode": 1,
        "interfaces": [
            {"type": 2, "main": 1, "useip": 1, "ip": ENV["READER_HOST"], "dns": "", "port": "161",
             "details": {"version": 2, "bulk": 1, "community": "{$SNMP_COMMUNITY}"}},
        ] + ([{"type": 2, "main": 0, "useip": 1, "ip": TRAP_SOURCE_IP, "dns": "", "port": "161",
               "details": {"version": 2, "bulk": 1, "community": "{$SNMP_COMMUNITY}"}}]
             if separate_trap_if else [])
        + ([sr3_interface(ENV["READER_HOST"], 0)] if SR3_ON_READER else []),
        "macros": [
            {"macro": "{$SNMP_COMMUNITY}", "value": ENV["SNMP_COMMUNITY"]},
            {"macro": "{$CAP.USER}", "value": ENV["CAP_USER"]},
            {"macro": "{$CAP.PASSWORD}", "value": ENV["CAP_PASSWORD"], "type": 1},
            {"macro": "{$READER.USER}", "value": ENV["READER_USER"]},
            {"macro": "{$READER.PASSWORD}", "value": ENV["READER_PASSWORD"], "type": 1},
            # Ports with an antenna attached; empty ports in the preset would raise "antenna down" permanently.
            {"macro": "{$R700.ANTENNAS}", "value": ENV.get("R700_ANTENNAS", ".*")},
        ] + (sr3_macros() if SR3_ON_READER else []),
        "tags": tags(site="lab", role="r700"),
    })["hostids"][0]

    trap_items = call("item.get", {"hostids": hostid, "filter": {"type": TRAP}, "output": ["itemid"]})
    if separate_trap_if:
        # Point the trap items at the trap-only interface (the address the traps arrive from).
        interfaces = call("hostinterface.get", {"hostids": hostid, "output": ["interfaceid", "ip"]})
        trap_if = next(i["interfaceid"] for i in interfaces if i["ip"] == TRAP_SOURCE_IP)
        for it in trap_items:
            call("item.update", {"itemid": it["itemid"], "interfaceid": trap_if})
    if SR3_ON_READER:
        point_sr3_items(hostid, ENV["READER_HOST"])
    return hostid, len(trap_items)


def main():
    global TOKEN
    print("Zabbix API", wait_for_api())
    TOKEN = call("user.login", {"username": ENV["ZBX_WEB_USER"], "password": ENV["ZBX_WEB_PASSWORD"]})
    cleanup()
    tgroup = group("templategroup", "Templates/SmartReader")
    hgroup = group("hostgroup", "SmartReader lab")
    t1 = build_snmp_template(tgroup)
    t2 = build_cap_template(tgroup)
    t3 = build_rest_template(tgroup)
    t4 = build_sr3_template(tgroup) if (SR3_ON_READER or SR3_SIMULATOR) else None
    hostid, traps = build_host(hgroup, [t1, t2, t3] + ([t4] if SR3_ON_READER else []))
    print(f"templates {t1} {t2} {t3}{' ' + t4 if t4 else ''}; host {HOST} ({hostid}); "
          f"{traps} trap items on the trap interface")
    if SR3_ON_READER:
        print(f"  SmartReader SNMPv3 (experimental) on {HOST}: {ENV['READER_HOST']}:{SR3_PORT}")
    if SR3_SIMULATOR:
        print(f"  simulator host {SIM_HOST} ({build_sim_host(hgroup, t4)}): {SIM_IP}:{SR3_PORT}")
    # dashboard.py imports this file as the module "provision", a separate copy from __main__; share the token.
    import dashboard
    dashboard.provision.TOKEN = TOKEN
    dashboard.build(hostid)


if __name__ == "__main__":
    main()
