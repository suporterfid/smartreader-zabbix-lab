"""Shared helpers for the Zabbix lab: settings from .env, RShell over SSH, and HTTPS calls to the CAP and reader."""
import base64
import json
import pathlib
import ssl
import urllib.request

import paramiko

HERE = pathlib.Path(__file__).parent


def load_env():
    path = HERE / ".env"
    if not path.exists():
        raise SystemExit("No .env file: copy .env.example to .env and fill in your reader's address and credentials.")
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


ENV = load_env()


def rshell(command, timeout=20):
    """Run one RShell command on the reader and return its output (RShell answers on the SSH exec channel)."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        ENV["READER_HOST"], username=ENV["READER_USER"], password=ENV["READER_PASSWORD"],
        timeout=timeout, allow_agent=False, look_for_keys=False,
    )
    try:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        return stdout.read().decode("utf-8", "replace") + stderr.read().decode("utf-8", "replace")
    finally:
        client.close()


def _get(url, user, password, timeout=10):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # both the CAP (CN=localhost) and the reader use self-signed certificates
    req = urllib.request.Request(url)
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def cap_get(path):
    return _get(f"https://{ENV['READER_HOST']}:8443{path}", ENV["CAP_USER"], ENV["CAP_PASSWORD"])


def reader_get(path):
    return _get(f"https://{ENV['READER_HOST']}/api/v1{path}", ENV["READER_USER"], ENV["READER_PASSWORD"])


def as_json(body):
    try:
        return json.loads(body)
    except ValueError:
        return body
