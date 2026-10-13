"""Helpers for SmartReader's own SNMPv3 agent (EXPERIMENTAL). See docs/smartreader-snmpv3.md.

  python smartreader_snmpv3.py credentials   # SmartReader SNMPv3 test build: copy its USM user into .env
  python smartreader_snmpv3.py traps         # let the lab's snmptrapd accept SmartReader's informs
  python smartreader_snmpv3.py check [--sim] # one SNMPv3 GET against the CAP (or the simulator)
  python smartreader_snmpv3.py inform [--sim] # make the CAP (or the simulator) send an INFORM to the lab

Nothing here touches the reader's own SNMP agent; reader_snmp.py does that.
"""
import json
import pathlib
import re
import subprocess
import sys

from lablib import ENV, HERE

ENV_FILE = HERE / ".env"
TRAPD_FILE = HERE / "snmptrapd" / "snmptrapd_custom.conf"
SIM_IP = "172.31.67.20"
ROOT = ENV.get("SR_SNMP_ROOT", "1.3.6.1.4.1.8072.9999.9999.7").strip(".")
NETSNMP_AUTH = {"SHA1": "SHA", "SHA224": "SHA-224", "SHA256": "SHA-256", "SHA384": "SHA-384", "SHA512": "SHA-512"}
NETSNMP_PRIV = {"AES128": "AES", "AES192": "AES-192", "AES256": "AES-256"}


def usm():
    """User, Net-SNMP protocol names and passphrases from .env."""
    missing = [k for k in ("SR_SNMPV3_USER", "SR_SNMPV3_AUTH_PASSPHRASE", "SR_SNMPV3_PRIV_PASSPHRASE") if not ENV.get(k)]
    if missing:
        sys.exit(f"set {', '.join(missing)} in .env first (or run: python smartreader_snmpv3.py credentials)")
    return (ENV["SR_SNMPV3_USER"], NETSNMP_AUTH[ENV.get("SR_SNMPV3_AUTH_PROTOCOL", "SHA256")],
            ENV["SR_SNMPV3_AUTH_PASSPHRASE"], NETSNMP_PRIV[ENV.get("SR_SNMPV3_PRIV_PROTOCOL", "AES128")],
            ENV["SR_SNMPV3_PRIV_PASSPHRASE"])


def set_env(values):
    """Replace or append KEY=value lines in .env, keeping everything else as it is."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    for key, value in values.items():
        pattern = re.compile(rf"^{re.escape(key)}=")
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def credentials():
    """The SmartReader SNMPv3 test build generates its USM passphrases on the reader and shows them to the admin."""
    import lablib
    try:
        status, body = lablib.cap_get("/api/spike/snmp")
    except Exception as exc:  # noqa: BLE001 - 404 and connection errors alike
        sys.exit(f"the CAP did not answer /api/spike/snmp ({exc}). Only the SmartReader SNMPv3 test build has "
                 "it; on another build, put the USM user its documentation gives you into .env by hand.")
    agent = json.loads(body)
    user = next(u for u in agent["users"] if u["name"] == "srspike")
    set_env({
        "SR_SNMPV3_ENABLED": "1",
        "SR_SNMPV3_PORT": str(agent.get("port", 1161)),
        "SR_SNMPV3_USER": user["name"],
        "SR_SNMPV3_AUTH_PROTOCOL": user["auth"].replace("-", ""),
        "SR_SNMPV3_AUTH_PASSPHRASE": agent["authPassphrase"],
        "SR_SNMPV3_PRIV_PROTOCOL": user["priv"].replace("-", ""),
        "SR_SNMPV3_PRIV_PASSPHRASE": agent["privPassphrase"],
    })
    print(f"SmartReader SNMPv3 agent on {ENV['READER_HOST']}:{agent.get('port')}: {agent.get('binding')}, "
          f"engine {agent.get('engineIdHex')}, boots {agent.get('engineBoots')}")
    print(f"wrote SR_SNMPV3_* to .env for user {user['name']} ({user['auth']}, {user['priv']}); passphrases not shown")


def traps():
    user, auth, auth_pass, priv, priv_pass = usm()
    TRAPD_FILE.parent.mkdir(exist_ok=True)
    TRAPD_FILE.write_text(
        "# Written by smartreader_snmpv3.py from the SR_SNMPV3_* settings in .env. Holds passphrases.\n"
        "# INFORMs use the receiver's engine ID, so this one user covers every SmartReader that sends with it.\n"
        f'createUser {user} {auth} "{auth_pass}" {priv} "{priv_pass}"\n', encoding="utf-8")
    subprocess.run(["docker", "compose", "restart", "zabbix-snmptraps"], cwd=HERE, check=True)
    print(f"snmptrapd now accepts SNMPv3 informs from user {user} ({auth}, {priv})")


SIM_IMAGE = "smartreader-zabbix-lab-smartreader-snmpv3-sim"  # built by: docker compose --profile snmpv3-sim build
LAB_NETWORK = "smartreader-zabbix-lab_default"


def netsnmp(*args):
    """Run a Net-SNMP command on the lab's network, with the simulator image (it carries the tools)."""
    cmd = ["docker", "run", "--rm", "--network", LAB_NETWORK, "--entrypoint", args[0], SIM_IMAGE, *args[1:]]
    return subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)


def v3_args():
    user, auth, auth_pass, priv, priv_pass = usm()
    return ["-v3", "-l", "authPriv", "-u", user, "-a", auth, "-A", auth_pass, "-x", priv, "-X", priv_pass,
            "-On", "-t", "5", "-r", "1"]


def check(sim):
    target = f"{SIM_IP if sim else ENV['READER_HOST']}:{ENV.get('SR_SNMPV3_PORT', '1161')}"
    out = netsnmp("snmpget", *v3_args(), target, "1.3.6.1.2.1.1.1.0", "1.3.6.1.6.3.10.2.1.2.0", f"{ROOT}.2.1.0",
                  f"{ROOT}.2.9.0")
    print(f"SNMPv3 GET {target}:")
    print(out.stdout.strip() or out.stderr.strip())
    if out.returncode:
        sys.exit(out.returncode)


def inform(sim):
    if sim:
        cmd = ["docker", "compose", "exec", "-T", "smartreader-snmpv3-sim", "snmpinform", *v3_args(),
               "zabbix-snmptraps:1162", "", f"{ROOT}.0.1", "1.3.6.1.2.1.1.5.0", "s", "smartreader-snmpv3-sim"]
        out = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
        print("simulator INFORM:", "acknowledged" if out.returncode == 0 else out.stderr.strip())
        sys.exit(out.returncode)
    import urllib.parse
    query = urllib.parse.urlencode({"host": ENV["LAB_HOST_IP"], "port": 162, "user": ENV["SR_SNMPV3_USER"]})
    status, body = _cap_post(f"/api/spike/snmp/inform?{query}")
    print("CAP INFORM:", status, body)


def _cap_post(path):
    import base64
    import ssl
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(f"https://{ENV['READER_HOST']}:8443{path}", data=b"", method="POST")
    token = base64.b64encode(f"{ENV['CAP_USER']}:{ENV['CAP_PASSWORD']}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    sim = "--sim" in sys.argv
    if action == "credentials":
        credentials()
    elif action == "traps":
        traps()
    elif action == "check":
        check(sim)
    elif action == "inform":
        inform(sim)
    else:
        print(__doc__)
