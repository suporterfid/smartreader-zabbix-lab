#!/usr/bin/env python3
"""Net-SNMP pass_persist handler that serves the objects of SmartReader's SNMPv3 agent.

It answers under the same provisional root and with the layout of SMARTREADER-MIB (the objects under
`smartReaderObjects`, .2), so the lab's SNMPv3 template can be tried without a reader. Values are synthetic: they move like the real ones, but come from nowhere.

Protocol (snmpd.conf `pass_persist`): snmpd writes "PING", "get\\n<oid>" or "getnext\\n<oid>"; the
handler answers "PONG", "<oid>\\n<type>\\n<value>" or "NONE".
"""
import math
import os
import random
import sys
import time

ROOT = os.environ.get("SR_SNMP_ROOT", ".1.3.6.1.4.1.8072.9999.9999.7")
STARTED = time.time()
BOOTED = STARTED - random.randint(3600, 86400)  # pretend the reader has been up for a while


def oid_key(oid):
    return tuple(int(part) for part in oid.strip(".").split("."))


def system(t):
    """srSystem and srOutputs scalars (SMARTREADER-MIB 1.x and 3.x): same units as the agent."""
    cpu = 30 + 10 * math.sin(t / 60) + random.uniform(-2, 2)
    temp = 52 + 3 * math.sin(t / 300)
    return {
        "1.1": ("string", "4.0.1.999 (simulator)"),
        "1.2": ("gauge", int(t)),                                       # CAP uptime, s
        "1.3": ("gauge", int(time.time() - BOOTED)),                    # reader OS uptime, s
        "1.4": ("gauge", round(cpu * 100)),                             # CPU usage, % x100
        "1.5": ("gauge", 180 + int(5 * math.sin(t / 120))),             # process memory, MB
        "1.6": ("gauge", 2835),                                         # disk usage, % x100
        "1.7": ("integer", round(temp * 10)),                           # CPU temperature, C x10
        "1.8": ("integer", 1050),                                       # max allowed temperature, C x10
        "1.9": ("integer", round(55.4 * 10)),                           # peak temperature, C x10
        "2.6": ("string", "10.4.0"),                                    # firmware
        "2.7": ("string", "R700"),
        "2.8": ("string", "370-00-0000-SIM"),
        "2.9": ("string", "00:16:25:00:00:01"),
        "3.1": ("integer", 1),                                          # MQTT connected (TruthValue: 1 true)
        "3.2": ("gauge", random.randint(0, 3)),                         # MQTT messages pending
        "3.14": ("counter64", 0),                                       # informs failed
        "3.15": ("counter64", 0),                                       # informs dropped
    }


def agent_counters(t):
    """srAgent (10.x): requests and responses grow, the rest stay at 0 except one discovery every 10 minutes."""
    values = {i: 0 for i in range(1, 17)}
    values[1] = int(t / 2)
    values[2] = int(t / 2)
    values[3] = int(t / 600) + 1
    return {f"10.{i}": ("counter64", v) for i, v in values.items()}


COMPONENTS = (("reader-connection", "Reader Connection", 1, "Connected"), ("mqtt", "MQTT", 1, "Connected"),
              ("http-webhook", "HTTP Webhook", 4, "Disabled"), ("mqtt-cert", "MQTT Certificate", 1, "Certificate valid"),
              ("license", "License", 1, "Valid"))


def scalars(t):
    """Scalars are read at the instance .0."""
    return {f"{suffix}.0": cell for suffix, cell in {**system(t), **agent_counters(t)}.items()}


def components():
    objects = {}
    for row, (key, label, state, detail) in enumerate(COMPONENTS, start=1):
        objects[f"4.1.1.2.{row}"] = ("string", key)
        objects[f"4.1.1.3.{row}"] = ("string", label)
        objects[f"4.1.1.4.{row}"] = ("integer", state)
        objects[f"4.1.1.5.{row}"] = ("string", detail)
    return objects


def table():
    objects = {}
    t = time.time() - STARTED
    for suffix, cell in {**scalars(t), **components(), **rfid(t)}.items():
        objects[f"{ROOT}.2.{suffix}"] = cell
    return objects


# Antenna table (5.1.1.<column>.<port>), like the agent's. Port 1 has an antenna and reads tags; ports 2-4 are
# in the preset without one, so the reader reports them disabled. Statuses: 1 enabled, 2 disabled, 3 other.
ANTENNA_COUNTERS = ("LastPowerLevel", "LastNoiseLevel", "EnergizedTime", "UniqueInventoryCount",
                    "TotalInventoryCount", "FailedInventoryCount", "ReadCount", "FailedReadCount", "WriteCount",
                    "FailedWriteCount", "LockCount", "FailedLockCount", "KillCount", "FailedKillCount",
                    "EraseCount", "FailedEraseCount")


def rfid(t):
    objects = {}
    for port in range(1, 5):
        live = port == 1
        counters = {name: 0 for name in ANTENNA_COUNTERS}
        if live:
            counters.update(LastPowerLevel=1550, EnergizedTime=int(t * 1000 * 0.98), UniqueInventoryCount=4,
                            TotalInventoryCount=int(t * 245))
        cells = {2: ("integer", 1), 3: ("integer", 1 if live else 2)}
        for column, name in enumerate(ANTENNA_COUNTERS, start=4):
            kind = "integer" if name in ("LastPowerLevel", "LastNoiseLevel") else (
                "gauge" if name == "UniqueInventoryCount" else "counter64")
            cells[column] = (kind, counters[name])
        cells.update({20: ("integer", 1 if live else 2), 21: ("string", "Dock door 1" if live else "Unused"),
                      22: ("integer", 1550), 23: ("integer", -92)})
        for column, cell in cells.items():
            objects[f"5.1.1.{column}.{port}"] = cell
    objects["2.20.0"] = ("integer", 1)                  # reader administrative status
    objects["2.21.0"] = ("integer", 1)                  # reader operational status
    objects["2.22.0"] = ("gauge", int(t))               # seconds since the statistics were reset
    # srCollectorGroupTable row 1 is the RfidStatistics group.
    objects["9.2.1.3.1"] = ("integer", 1)             # last collection: ok
    objects["9.2.1.4.1"] = ("gauge", int(t) % 60)     # age of the RFID statistics, s (collected every 60 s)
    return objects


def answer(oid, kind, value):
    sys.stdout.write(f"{oid}\n{kind}\n{value}\n")


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        command = line.strip()
        if command == "PING":
            sys.stdout.write("PONG\n")
        elif command in ("get", "getnext"):
            requested = sys.stdin.readline().strip()
            objects = table()
            if command == "get":
                found = objects.get(requested)
                if found:
                    answer(requested, *found)
                else:
                    sys.stdout.write("NONE\n")
            else:
                target = oid_key(requested)
                following = sorted((oid_key(o), o) for o in objects if oid_key(o) > target)
                if following:
                    oid = following[0][1]
                    answer(oid, *objects[oid])
                else:
                    sys.stdout.write("NONE\n")
        elif command == "set":
            sys.stdin.readline()
            sys.stdin.readline()
            sys.stdout.write("not-writable\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
