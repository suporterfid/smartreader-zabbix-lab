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
HOST = "r700-bench"
# Address Zabbix sees as the source of the reader's traps. Docker Desktop rewrites it to the gateway of the
# lab network (see docker-compose.yml); set TRAP_SOURCE_IP to the reader's own IP, or leave it empty, where
# the source address is kept (Docker Engine on Linux, or a native proxy).
TRAP_SOURCE_IP = ENV.get("TRAP_SOURCE_IP", "172.31.67.1")

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
    hosts = call("host.get", {"filter": {"host": [HOST]}, "output": ["hostid"]})
    if hosts:
        call("host.delete", [h["hostid"] for h in hosts])
    templates = call("template.get", {"filter": {"host": [T_SNMP, T_CAP, T_REST]}, "output": ["templateid"]})
    if templates:
        call("template.delete", [t["templateid"] for t in templates])


def group(kind, name):
    found = call(f"{kind}.get", {"filter": {"name": [name]}, "output": ["groupid"]})
    return found[0]["groupid"] if found else call(f"{kind}.create", {"name": name})["groupids"][0]


def template(name, groupid, description, macros=()):
    return call("template.create", {
        "host": name, "groups": [{"groupid": groupid}], "description": description,
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
        ("CAP CPU share since boot", "cap.cpu.avg", "metricsmonitoringservice_system_cpu_usage____", FLOAT, "%",
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
             if separate_trap_if else []),
        "macros": [
            {"macro": "{$SNMP_COMMUNITY}", "value": ENV["SNMP_COMMUNITY"]},
            {"macro": "{$CAP.USER}", "value": ENV["CAP_USER"]},
            {"macro": "{$CAP.PASSWORD}", "value": ENV["CAP_PASSWORD"], "type": 1},
            {"macro": "{$READER.USER}", "value": ENV["READER_USER"]},
            {"macro": "{$READER.PASSWORD}", "value": ENV["READER_PASSWORD"], "type": 1},
            # Ports with an antenna attached; empty ports in the preset would raise "antenna down" permanently.
            {"macro": "{$R700.ANTENNAS}", "value": ENV.get("R700_ANTENNAS", ".*")},
        ],
        "tags": tags(site="lab", role="r700"),
    })["hostids"][0]

    trap_items = call("item.get", {"hostids": hostid, "filter": {"type": TRAP}, "output": ["itemid"]})
    if separate_trap_if:
        # Point the trap items at the trap-only interface (the address the traps arrive from).
        interfaces = call("hostinterface.get", {"hostids": hostid, "output": ["interfaceid", "ip"]})
        trap_if = next(i["interfaceid"] for i in interfaces if i["ip"] == TRAP_SOURCE_IP)
        for it in trap_items:
            call("item.update", {"itemid": it["itemid"], "interfaceid": trap_if})
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
    hostid, traps = build_host(hgroup, [t1, t2, t3])
    print(f"templates {t1} {t2} {t3}; host {HOST} ({hostid}); {traps} trap items on the trap interface")
    # dashboard.py imports this file as the module "provision", a separate copy from __main__; share the token.
    import dashboard
    dashboard.provision.TOKEN = TOKEN
    dashboard.build(hostid)


if __name__ == "__main__":
    main()
