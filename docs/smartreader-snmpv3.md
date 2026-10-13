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

`{ROOT}` is `{$SR.SNMP.ROOT}`, provisionally `1.3.6.1.4.1.8072.9999.9999.7`. Every polled item uses the SNMPv3 interface on
port 1161. The template is also published for import: [templates/zbx_smartreader_cap_snmpv3.yaml](../templates/zbx_smartreader_cap_snmpv3.yaml)
(see [Import the template](#import-the-template)).

### Item keys and values read in the tests

All 27 keys of the template, each read over SNMPv3 on 2026-10-13 16:25:16 UTC:

- **R700:** the bench reader (R700 Rev1, firmware 10.4.0) running the SmartReader SNMPv3 test build
  (engine boots 7). MQTT was switched off on that test CAP, hence `mqtt.connected` 0.
- **Simulator:** `smartreader-snmpv3-sim`; synthetic values.

Each row has the key and its OID. `snmp_type` and `agent_value_is` say what the agent answers. The
`*_snmp` columns hold the raw answer from Net-SNMP 5.9 (authPriv SHA-256 / AES-128). The `*_zabbix` columns
hold the value Zabbix 7.0.31 stored after `zabbix_preprocessing`, in `zabbix_units`. The two come from
reads a few seconds apart, so a moving value such as CPU differs between them: on the reader, raw `1289` is
12.89 % while Zabbix had stored 11.23 % from its own poll. The reader's `sysDescr` ends in a build label,
elided as `(…)`.

```csv
key,item,oid,snmp_type,agent_value_is,zabbix_preprocessing,zabbix_units,r700_snmp,r700_zabbix,simulator_snmp,simulator_zabbix
sr3.agent.uptime,SNMPv3 agent uptime,1.3.6.1.2.1.1.3.0,Timeticks,hundredths of a second,multiply by 0.01,uptime,(122745) 0:20:27.45,1208.93,(118420) 0:19:44.20,1161.51
sr3.sysdescr,SNMPv3 agent description,1.3.6.1.2.1.1.1.0,STRING,,,,SmartReader CAP 4.0.1.200 on R700 (…),SmartReader CAP 4.0.1.200 on R700 (…),"SmartReader SNMPv3 simulator (lab, synthetic values)","SmartReader SNMPv3 simulator (lab, synthetic values)"
sr3.sysobjectid,SNMPv3 agent object ID,1.3.6.1.2.1.1.2.0,OID,,,,.1.3.6.1.4.1.8072.9999.9999.7.1,NET-SNMP-MIB::netSnmpPlaypen.7.1,.1.3.6.1.4.1.8072.9999.9999.7.1,NET-SNMP-MIB::netSnmpPlaypen.7.1
sr3.engine.id,SNMPv3 engine ID,1.3.6.1.6.3.10.2.1.1.0,Hex-STRING,,,,80 00 65 1A 05 4C B3 D1 76 1C D7 3E 86,80 00 65 1A 05 4C B3 D1 76 1C D7 3E 86,80 00 1F 88 80 6E 3E 6C 40 D4 56 CE 6A 00 00 00 00,80 00 1F 88 80 6E 3E 6C 40 D4 56 CE 6A 00 00 00 00
sr3.engine.boots,SNMPv3 engine boots,1.3.6.1.6.3.10.2.1.2.0,INTEGER,,,,7,7,1,1
sr3.cpu,CAP process CPU,{ROOT}.2.1.0,Gauge32,percent x 100,multiply by 0.01,%,1289,11.23,3001,26.18
sr3.memory,CAP process memory,{ROOT}.2.2.0,Gauge32,MB,multiply by 1048576,B,190,201326592,180,187695104
sr3.disk.pused,CAP file system used,{ROOT}.2.3.0,Gauge32,percent x 100,multiply by 0.01,%,4395,43.95,2835,28.35
sr3.os.uptime,Reader OS uptime,{ROOT}.2.4.0,Gauge32,seconds,,uptime,1325,1305,49808,49785
sr3.app.uptime,CAP application uptime,{ROOT}.2.5.0,Gauge32,seconds,,uptime,1223,1203,743,720
sr3.cpu.temp,CPU temperature,{ROOT}.2.6.0,Gauge32,degrees C x 10,multiply by 0.1,°C,486,48.7,538,54
sr3.cpu.temp.max,CPU temperature limit,{ROOT}.2.7.0,Gauge32,degrees C x 10,multiply by 0.1,°C,800,80,1050,105
sr3.cpu.temp.peak,CPU temperature peak,{ROOT}.2.8.0,Gauge32,degrees C x 10,multiply by 0.1,°C,488,48.8,554,55.4
sr3.mqtt.connected,CAP connected to MQTT broker,{ROOT}.2.9.0,Gauge32,0 or 1,,,0,0,1,1
sr3.mqtt.pending,CAP MQTT messages pending,{ROOT}.2.10.0,Gauge32,messages,,,0,0,1,2
sr3.process.rss,CAP resident memory,{ROOT}.2.20.0,Gauge32,bytes,,B,200237056,200237056,202428830,202990429
sr3.process.cpu,"CAP CPU, % of one core",{ROOT}.2.21.0,Counter64,CPU milliseconds since start,"change per second, then multiply by 0.1",%,445370,28.4402,208238,28.0014
sr3.process.heap,CAP managed heap,{ROOT}.2.22.0,Gauge32,bytes,,B,50456660,43069572,87281808,98089422
sr3.process.threads,CAP threads,{ROOT}.2.23.0,Gauge32,threads,,,26,27,27,27
sr3.requests,SNMPv3 requests per second,{ROOT}.3.1.0,Counter32,,change per second,rps,751,0.9448,371,0.4978
sr3.unknown.users,SNMPv3 unknown user names per second,{ROOT}.3.4.0,Counter32,,change per second,rps,0,0,0,0
sr3.wrong.digests,SNMPv3 wrong digests (authentication failures) per second,{ROOT}.3.6.0,Counter32,,change per second,rps,0,0,0,0
sr3.decryption.errors,SNMPv3 decryption errors per second,{ROOT}.3.7.0,Counter32,,change per second,rps,0,0,0,0
sr3.time.window,SNMPv3 requests outside the time window per second,{ROOT}.3.8.0,Counter32,,change per second,rps,5,0,0,0
sr3.rate.limited,SNMPv3 requests dropped by the rate limit per second,{ROOT}.3.11.0,Counter32,,change per second,rps,0,0,0,0
sr3.set.refused,SNMPv3 SET requests refused per second,{ROOT}.3.12.0,Counter32,,change per second,rps,0,0,0,0
"snmptrap[""netSnmpPlaypen\.7\.0\.|8072\.9999\.9999\.7\.0\.""]",Trap: SmartReader SNMPv3 notification,{ROOT}.0.* (INFORM),SNMPv3 INFORM,notification,,,snmpTrapOID.0 = NET-SNMP-MIB::netSnmpPlaypen.7.0.1,trap text (below),snmpTrapOID.0 = NET-SNMP-MIB::netSnmpPlaypen.7.0.1,trap text (below)
```

Every key was collected on both hosts: 26 SNMP items with a value and none unsupported, plus the trap item
with an INFORM from each side.

### Raw SNMP answers

A walk of `{ROOT}` on each agent at the same time, with Net-SNMP 5.9 over authPriv from the lab's network.
Values under `{ROOT}.2` are scaled integers (see `agent_value_is` above): `{ROOT}.2.1.0` is percent × 100
and `{ROOT}.2.6.0` is °C × 10. `{ROOT}.4` is a synthetic 25-row table the test build carries to size
walks; the template does not poll it.

R700, `{ROOT}.2` (health) and `{ROOT}.3` (agent counters since the CAP started):

```text
.1.3.6.1.4.1.8072.9999.9999.7.2.1.0 = Gauge32: 1289
.1.3.6.1.4.1.8072.9999.9999.7.2.2.0 = Gauge32: 190
.1.3.6.1.4.1.8072.9999.9999.7.2.3.0 = Gauge32: 4395
.1.3.6.1.4.1.8072.9999.9999.7.2.4.0 = Gauge32: 1325
.1.3.6.1.4.1.8072.9999.9999.7.2.5.0 = Gauge32: 1223
.1.3.6.1.4.1.8072.9999.9999.7.2.6.0 = Gauge32: 486
.1.3.6.1.4.1.8072.9999.9999.7.2.7.0 = Gauge32: 800
.1.3.6.1.4.1.8072.9999.9999.7.2.8.0 = Gauge32: 488
.1.3.6.1.4.1.8072.9999.9999.7.2.9.0 = Gauge32: 0
.1.3.6.1.4.1.8072.9999.9999.7.2.10.0 = Gauge32: 0
.1.3.6.1.4.1.8072.9999.9999.7.2.20.0 = Gauge32: 200237056
.1.3.6.1.4.1.8072.9999.9999.7.2.21.0 = Counter64: 445710
.1.3.6.1.4.1.8072.9999.9999.7.2.22.0 = Gauge32: 51653360
.1.3.6.1.4.1.8072.9999.9999.7.2.23.0 = Gauge32: 27
.1.3.6.1.4.1.8072.9999.9999.7.3.1.0 = Counter32: 769
.1.3.6.1.4.1.8072.9999.9999.7.3.2.0 = Counter32: 769
.1.3.6.1.4.1.8072.9999.9999.7.3.3.0 = Counter32: 375
.1.3.6.1.4.1.8072.9999.9999.7.3.4.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.5.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.6.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.7.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.8.0 = Counter32: 5
.1.3.6.1.4.1.8072.9999.9999.7.3.9.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.10.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.11.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.12.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.13.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.14.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.15.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.16.0 = Counter32: 1
.1.3.6.1.4.1.8072.9999.9999.7.3.17.0 = Counter32: 1
.1.3.6.1.4.1.8072.9999.9999.7.3.18.0 = Counter32: 0
```

The counters in `{ROOT}.3`, in order: 1 requests received · 2 responses sent · 3 discovery requests ·
4 unknown user names · 5 unknown engine IDs · 6 wrong digests · 7 decryption errors · 8 outside the time
window · 9 unsupported security levels · 10 SNMPv1/v2c messages dropped · 11 dropped by the rate limit ·
12 SET requests refused · 13 malformed messages · 14 responses too big · 15 other errors · 16 INFORMs sent ·
17 INFORMs acknowledged · 18 INFORMs failed. The template polls 1, 4, 6, 7, 8, 11 and 12.

`.3.8.0 = 5` on the reader is real: after the reboot, managers still held the engine's previous boots value,
were refused as outside the time window, and resynchronized. It happens once per manager after a reboot.

Simulator, `{ROOT}.2` and `{ROOT}.3`:

```text
.1.3.6.1.4.1.8072.9999.9999.7.2.1.0 = Gauge32: 3000
.1.3.6.1.4.1.8072.9999.9999.7.2.2.0 = Gauge32: 180
.1.3.6.1.4.1.8072.9999.9999.7.2.3.0 = Gauge32: 2835
.1.3.6.1.4.1.8072.9999.9999.7.2.4.0 = Gauge32: 49809
.1.3.6.1.4.1.8072.9999.9999.7.2.5.0 = Gauge32: 744
.1.3.6.1.4.1.8072.9999.9999.7.2.6.0 = Gauge32: 538
.1.3.6.1.4.1.8072.9999.9999.7.2.7.0 = Gauge32: 1050
.1.3.6.1.4.1.8072.9999.9999.7.2.8.0 = Gauge32: 554
.1.3.6.1.4.1.8072.9999.9999.7.2.9.0 = Gauge32: 1
.1.3.6.1.4.1.8072.9999.9999.7.2.10.0 = Gauge32: 1
.1.3.6.1.4.1.8072.9999.9999.7.2.20.0 = Gauge32: 202758486
.1.3.6.1.4.1.8072.9999.9999.7.2.21.0 = Counter64: 208523
.1.3.6.1.4.1.8072.9999.9999.7.2.22.0 = Gauge32: 97821910
.1.3.6.1.4.1.8072.9999.9999.7.2.23.0 = Gauge32: 27
.1.3.6.1.4.1.8072.9999.9999.7.3.1.0 = Counter32: 372
.1.3.6.1.4.1.8072.9999.9999.7.3.2.0 = Counter32: 372
.1.3.6.1.4.1.8072.9999.9999.7.3.3.0 = Counter32: 2
.1.3.6.1.4.1.8072.9999.9999.7.3.4.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.5.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.6.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.7.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.8.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.9.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.10.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.11.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.12.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.13.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.14.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.15.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.16.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.17.0 = Counter32: 0
.1.3.6.1.4.1.8072.9999.9999.7.3.18.0 = Counter32: 0
```

The simulator gets a new engine ID each time its container is recreated, because it keeps no state.
SmartReader's agent keeps its engine ID across CAP restarts and reboots: `80 00 65 1A 05 4C B3 D1 76 1C D7 3E 86`
on the bench reader, with boots climbing from 1 to 7 over the tests.

### What an INFORM looks like

As the trap item stores it, from the same run.

From the CAP on the R700. Docker Desktop shows the lab network's gateway as the source, so Zabbix matches it
to the reader's trap-only interface. The reader's host name is masked. The test build's notification is a
test: its last varbind is a fixed `1`, not a reading.

```text
2026-10-13T16:24:55+0000 UDP: [172.31.67.1]:38675->[172.31.67.3]:1162
DISMAN-EVENT-MIB::sysUpTimeInstance = 130727
SNMPv2-MIB::snmpTrapOID.0 = NET-SNMP-MIB::netSnmpPlaypen.7.0.1
SNMPv2-MIB::sysName.0 = impinj-xx-xx-xx
NET-SNMP-MIB::netSnmpPlaypen.7.2.4.0 = 1
```

From the simulator. It arrives from the container's own address, so it lands on the simulator's host:

```text
2026-10-13T16:24:56+0000 UDP: [172.31.67.20]:46628->[172.31.67.3]:1162
DISMAN-EVENT-MIB::sysUpTimeInstance = 70123490
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

## Import the template

[templates/zbx_smartreader_cap_snmpv3.yaml](../templates/zbx_smartreader_cap_snmpv3.yaml) is the same
template `provision.py` builds, exported from Zabbix 7.0, for a Zabbix you run yourself. It needs Zabbix 7.0
or later.

1. *Data collection → Templates → Import*, choose the file, keep the default rules. It creates the template
   group *Templates/SmartReader* if it is missing.
2. On the host that stands for the reader, add an **SNMP interface**:

   | Field | Value |
   |---|---|
   | IP address | The reader's address |
   | Port | `1161` |
   | SNMP version | SNMPv3 |
   | Security name | The agent's USM user (a `{$...}` host macro works) |
   | Security level | authPriv |
   | Authentication protocol, passphrase | As configured on the agent, for example SHA256 |
   | Privacy protocol, passphrase | As configured on the agent, for example AES128 |

3. Link **SmartReader CAP by SNMPv3 (experimental)** to the host.
4. **If the host also polls the reader's own agent** (SNMP v2c on port 161, as this lab's host does): Zabbix
   links every SNMP item of the template to the host's *main* SNMP interface. Set the SNMPv3 interface on
   each of the template's items on that host, or give the CAP a host of its own.
5. For the informs, the trap receiver needs the same USM user. With Zabbix's `zabbix-snmptraps` image,
   put a `createUser` line in `snmptrapd_custom.conf` in its persistent configuration directory, as
   `smartreader_snmpv3.py traps` does here.

Template macros:

| Macro | Default | Use |
|---|---|---|
| `{$SR.SNMP.ROOT}` | `1.3.6.1.4.1.8072.9999.9999.7` | Root of SmartReader's objects. Provisional |
| `{$SR.DISK.MAX}` | `85` | File system trigger, % |
| `{$SR.PENDING.MAX}` | `100` | MQTT backlog trigger, messages |
| `{$SR.TEMP.MARGIN}` | `5` | CPU temperature trigger: degrees below the limit |

When the final root is allocated, change `{$SR.SNMP.ROOT}`, and change the trap item's key too: its regular
expression spells the provisional root out.

Checked on 2026-10-13: the file imported into Zabbix 7.0.31 with 27 items, all enabled, and 10 triggers.
On a host pointed at the simulator, 26 of the 26 SNMP items collected a value.

## Checked on

| | |
|---|---|
| Date | 2026-10-13 |
| Reader | R700 Rev1, firmware 10.4.0 |
| CAP | SmartReader SNMPv3 test build |
| Zabbix | 7.0.31 |
| Results | All 26 SNMPv3 items supported over authPriv SHA-256 / AES-128, on the reader and on the simulator, and all 27 keys of the template collected in one run (16:25 UTC, [above](#item-keys-and-values-read-in-the-tests)). The CAP's INFORM was acknowledged and matched on the reader's host; the simulator's on its own host. *Requests with a wrong key* opened for requests with a wrong key. The reader's v2c items and traps worked as before. The published template imported and collected |

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
