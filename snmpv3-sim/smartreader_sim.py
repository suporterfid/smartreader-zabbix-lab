#!/usr/bin/env python3
"""Net-SNMP pass_persist handler that serves the objects of SmartReader's experimental SNMPv3 agent.

It answers under the same provisional root and with the same layout as the agent in the SmartReader
SNMPv3 test build, so the lab's SNMPv3 template can be tried
without that build. Values are synthetic: they move like the real ones, but come from nowhere.

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


def health():
    """The .2 health scalars: same indexes and scaling as the agent (x100, x10 where it scales)."""
    t = time.time() - STARTED
    cpu = 30 + 10 * math.sin(t / 60) + random.uniform(-2, 2)
    temp = 52 + 3 * math.sin(t / 300)
    return {
        1: ("gauge", round(cpu * 100)),                      # CPU usage, % x100
        2: ("gauge", 180 + int(5 * math.sin(t / 120))),     # process memory, MB
        3: ("gauge", 2835),                                   # disk usage, % x100
        4: ("gauge", int(time.time() - BOOTED)),            # reader OS uptime, s
        5: ("gauge", int(t)),                                 # CAP uptime, s
        6: ("gauge", round(temp * 10)),                      # CPU temperature, C x10
        7: ("gauge", 1050),                                   # max allowed temperature, C x10
        8: ("gauge", round(55.4 * 10)),                      # peak temperature, C x10
        9: ("gauge", 1),                                      # MQTT connected
        10: ("gauge", random.randint(0, 3)),                 # MQTT messages pending
        20: ("gauge", 201_000_000 + random.randint(0, 9_000_000)),  # process RSS, bytes
        21: ("counter64", int(t * 280)),                     # process CPU time, ms (about 28 % of a core)
        22: ("gauge", 70_000_000 + random.randint(0, 30_000_000)),  # GC heap, bytes
        23: ("gauge", 27),                                    # threads
    }


COUNTERS = {i: 0 for i in range(1, 19)}  # .3 agent counters; requests and responses grow below


def table():
    objects = {}
    t = time.time() - STARTED
    COUNTERS[1] = int(t / 2)       # requests received
    COUNTERS[2] = int(t / 2)       # responses sent
    COUNTERS[3] = int(t / 600) + 1  # discoveries
    for index, (kind, value) in health().items():
        objects[f"{ROOT}.2.{index}.0"] = (kind, value)
    for index, value in COUNTERS.items():
        objects[f"{ROOT}.3.{index}.0"] = ("counter", value)
    for row in range(1, 26):
        objects[f"{ROOT}.4.1.1.{row}"] = ("integer", row)
        objects[f"{ROOT}.4.1.2.{row}"] = ("string", f"row-{row}")
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
