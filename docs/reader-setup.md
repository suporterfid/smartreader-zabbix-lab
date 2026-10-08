# Setting up an R700 for the Zabbix lab

This tutorial prepares an Impinj R700 running the SmartReader CAP so the lab can monitor it: credentials,
network checks, SNMP polling and traps, and a final check from Zabbix. It takes about 15 minutes per
reader.

The examples use `192.0.2.10` for the reader and `192.0.2.20` for the PC that runs the lab. Replace them
with your own addresses.

## What you need

- An R700 on firmware 10.3.0 or later with the SmartReader CAP installed. The lab was checked on
  firmware 10.4.0 with CAP 4.0.1.109.
- The reader's `root` password, which also logs in to RShell over SSH.
- The CAP's web admin login. The factory default is `admin` / `admin`.
- A PC on the same network as the reader, with Docker, Python 3.10 or later, and this repository.

Only step 4 changes the reader, and only its SNMP settings. Step 8 undoes it.

## 1. Check that the PC can reach the reader

The reader serves three things the lab uses: its REST API on HTTPS 443, the CAP on HTTPS 8443, and SSH
for RShell.

```bash
ping 192.0.2.10
curl -k -u root:<password> https://192.0.2.10/api/v1/status
curl -k -u admin:<cap-password> https://192.0.2.10:8443/api/getstatus
ssh root@192.0.2.10 "show system platform"
```

- The REST call returns JSON with a `status` field (`running`, `idle`, …).
- The CAP call returns `[{"status":"STARTED", …}]` or `"STOPPED"`.
- If you only know the reader's host name, which has the form `impinj-xx-xx-xx`, the R700 also answers
  on mDNS as `impinj-xx-xx-xx.local`.

The CAP also reports its own view of the reader's REST API:

```bash
curl -k -u admin:<cap-password> https://192.0.2.10:8443/api/reader-rest-health
```

`"healthy": true` with `"status": "Ok"` is what you want. `RestInterfaceDisabled` means the reader is in
LLRP mode, and SmartReader needs the REST interface. Switch it back in RShell:

```text
> config rfid interface rest
```

Keep the REST API on basic authentication, the default (`config access authentication basic`). The
lab's REST checks send basic credentials.

## 2. Replace the factory passwords

Do this before the reader goes anywhere near production.

**Reader `root` password.** Firmware 10.3.0 and later make you change it at the first login to the
reader's web UI (`https://192.0.2.10/`). To change it later, use RShell:

```text
> config access mypasswd <old password> <new password>
```

The CAP talks to the reader with this same password. After you change it, open the CAP admin at
`https://192.0.2.10:8443/admin/`, go to **Admin**, and click **Update RShell Password** with the new
value. Otherwise the CAP loses its connection to the reader.

**CAP web admin password.** In the same **Admin** page, use **Update Admin Password**. The lab signs in
to the CAP with this login.

Then put both passwords in the lab's `.env`:

```bash
cp .env.example .env
```

```ini
READER_HOST=192.0.2.10
READER_USER=root
READER_PASSWORD=<new root password>
CAP_USER=admin
CAP_PASSWORD=<new CAP admin password>
LAB_HOST_IP=192.0.2.20
```

`LAB_HOST_IP` is the PC's address as the reader sees it; the reader sends its traps there. On Windows,
`ipconfig` lists it under the adapter on the reader's network.

## 3. Look at the reader's current SNMP settings

SNMP is disabled on a new R700. Check what this one has before changing it:

```bash
python reader_snmp.py show
```

```text
SnmpService='Disabled'
TrapService='Disabled'
SnmpVersion2c='Disabled'
...
```

If anything here is already enabled, someone configured SNMP on this reader. Save the full output of
`show snmp all` in RShell before you go on, because step 8 resets SNMP to factory defaults rather than
to what you had.

## 4. Turn on SNMP and traps

Pick a read-only community and a trap community, and set them in `.env`:

```ini
SNMP_COMMUNITY=<read-only community>
SNMP_TRAP_COMMUNITY=<trap community>
```

Then run:

```bash
python reader_snmp.py enable
```

It sends these RShell commands, each of which should answer `Status='0,Success'`:

```text
> config snmp access rocommunity <read-only community>
> config snmp write disable all
> config snmp version 2c enable
> config snmp access trapcommunity <trap community>
> config snmp trap sink 192.0.2.20
> config snmp trap port 162
> config snmp trap enable unexpectedrestart
> config snmp trapservice enable
> config snmp service enable
```

You can type them yourself in an RShell session (`ssh root@192.0.2.10`) instead.

Some notes on these settings:

- **SNMP writes stay off.** The reader's writable objects include reboot and reset statistics, and
  monitoring needs none of them.
- **The traps are v2c.** That is the only version the R700 sends.
- **The reader takes up to four trap destinations.** Use `config snmp trap sink2 <host>` and so on.

If you prefer SNMPv3, the R700 supports one read-only user with MD5 authentication and no encryption
(`config snmp v3 ro …`). The lab's host is set up for v2c, so change its SNMP interface in Zabbix to
SNMPv3 *authNoPriv* if you go that way.

## 5. Label the reader (optional)

Two values the reader reports over SNMP are yours to set, and Zabbix copies the location into the host
inventory:

```text
> config system location "Warehouse 2, dock door 4"
> config snmp epcg device role inbound-dock
```

Until you set them, the location reads `unknown` and the role `My Reader Role`.

## 6. Find out which antenna ports are connected

The lab discovers one item set per antenna. A port that is in the active preset but has no antenna
reports *down* and would raise "antenna down" forever, so tell the lab which ports to watch. In RShell:

```text
> show rfid stat
...
Antenna1OperationalStatus='enabled'
Antenna2OperationalStatus='disabled'
...
```

Ports showing `enabled` have a working antenna. Set the matching regex in `.env`:

```ini
R700_ANTENNAS=^1$          # only port 1
# R700_ANTENNAS=^(1|2)$    # ports 1 and 2
```

## 7. Check it from the PC, then from Zabbix

Make sure SNMP answers, using a throwaway container so you don't need Net-SNMP on the PC:

```bash
docker run --rm alpine:3.20 sh -c "apk add -q net-snmp-tools && \
  snmpget -v2c -c <read-only community> -On 192.0.2.10 1.3.6.1.2.1.1.2.0"
```

It should print `.1.3.6.1.4.1.25882.2.1.5`, the R700's object ID. Then start and provision the lab:

```bash
docker compose up -d
python provision.py
python status.py --wait
```

`status.py` should report no unsupported items and list the reader's values. To prove the trap path,
send a request with a wrong community. The reader answers with an `authenticationFailure` trap, which
opens a problem in Zabbix within a few seconds:

```bash
docker run --rm alpine:3.20 sh -c "apk add -q net-snmp-tools && \
  snmpget -v2c -c wrong-community -t 2 -r 0 192.0.2.10 1.3.6.1.2.1.1.5.0"
python status.py
```

If the trap does not show up:

- **No trap in the receiver log at all.** The reader sends to `LAB_HOST_IP` on UDP 162, so either that
  address is wrong or the PC's firewall drops the packets. On Windows, allow UDP 162 inbound:

  ```powershell
  New-NetFirewallRule -DisplayName "Zabbix lab SNMP traps" -Direction Inbound -Protocol UDP -LocalPort 162 -Action Allow
  ```

- **The trap is in the log but Zabbix shows nothing.** The source address does not match the host. Check
  the `UDP: [...]` line of the trap:

  ```bash
  docker compose exec zabbix-snmptraps tail /var/lib/zabbix/snmptraps/snmptraps.log
  ```

  Then set `TRAP_SOURCE_IP` in `.env` to that address and run `python provision.py` again. Docker
  Desktop shows `172.31.67.1`, the default; Docker Engine on Linux usually shows the reader's own IP.

## 8. Undo the SNMP changes

When you no longer need the lab:

```bash
python reader_snmp.py revert     # runs "config snmp reset": SNMP and traps back to disabled
python reader_snmp.py show
```

The passwords from step 2 and the location from step 5 stay as they are. The device role is an SNMP
setting, so the reset may clear it too.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `snmpget` times out | SNMP service or v2c disabled, or wrong community | `python reader_snmp.py show`; re-run `enable` |
| Every SNMP item unsupported in Zabbix | Community in `.env` differs from the reader's | Fix `SNMP_COMMUNITY` and re-run `provision.py` |
| CAP items fail with HTTP 401 | Wrong CAP login in `.env` | Fix `CAP_USER` / `CAP_PASSWORD` and re-run `provision.py` |
| CAP items fail with HTTP 429 | 20 failed CAP logins in a minute locked the PC out for 60 s | Fix the login, then wait a minute |
| REST items fail with HTTP 401 | Reader password changed but not in `.env` | Update `READER_PASSWORD` and re-run `provision.py` |
| "CAP cannot use the reader REST API" | The CAP has an old reader password, or the reader is in LLRP mode | CAP **Admin → Update RShell Password**; `config rfid interface rest` |
| "Antenna N is down" for an empty port | That port is in the preset but has no antenna | Set `R700_ANTENNAS` (step 6) and re-run `provision.py` |
| "SNMP agent restarted" after a change | Every SNMP settings change restarts the reader's agent | Expected; it clears after 10 minutes |
| "CAP MQTT Certificate is red" while MQTT works | CAP 4.0.1.109 flags TLS without a CA and a client certificate | Known CAP issue; upload the broker's CA in the CAP if you have it |

`provision.py` rebuilds the host from scratch, so collected history starts over each time you run it.
