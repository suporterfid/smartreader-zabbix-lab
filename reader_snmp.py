"""Turn SNMP on (or back to factory defaults) on the bench reader.

  python reader_snmp.py enable   # v2c read-only + traps to this PC, SNMP writes off
  python reader_snmp.py revert   # config snmp reset: factory defaults (SNMP and traps disabled)
  python reader_snmp.py show
"""
import sys

from lablib import ENV, rshell

ENABLE = [
    f"config snmp access rocommunity {ENV['SNMP_COMMUNITY']}",
    "config snmp write disable all",
    "config snmp version 2c enable",
    f"config snmp access trapcommunity {ENV['SNMP_TRAP_COMMUNITY']}",
    f"config snmp trap sink {ENV['LAB_HOST_IP']}",
    "config snmp trap port 162",
    "config snmp trap enable unexpectedrestart",
    "config snmp trapservice enable",
    "config snmp service enable",
]
REVERT = ["config snmp reset"]


def run(commands):
    for cmd in commands:
        out = rshell(cmd).strip().splitlines()
        status = out[0] if out else "(no output)"
        shown = cmd if "community" not in cmd and "passphrase" not in cmd else cmd.rsplit(" ", 1)[0] + " ***"
        print(f"{shown:55} {status}")
        if "Success" not in status:
            sys.exit(f"stopped: {shown!r} answered {out}")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "show"
    if action == "enable":
        run(ENABLE)
    elif action == "revert":
        run(REVERT)
    out = rshell("show snmp summary")
    print("\n".join(line for line in out.splitlines() if "Passphrase" not in line and "Community" not in line))
