# SNMPv3 from SmartReader (experimental)

> **Experimental.** SmartReader is getting its own SNMPv3 agent, but **no released SmartReader CAP ships it
> yet**. Today only a SmartReader test build has it. Its objects sit under a **provisional root** that will
> move when the final one is allocated, and their layout may change before release. Until a release ships
> the agent, try this part of the lab with the **simulator** described below.
>
> Nothing here changes how the lab monitors the R700 itself. The reader's own agent is still polled over
> SNMP v2c and still sends v2c traps, exactly as in the [README](../README.md) and
> [reader-setup.md](reader-setup.md).

## What it adds

| | SmartReader's SNMPv3 agent |
|---|---|
| Where | Inside the SmartReader CAP on the reader, **UDP 1161** (the reader's own agent keeps UDP 161) |
| Security | SNMPv3 **authPriv** only (SHA-2 and AES); read-only, every SET is refused |
| Data | CAP health the CAP already collects: CPU, memory, disk, CPU temperature, reader and CAP uptime, MQTT connection and backlog, process memory, CPU and threads, the agent's own request counters |
| Notifications | SNMPv3 **INFORMs** to the lab's trap receiver, acknowledged by it |
| What Zabbix no longer needs | The CAP admin password and the reader root password: the HTTP and REST templates use them, this one uses a read-only SNMPv3 user |

The lab adds three things, all off unless `.env` turns them on:

- **A template, *SmartReader CAP by SNMPv3 (experimental)*,** with 26 items, a trap item for SmartReader's
  informs and 10 triggers. Every SmartReader OID is written relative to the macro `{$SR.SNMP.ROOT}`, so the
  final root needs one macro change, not a new template.
- **A third interface on the reader's host.** It uses SNMPv3 on `READER_HOST:1161`, next to the v2c interface
  on port 161 and the trap-only interface.
- **A simulator.** Net-SNMP's agent in a container answers for the same objects with synthetic values,
  and has a host of its own in Zabbix.

## The settings

All in `.env`; `.env.example` lists them with their defaults.

| Setting | Meaning |
|---|---|
| `SR_SNMPV3_ENABLED` | `1` adds the SNMPv3 interface and template to the reader's host. Needs a CAP with the agent |
| `SR_SNMPV3_SIMULATOR` | `1` adds the simulator's host |
| `SR_SNMPV3_PORT` | The agent's UDP port, `1161` |
| `SR_SNMPV3_USER` | USM user name |
| `SR_SNMPV3_AUTH_PROTOCOL`, `SR_SNMPV3_AUTH_PASSPHRASE` | `SHA1`, `SHA224`, `SHA256`, `SHA384` or `SHA512`, and its passphrase (8 characters or more) |
| `SR_SNMPV3_PRIV_PROTOCOL`, `SR_SNMPV3_PRIV_PASSPHRASE` | `AES128`, `AES192` or `AES256`, and its passphrase |
| `SR_SNMP_ROOT` | Root of SmartReader's objects. Provisional: `1.3.6.1.4.1.8072.9999.9999.7` |

The simulator, the trap receiver and Zabbix all take the user from these settings. Zabbix keeps the
passphrases as secret host macros (`{$SR.SNMPV3.AUTHPASS}`, `{$SR.SNMPV3.PRIVPASS}`).

## A. Try it with the simulator

No reader is involved. You need the lab running ([README](../README.md), quick start).

1. Pick a user and two passphrases in `.env`:

   ```ini
   SR_SNMPV3_SIMULATOR=1
   SR_SNMPV3_USER=srlab
   SR_SNMPV3_AUTH_PROTOCOL=SHA256
   SR_SNMPV3_AUTH_PASSPHRASE=<8 characters or more>
   SR_SNMPV3_PRIV_PROTOCOL=AES128
   SR_SNMPV3_PRIV_PASSPHRASE=<8 characters or more>
   ```

2. Start the simulator, let the trap receiver accept the user, and check the agent:

   ```bash
   docker compose --profile snmpv3-sim up -d --build
   python smartreader_snmpv3.py traps       # writes snmptrapd/snmptrapd_custom.conf, restarts zabbix-snmptraps
   python smartreader_snmpv3.py check --sim
   ```

   `check --sim` prints the simulator's description and a few of SmartReader's values, fetched over authPriv.

3. Build the Zabbix side and look at it:

   ```bash
   python provision.py
   python status.py --host smartreader-snmpv3-sim --wait
   ```

   Expect about 27 items, none unsupported, and the interface `172.31.67.20` available. In the web UI the
   host is *SmartReader SNMPv3 simulator*.

4. Send an INFORM and watch it arrive:

   ```bash
   python smartreader_snmpv3.py inform --sim
   python status.py --host smartreader-snmpv3-sim
   ```

   *Trap: SmartReader SNMPv3 notification* gets a value, and *SmartReader SNMPv3 notification received* opens
   as a problem for 15 minutes.

## B. Monitor a reader whose CAP has the agent

1. **The USM user.**
   - On the SmartReader **test build**, the agent generates its passphrases on the reader and shows them to
     the CAP admin. Copy them into `.env`:

     ```bash
     python smartreader_snmpv3.py credentials   # sets SR_SNMPV3_ENABLED=1 and the SR_SNMPV3_* user
     ```

   - On a later build, set the `SR_SNMPV3_*` values by hand to the user you configured in the CAP, and set
     `SR_SNMPV3_ENABLED=1`.

2. **Let the trap receiver accept the informs, and check the agent from the lab:**

   ```bash
   python smartreader_snmpv3.py traps
   python smartreader_snmpv3.py check
   ```

3. **Build the Zabbix side:**

   ```bash
   python provision.py
   python status.py --wait
   ```

   The reader's host now has three interfaces: SNMP v2c on 161, the trap-only interface, and SNMPv3 on 1161.
   Its items are those of the four templates, none unsupported. A Zabbix host with two SNMP interfaces
   links every SNMP item to its main (v2c) one, so `provision.py` creates the SNMPv3 items disabled, moves
   them to the SNMPv3 interface, enables them there and asks for a first check.

4. **An INFORM from the CAP** (test build):

   ```bash
   python smartreader_snmpv3.py inform
   ```

   On Docker Desktop it arrives from `172.31.67.1`, like the reader's v2c traps, so it lands on the
   trap-only interface. There *Trap: SmartReader SNMPv3 notification* matches it before *Trap: other* can.

## What the template collects

`{ROOT}` is `{$SR.SNMP.ROOT}`, provisionally `1.3.6.1.4.1.8072.9999.9999.7`. Every polled item uses the
SNMPv3 interface on port 1161.

### Item keys and values read in the tests

The two example columns are values Zabbix stored, after the template's preprocessing.

- **R700:** the bench reader (R700 Rev1, firmware 10.4.0) running the SmartReader SNMPv3 test build,
  polled by Zabbix 7.0.31 on 2026-10-13. Values marked ² are from the 2026-10-09 run of the same build:
  they are what those OIDs serve, but that run read them from the agent's own diagnostics rather than over
  SNMP, and the 2026-10-13 run did not record them.
- **Simulator:** `smartreader-snmpv3-sim`, read on 2026-10-13 around 15:40 UTC. Its values are synthetic.

| Key | Item | OID | SNMP type, conversion | R700 | Simulator |
|---|---|---|---|---|---|
| `sr3.agent.uptime` | SNMPv3 agent uptime | `1.3.6.1.2.1.1.3.0` (sysUpTime) | TimeTicks; × 0.01 → s | 1403.38 s (00:23:23) | 1411.31 s (00:23:31) |
| `sr3.sysdescr` | SNMPv3 agent description | `1.3.6.1.2.1.1.1.0` (sysDescr) | OCTET STRING | `SmartReader CAP 4.0.1.200 on R700 (…)` | `SmartReader SNMPv3 simulator (lab, synthetic values)` |
| `sr3.sysobjectid` | SNMPv3 agent object ID | `1.3.6.1.2.1.1.2.0` (sysObjectID) | OBJECT IDENTIFIER | `NET-SNMP-MIB::netSnmpPlaypen.7.1` | `NET-SNMP-MIB::netSnmpPlaypen.7.1` |
| `sr3.engine.id` | SNMPv3 engine ID | `1.3.6.1.6.3.10.2.1.1.0` (snmpEngineID) | OCTET STRING (hex) | `80 00 65 1A 05 4C B3 D1 76 1C D7 3E 86` | `80 00 1F 88 80 AB FA 63 2C C2 4B CE 6A 00 00 00 00` |
| `sr3.engine.boots` | SNMPv3 engine boots | `1.3.6.1.6.3.10.2.1.2.0` (snmpEngineBoots) | INTEGER | 6 | 1 |
| `sr3.cpu` | CAP process CPU | `{ROOT}.2.1.0` | Gauge32, % × 100; × 0.01 → % | 11.19 % | 21.87 % |
| `sr3.memory` | CAP process memory | `{ROOT}.2.2.0` | Gauge32, MB; × 1048576 → B | 232783872 B (222 MB)² | 185597952 B (177 MB) |
| `sr3.disk.pused` | CAP file system used | `{ROOT}.2.3.0` | Gauge32, % × 100; × 0.01 → % | 43.95 %² | 28.35 % |
| `sr3.os.uptime` | Reader OS uptime | `{ROOT}.2.4.0` | Gauge32, s | 714 s (00:11:54, just after a reboot) | 64189 s (17:49:49) |
| `sr3.app.uptime` | CAP application uptime | `{ROOT}.2.5.0` | Gauge32, s | 60972 s (16:56:12)² | 1406 s (00:23:26) |
| `sr3.cpu.temp` | CPU temperature | `{ROOT}.2.6.0` | Gauge32, °C × 10; × 0.1 → °C | 48.5 °C | 49 °C |
| `sr3.cpu.temp.max` | CPU temperature limit | `{ROOT}.2.7.0` | Gauge32, °C × 10; × 0.1 → °C | 80 °C | 105 °C |
| `sr3.cpu.temp.peak` | CPU temperature peak | `{ROOT}.2.8.0` | Gauge32, °C × 10; × 0.1 → °C | 48.6 °C | 55.4 °C |
| `sr3.mqtt.connected` | CAP connected to MQTT broker | `{ROOT}.2.9.0` | Gauge32, 0 / 1; value map Up/Down | 0 (Down: MQTT was switched off on that test CAP) | 1 (Up) |
| `sr3.mqtt.pending` | CAP MQTT messages pending | `{ROOT}.2.10.0` | Gauge32 | 40² | 3 |
| `sr3.process.rss` | CAP resident memory | `{ROOT}.2.20.0` | Gauge32, bytes | 233701376 B (223 MiB)² | 209656778 B (200 MiB) |
| `sr3.process.cpu` | CAP CPU, % of one core | `{ROOT}.2.21.0` | Counter64, CPU ms; change per second × 0.1 → % | 26.79 % | 28.00 % |
| `sr3.process.heap` | CAP managed heap | `{ROOT}.2.22.0` | Gauge32, bytes | 105804808 B (101 MiB)² | 84928473 B (81 MiB) |
| `sr3.process.threads` | CAP threads | `{ROOT}.2.23.0` | Gauge32 | 28² | 27 |
| `sr3.requests` | SNMPv3 requests per second | `{ROOT}.3.1.0` | Counter32; change per second | 0.415 rps | 0.499 rps |
| `sr3.unknown.users` | SNMPv3 unknown user names per second | `{ROOT}.3.4.0` | Counter32; change per second | 0 rps | 0 rps |
| `sr3.wrong.digests` | SNMPv3 wrong digests (authentication failures) per second | `{ROOT}.3.6.0` | Counter32; change per second | 0 rps | 0 rps |
| `sr3.decryption.errors` | SNMPv3 decryption errors per second | `{ROOT}.3.7.0` | Counter32; change per second | 0 rps; 0.0998 rps during the wrong-key test | 0 rps |
| `sr3.time.window` | SNMPv3 requests outside the time window per second | `{ROOT}.3.8.0` | Counter32; change per second | 0 rps | 0 rps |
| `sr3.rate.limited` | SNMPv3 requests dropped by the rate limit per second | `{ROOT}.3.11.0` | Counter32; change per second | 0 rps | 0 rps |
| `sr3.set.refused` | SNMPv3 SET requests refused per second | `{ROOT}.3.12.0` | Counter32; change per second | 0 rps | 0 rps |
| `snmptrap["netSnmpPlaypen\.7\.0\.\|8072\.9999\.9999\.7\.0\."]` | Trap: SmartReader SNMPv3 notification | INFORMs under `{ROOT}.0` | log; one item for every SmartReader notification | the trap below | the trap below |

The CAP's CPU on the reader moves a lot. Zabbix stored 11.19 %, and the Net-SNMP GET below read 73.14 %
right after the CAP had started. Both are right: it is the average over the last 10 s.

### Raw SNMP answers

Net-SNMP 5.9 over authPriv SHA-256 / AES-128, from the lab's network. They show the scaling the template
undoes: `Gauge32: 7314` on `{ROOT}.2.1.0` is 73.14 %, `Gauge32: 490` on `{ROOT}.2.6.0` is 49 °C.

R700, 2026-10-13 (`python smartreader_snmpv3.py check`):

```text
.1.3.6.1.2.1.1.1.0 = STRING: SmartReader CAP 4.0.1.200 on R700 (…)
.1.3.6.1.6.3.10.2.1.2.0 = INTEGER: 6
.1.3.6.1.4.1.8072.9999.9999.7.2.1.0 = Gauge32: 7314
.1.3.6.1.4.1.8072.9999.9999.7.2.9.0 = Gauge32: 0
```

R700, 2026-10-09, a walk of `{ROOT}.3`, the agent's counters since its start. The template polls the ones
marked •. The others are there for diagnosis.

```text
.1.3.6.1.4.1.8072.9999.9999.7.3.1.0 = Counter32: 149     • requests received
.1.3.6.1.4.1.8072.9999.9999.7.3.2.0 = Counter32: 147       responses sent
.1.3.6.1.4.1.8072.9999.9999.7.3.3.0 = Counter32: 27        discovery requests
.1.3.6.1.4.1.8072.9999.9999.7.3.4.0 = Counter32: 2       • unknown user names
.1.3.6.1.4.1.8072.9999.9999.7.3.5.0 = Counter32: 0         unknown engine IDs
.1.3.6.1.4.1.8072.9999.9999.7.3.6.0 = Counter32: 1       • wrong digests
.1.3.6.1.4.1.8072.9999.9999.7.3.7.0 = Counter32: 12      • decryption errors
.1.3.6.1.4.1.8072.9999.9999.7.3.8.0 = Counter32: 0       • outside the time window
.1.3.6.1.4.1.8072.9999.9999.7.3.9.0 = Counter32: 4         unsupported security levels
.1.3.6.1.4.1.8072.9999.9999.7.3.10.0 = Counter32: 2        SNMPv1/v2c messages dropped
.1.3.6.1.4.1.8072.9999.9999.7.3.11.0 = Counter32: 0      • dropped by the rate limit
.1.3.6.1.4.1.8072.9999.9999.7.3.12.0 = Counter32: 1      • SET requests refused
.1.3.6.1.4.1.8072.9999.9999.7.3.13.0 = Counter32: 0        malformed messages
.1.3.6.1.4.1.8072.9999.9999.7.3.14.0 = Counter32: 0        responses too big
.1.3.6.1.4.1.8072.9999.9999.7.3.15.0 = Counter32: 0        other errors
.1.3.6.1.4.1.8072.9999.9999.7.3.16.0 = Counter32: 2        INFORMs sent
.1.3.6.1.4.1.8072.9999.9999.7.3.17.0 = Counter32: 2        INFORMs acknowledged
.1.3.6.1.4.1.8072.9999.9999.7.3.18.0 = Counter32: 0        INFORMs failed
```

That walk ran just after the wrong-passphrase, wrong-user and SET cases of the test, which is why those
counters are not zero.

Simulator, 2026-10-13 around 15:40 UTC (one GET per item OID):

```text
.1.3.6.1.2.1.1.3.0 = Timeticks: (143583) 0:23:55.83
.1.3.6.1.6.3.10.2.1.2.0 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.2.1.0 = Gauge32: 2078
.1.3.6.1.4.1.8072.9999.9999.7.2.2.0 = Gauge32: 177
.1.3.6.1.4.1.8072.9999.9999.7.2.3.0 = Gauge32: 2835
.1.3.6.1.4.1.8072.9999.9999.7.2.4.0 = Gauge32: 64214
.1.3.6.1.4.1.8072.9999.9999.7.2.5.0 = Gauge32: 1430
.1.3.6.1.4.1.8072.9999.9999.7.2.6.0 = Gauge32: 490
.1.3.6.1.4.1.8072.9999.9999.7.2.7.0 = Gauge32: 1050
.1.3.6.1.4.1.8072.9999.9999.7.2.8.0 = Gauge32: 554
.1.3.6.1.4.1.8072.9999.9999.7.2.9.0 = Gauge32: 1
.1.3.6.1.4.1.8072.9999.9999.7.2.10.0 = Gauge32: 1
.1.3.6.1.4.1.8072.9999.9999.7.2.20.0 = Gauge32: 205719888
.1.3.6.1.4.1.8072.9999.9999.7.2.21.0 = Counter64: 400726
.1.3.6.1.4.1.8072.9999.9999.7.2.22.0 = Gauge32: 99315922
.1.3.6.1.4.1.8072.9999.9999.7.2.23.0 = Gauge32: 27
.1.3.6.1.4.1.8072.9999.9999.7.3.1.0 = Counter32: 715
```

The simulator gets a new engine ID each time its container is recreated, because it keeps no state; the
one above is from after a rebuild. SmartReader's agent keeps its engine ID across CAP restarts and reboots:
`80 00 65 1A 05 4C B3 D1 76 1C D7 3E 86` on the bench reader, with boots climbing from 1 to 6.

### What an INFORM looks like

As the lab's trap receiver logs it (`snmptraps.log`), and as the trap item stores it.

From the CAP on the R700, 2026-10-13. Docker Desktop shows the lab network's gateway as the source, so
Zabbix matches it to the reader's trap-only interface. The reader's host name is masked.

```text
2026-10-13T13:23:15+0000 ZBXTRAP 172.31.67.1
UDP: [172.31.67.1]:56422->[172.31.67.3]:1162
DISMAN-EVENT-MIB::sysUpTimeInstance = 303301
SNMPv2-MIB::snmpTrapOID.0 = NET-SNMP-MIB::netSnmpPlaypen.7.0.1
SNMPv2-MIB::sysName.0 = impinj-xx-xx-xx
NET-SNMP-MIB::netSnmpPlaypen.7.2.4.0 = 1
```

The test build's notification is a test: its last varbind is a fixed `1`, not a reading.

From the simulator, 2026-10-13. It arrives from the container's own address, so it lands on the simulator's
host:

```text
2026-10-13T12:30:14+0000 ZBXTRAP 172.31.67.20
UDP: [172.31.67.20]:32976->[172.31.67.3]:1162
DISMAN-EVENT-MIB::sysUpTimeInstance = 68715077
SNMPv2-MIB::snmpTrapOID.0 = NET-SNMP-MIB::netSnmpPlaypen.7.0.1
SNMPv2-MIB::sysName.0 = smartreader-snmpv3-sim
```

### Triggers

| Trigger | Severity |
|---|---|
| The agent not answering | Average |
| CAP lost the MQTT broker | High |
| MQTT messages backing up | Average |
| File system above `{$SR.DISK.MAX}` % | Warning |
| CPU close to its temperature limit | Warning |
| Reader rebooted | Warning |
| CAP restarted | Warning |
| Engine restarted | Info |
| Requests with a wrong key | Warning |
| Notification received | Info |

On the reader's host, the HTTP template raises its own MQTT and disk problems from `/metrics`. The lab keeps
both so you can compare them; a production template would pick one.

## Checked on

| | |
|---|---|
| Date | 2026-10-13 |
| Reader | R700 Rev1, firmware 10.4.0 |
| CAP | SmartReader SNMPv3 test build |
| Zabbix | 7.0.31 |
| Results | All 26 SNMPv3 items supported over authPriv SHA-256 / AES-128, on the reader and on the simulator. The CAP's INFORM was acknowledged and matched on the reader's host; the simulator's on its own host. *Requests with a wrong key* opened for requests with a wrong key. The reader's v2c items and traps worked as before |

An earlier run against the same agent (2026-10-09) also passed SHA-512 / AES-256 and SHA-384 / AES-192 from
Net-SNMP 5.9, and SHA-512 / AES-256 from a Zabbix 7.0 interface.

## Notes

- **A wrong key often shows up as a decryption error, not an authentication failure.** The test build's
  agent decrypts a request before it checks the digest, so a request with both keys wrong counts as a
  decryption error. The wrong-key trigger watches both counters.
- **The first values of the hourly items** (description, object ID, engine ID) come from the check that
  `provision.py` requests. Without it, an item enabled after creation is first polled somewhere inside its
  hour.
- **AES-192 and AES-256** have two key-extension variants in the SNMP world. With SHA-384 or SHA-512 the
  localized key is long enough that they coincide. Pair AES-256 with SHA-512 and AES-192 with SHA-384.
- **The INFORM user:** an INFORM is authenticated with the receiver's engine ID. One `createUser` in
  `snmptrapd/snmptrapd_custom.conf` therefore covers every SmartReader that uses the same user, and the
  receiver needs no reader's engine ID.

## Back to SNMP v2c only

```bash
# .env: SR_SNMPV3_ENABLED=0 and SR_SNMPV3_SIMULATOR=0
docker compose --profile snmpv3-sim stop smartreader-snmpv3-sim
python provision.py
```

The reader's host goes back to its two interfaces and three templates. `snmptrapd/snmptrapd_custom.conf` can
stay; delete it and restart `zabbix-snmptraps` to remove the SNMPv3 user from the trap receiver.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `check` says `Unknown user name` | The user in `.env` is not the agent's | Set `SR_SNMPV3_USER` (or run `credentials` on the test build) |
| `Authentication failure` or `Decryption error` | Wrong passphrase or protocol | Check the `SR_SNMPV3_*` values against the agent |
| `Timeout` from `check` (reader) | The CAP has no SNMPv3 agent, or UDP 1161 is blocked on the way | A released CAP does not have the agent yet; use the simulator |
| SNMPv3 items show values of the reader's own agent | The items were polled on the v2c interface | Re-run `provision.py`; it moves and enables them |
| INFORMs time out | snmptrapd does not know the user | `python smartreader_snmpv3.py traps` after every change of the `SR_SNMPV3_*` user |
| The simulator exits at start | `SR_SNMPV3_USER` or a passphrase is empty | Fill them in `.env`, then `docker compose --profile snmpv3-sim up -d` |
