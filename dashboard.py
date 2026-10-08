"""Create (or re-create) the "R700 bench lab" dashboard for the bench host.

Run by provision.py at the end; can also be run on its own:
  python dashboard.py
"""
import itertools
import string
import time

import provision
from lablib import ENV
from provision import HOST, call

NAME = "R700 bench lab"
RED, ORANGE, YELLOW, GREEN, GREY = "E45959", "FFA059", "FFC859", "59DB8F", "97AAB3"
UP_DOWN = (("0", RED), ("1", GREEN))
EPCG = (("1", YELLOW), ("2", YELLOW), ("3", GREEN), ("4", RED))  # unknown, other, up, down
CAP_LEVEL = (("0", GREY), ("1", GREEN), ("2", YELLOW), ("3", RED))  # off, OK, warning, error
NEEDED = ("r700.antenna.oper[1]", "cap.level[reader-connection]", "cap.level[mqtt]")

_refs = ("".join(p) for p in itertools.product(string.ascii_uppercase, repeat=5))


def num(name, value):
    return {"type": 0, "name": name, "value": value}


def text(name, value):
    return {"type": 1, "name": name, "value": value}


def item_field(name, itemid):
    return {"type": 4, "name": name, "value": itemid}


def widget(kind, name, x, y, w, h, fields, view_mode=0):
    return {"type": kind, "name": name, "x": x, "y": y, "width": w, "height": h, "view_mode": view_mode,
            "fields": fields + [text("reference", next(_refs))]}


def thresholds(pairs):
    out = []
    for i, (value, color) in enumerate(pairs):
        out += [text(f"thresholds.{i}.threshold", value), text(f"thresholds.{i}.color", color)]
    return out


def tile(items, label, key, x, y, levels=(), w=12, h=2):
    return widget("item", label, x, y, w, h, [
        item_field("itemid.0", items[key]), num("show.0", 2), num("value_size", 34), num("decimal_places", 0),
        *thresholds(levels)])


def gauge(items, label, key, x, y, lo, hi, levels, w=18, h=4):
    return widget("gauge", label, x, y, w, h, [
        item_field("itemid.0", items[key]), text("min", lo), text("max", hi), text("description", label),
        num("decimal_places", 1), *thresholds(levels)], view_mode=1)


def graph(items, label, series, x, y, w=24, h=5):
    fields = [num("ds.0.dataset_type", 0), num("ds.0.width", 2), num("ds.0.fill", 1),
              text("time_period._reference", "DASHBOARD._timeperiod")]
    colors = ("0080FF", "FF8000", "00A86B", "C0399B")
    for i, key in enumerate(series):
        fields += [item_field(f"ds.0.itemids.{i}", items[key]), text(f"ds.0.color.{i}", colors[i])]
    return widget("svggraph", label, x, y, w, h, fields)


def wait_for_items(hostid, timeout=240):
    deadline = time.time() + timeout
    while True:
        found = {i["key_"]: i["itemid"] for i in call("item.get", {"hostids": hostid, "output": ["itemid", "key_"]})}
        missing = [k for k in NEEDED if k not in found]
        if not missing:
            return found
        if time.time() > deadline:
            raise SystemExit(f"discovered items still missing: {missing}")
        print(f"waiting for discovery: {', '.join(missing)}", flush=True)
        time.sleep(15)


def build(hostid):
    items = wait_for_items(hostid)
    old = call("dashboard.get", {"filter": {"name": [NAME]}, "output": ["dashboardid"]})
    if old:
        call("dashboard.delete", [d["dashboardid"] for d in old])

    widgets = [
        # Row 1: is everything up?
        tile(items, "Reader reachable", "icmpping", 0, 0, UP_DOWN),
        tile(items, "RFID subsystem", "r700.rfid.oper", 12, 0, EPCG),
        tile(items, "Antenna 1", "r700.antenna.oper[1]", 24, 0, EPCG),
        tile(items, "Inventory (CAP)", "cap.inventory.status", 36, 0),
        tile(items, "CAP to MQTT broker", "cap.mqtt.connected", 48, 0, UP_DOWN),
        tile(items, "CAP to reader REST", "cap.readerrest.healthy", 60, 0, UP_DOWN),
    ]
    # Row 2: the CAP's own status dashboard, one tile per component.
    for i, (key, label) in enumerate((("reader-connection", "CAP: reader connection"), ("mqtt", "CAP: MQTT"),
                                      ("mqtt-cert", "CAP: MQTT certificate"), ("license", "CAP: license"),
                                      ("http-webhook", "CAP: HTTP webhook"), ("tag-quieting", "CAP: tag quieting"))):
        level_key = f"cap.level[{key}]"
        if level_key in items:
            widgets.append(tile(items, label, level_key, 12 * i, 2, CAP_LEVEL))
    widgets += [
        # Row 3: gauges.
        gauge(items, "CPU temperature (°C)", "cap.cpu.temp", 0, 4, "0", "80", (("65", YELLOW), ("75", RED))),
        gauge(items, "Reader CPU (%)", "r700rest.cpu", 18, 4, "0", "100", (("70", YELLOW), ("90", RED))),
        gauge(items, "Reader memory (%)", "r700rest.memory", 36, 4, "0", "100", (("70", YELLOW), ("90", RED))),
        gauge(items, "CAP file system (%)", "cap.disk.pused", 54, 4, "0", "100", (("75", YELLOW), ("85", RED))),
        # Row 4: problems and uptimes.
        widget("problems", "Current problems", 0, 8, 48, 6, [
            {"type": 3, "name": "hostids.0", "value": hostid}, num("show", 3), num("show_lines", 10),
            num("show_opdata", 2), num("show_timeline", 1)]),
        tile(items, "Reader uptime (REST)", "r700rest.uptime", 48, 8, w=24),
        tile(items, "CAP uptime", "cap.app.uptime", 48, 10, w=24),
        tile(items, "SNMP agent uptime", "r700.snmp.uptime", 48, 12, w=24),
        # Rows 5 and 6: trends.
        graph(items, "Reader CPU and memory (%)", ("r700rest.cpu", "r700rest.memory"), 0, 14),
        graph(items, "Temperatures (°C)", ("cap.cpu.temp", "r700rest.temp"), 24, 14),
        graph(items, "eth0 throughput", ("cap.net.rx", "cap.net.tx"), 48, 14),
        graph(items, "CAP process memory", ("cap.memory",), 0, 19),
        graph(items, "ICMP response time", ("icmppingsec",), 24, 19),
        graph(items, "MQTT messages pending", ("cap.mqtt.pending",), 48, 19),
    ]
    # Row 7: traps as they arrive.
    traps = call("item.get", {"hostids": hostid, "filter": {"type": 17}, "output": ["itemid", "name"],
                              "sortfield": "name"})
    columns = []
    for i, trap in enumerate(traps):
        columns += [text(f"columns.{i}.name", trap["name"].replace("Trap: ", "")),
                    item_field(f"columns.{i}.itemid", trap["itemid"]), num(f"columns.{i}.max_length", 300)]
    widgets.append(widget("itemhistory", "SNMP traps received", 0, 24, 72, 5,
                          columns + [num("show_lines", 10), num("show_timestamp", 1), num("show_column_header", 1)]))

    dashboardid = call("dashboard.create", {
        "name": NAME, "display_period": 30, "auto_start": 0,
        "pages": [{"name": "Bench R700", "widgets": widgets}],
    })["dashboardids"][0]
    print(f'dashboard "{NAME}" ({dashboardid}): http://localhost:8080/zabbix.php?action=dashboard.view'
          f"&dashboardid={dashboardid}")
    return dashboardid


if __name__ == "__main__":
    provision.TOKEN = call("user.login", {"username": ENV["ZBX_WEB_USER"], "password": ENV["ZBX_WEB_PASSWORD"]})
    host = call("host.get", {"filter": {"host": [HOST]}, "output": ["hostid"]})[0]["hostid"]
    build(host)
