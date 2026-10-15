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
| Data | CAP health the CAP already collects: CPU, memory, disk, CPU temperature, reader and CAP uptime, MQTT connection and backlog, process memory, CPU and threads, the agent's own request counters. Also the reader's RFID statistics: its RFID status, and an antenna table with each port's `show rfid stat` figures and SmartReader's settings for it |
| Notifications | SNMPv3 **INFORMs** to the lab's trap receiver, acknowledged by it |
| What Zabbix no longer needs | The CAP admin password and the reader root password: the HTTP and REST templates use them, this one uses a read-only SNMPv3 user |

The lab adds three things, all off unless `.env` turns them on:

- **A template, *SmartReader CAP by SNMPv3 (experimental)*,** with 32 items, an antenna discovery rule (23
  item prototypes and a trigger prototype per port), a trap item for SmartReader's informs and 13 triggers. Every SmartReader OID is written relative to the macro `{$SR.SNMP.ROOT}`, so the
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

For a real reader the CAP's admin page owns the user, the protocols and the passphrases, and the CAP never
returns a passphrase: `python smartreader_snmpv3.py credentials` copies everything else into `.env`, and the
two passphrases are the ones you typed or generated there ([part B](#b-monitor-a-reader-whose-cap-has-the-agent)).

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

   Expect 33 items plus 92 discovered antenna items, none unsupported, and the interface `172.31.67.20` available. In the web UI the
   host is *SmartReader SNMPv3 simulator*.

4. Send an INFORM and watch it arrive:

   ```bash
   python smartreader_snmpv3.py inform --sim
   python status.py --host smartreader-snmpv3-sim
   ```

   *Trap: SmartReader SNMPv3 notification* gets a value, and *SmartReader SNMPv3 notification received* opens
   as a problem for 15 minutes.

## B. Monitor a reader whose CAP has the agent

1. On the CAP's admin page, open **SNMP Monitoring**. Enable the agent, set a user, and generate or type both
   passphrases. Copy them before you apply: the CAP never shows them again.
2. Put the two passphrases into `.env` as `SR_SNMPV3_AUTH_PASSPHRASE` and `SR_SNMPV3_PRIV_PASSPHRASE`, then
   copy the rest of the settings from the CAP:

   ```bash
   python smartreader_snmpv3.py credentials   # sets SR_SNMPV3_ENABLED=1, the port, the user and both protocols
   ```

   `credentials` reads the CAP's `GET /api/snmp/status`, which answers to the CAP admin login and never
   returns a passphrase. It leaves the two passphrase keys in `.env` as they are, and says so when they are
   still empty. It stops with a message if the CAP has no SNMPv3 user yet. On a CAP without that endpoint, set
   the `SR_SNMPV3_*` values by hand to the user you configured and set `SR_SNMPV3_ENABLED=1`.

   With SHA-256 or stronger authentication the agent's privacy key is long enough for AES-192 and AES-256, so
   Net-SNMP's plain (`AES-256`) and Cisco-style (`AES-256-C`) names both work.

3. **Let the trap receiver accept the informs, and check the agent from the lab:**

   ```bash
   python smartreader_snmpv3.py traps
   python smartreader_snmpv3.py check
   ```

4. **Build the Zabbix side:**

   ```bash
   python provision.py
   python status.py --wait
   ```

   The reader's host now has three interfaces: SNMP v2c on 161, the trap-only interface, and SNMPv3 on 1161.
   Its items are those of the four templates, none unsupported. A Zabbix host with two SNMP interfaces
   links every SNMP item to its main (v2c) one, so `provision.py` creates the SNMPv3 items disabled, moves
   them to the SNMPv3 interface, enables them there and asks for a first check.

5. **An INFORM from the CAP** (test build):

   ```bash
   python smartreader_snmpv3.py inform
   ```

   The CAP sends it with the user configured on its SNMP Monitoring page, so the lab passes only the trap
   receiver's address and port.

   On Docker Desktop it arrives from `172.31.67.1`, like the reader's v2c traps, so it lands on the
   trap-only interface. There *Trap: SmartReader SNMPv3 notification* matches it before *Trap: other* can.

## What the template collects

`{ROOT}` is `{$SR.SNMP.ROOT}`, provisionally `1.3.6.1.4.1.8072.9999.9999.7`. Every polled item uses the SNMPv3 interface on
port 1161. The template is also published for import: [templates/zbx_smartreader_cap_snmpv3.yaml](../templates/zbx_smartreader_cap_snmpv3.yaml)
(see [Import the template](#import-the-template)).

| Subtree | Holds |
|---|---|
| `{ROOT}.2` | CAP health |
| `{ROOT}.3` | The agent's counters |
| `{ROOT}.4` | A synthetic 25-row table the test build carries to size walks; not polled |
| `{ROOT}.5.1` | **Antenna table**, one row per port: `show rfid stat` figures and SmartReader's antenna settings |
| `{ROOT}.5.2` | The reader's RFID status and when its statistics were reset |
| `{ROOT}.5.3` | Age and outcome of the latest RFID statistics collection |

The RFID values come from the CAP's reader-status collector, which reads RShell `show rfid stat` every 60 s
while the agent runs. An SNMP request reads the collector's latest snapshot and never makes the CAP talk
to the reader.

### Item keys and values read in the tests

Every key was read over SNMPv3 in one run, on 2026-10-13 18:32:53 UTC:

- **R700:** the bench reader (R700 Rev1, firmware 10.4.0) running the SmartReader SNMPv3 test build
  (engine boots 3).
- **Simulator:** `smartreader-snmpv3-sim`, with synthetic values.

`snmp_type` and `agent_value_is` say what the agent answers. The `*_snmp` columns hold the raw answer from
Net-SNMP 5.9 (authPriv SHA-256 / AES-128). The `*_zabbix` columns hold the value Zabbix 7.0.31 stored after
`zabbix_preprocessing`, in `zabbix_units`. The two come from reads a few seconds apart, so values that move,
such as CPU or tag counts, differ between them. The reader's `sysDescr` ends in a build label, shown as `(…)`.

**Items** — 33 keys: the CAP's health, the agent, the RFID status, the antenna table's walk and the trap item.

```csv
key,item,oid,snmp_type,agent_value_is,zabbix_preprocessing,zabbix_units,r700_snmp,r700_zabbix,simulator_snmp,simulator_zabbix
sr3.agent.uptime,SNMPv3 agent uptime,1.3.6.1.2.1.1.3.0,Timeticks,hundredths of a second,multiply by 0.01,uptime,(131549) 0:21:55.49,1243.19,(104897) 0:17:28.97,975.63
sr3.sysdescr,SNMPv3 agent description,1.3.6.1.2.1.1.1.0,STRING,,,,SmartReader CAP 4.0.1.201 on R700 (…),SmartReader CAP 4.0.1.201 on R700 (…),"SmartReader SNMPv3 simulator (lab, synthetic values)","SmartReader SNMPv3 simulator (lab, synthetic values)"
sr3.sysobjectid,SNMPv3 agent object ID,1.3.6.1.2.1.1.2.0,OID,,,,.1.3.6.1.4.1.8072.9999.9999.7.1,NET-SNMP-MIB::netSnmpPlaypen.7.1,.1.3.6.1.4.1.8072.9999.9999.7.1,NET-SNMP-MIB::netSnmpPlaypen.7.1
sr3.engine.id,SNMPv3 engine ID,1.3.6.1.6.3.10.2.1.1.0,Hex-STRING,,,,80 00 65 1A 05 E3 EF CA 5F 21 07 4D 3E,80 00 65 1A 05 E3 EF CA 5F 21 07 4D 3E,80 00 1F 88 80 6D DE F3 4F 5D 75 CE 6A 00 00 00 00,80 00 1F 88 80 6D DE F3 4F 5D 75 CE 6A 00 00 00 00
sr3.engine.boots,SNMPv3 engine boots,1.3.6.1.6.3.10.2.1.2.0,INTEGER,,,,3,3,1,1
sr3.cpu,CAP process CPU,{ROOT}.2.1.0,Gauge32,percent x 100,multiply by 0.01,%,1333,20.06,3621,38.48
sr3.memory,CAP process memory,{ROOT}.2.2.0,Gauge32,MB,multiply by 1048576,B,190,199229440,176,185597952
sr3.disk.pused,CAP file system used,{ROOT}.2.3.0,Gauge32,percent x 100,multiply by 0.01,%,4395,43.95,2835,28.35
sr3.os.uptime,Reader OS uptime,{ROOT}.2.4.0,Gauge32,seconds,,uptime,1413,1343,78849,78775
sr3.app.uptime,CAP application uptime,{ROOT}.2.5.0,Gauge32,seconds,,uptime,1314,1244,533,460
sr3.cpu.temp,CPU temperature,{ROOT}.2.6.0,Gauge32,degrees C x 10,multiply by 0.1,°C,489,48.8,549,55
sr3.cpu.temp.max,CPU temperature limit,{ROOT}.2.7.0,Gauge32,degrees C x 10,multiply by 0.1,°C,800,80,1050,105
sr3.cpu.temp.peak,CPU temperature peak,{ROOT}.2.8.0,Gauge32,degrees C x 10,multiply by 0.1,°C,489,48.9,554,55.4
sr3.mqtt.connected,CAP connected to MQTT broker,{ROOT}.2.9.0,Gauge32,0 or 1,,,1,1,1,1
sr3.mqtt.pending,CAP MQTT messages pending,{ROOT}.2.10.0,Gauge32,messages,,,90,87,3,1
sr3.process.rss,CAP resident memory,{ROOT}.2.20.0,Gauge32,bytes,,B,198905856,199790592,202438635,202841554
sr3.process.cpu,"CAP CPU, % of one core",{ROOT}.2.21.0,Counter64,CPU milliseconds since start,"change per second, then multiply by 0.1",%,565179,43.1846,149579,27.9992
sr3.process.heap,CAP managed heap,{ROOT}.2.22.0,Gauge32,bytes,,B,53655352,59114604,92824169,88508667
sr3.process.threads,CAP threads,{ROOT}.2.23.0,Gauge32,threads,,,26,29,27,27
sr3.requests,SNMPv3 requests per second,{ROOT}.3.1.0,Counter32,,change per second,rps,1132,0.6705,267,0.5079
sr3.unknown.users,SNMPv3 unknown user names per second,{ROOT}.3.4.0,Counter32,,change per second,rps,0,0,0,0
sr3.wrong.digests,SNMPv3 wrong digests (authentication failures) per second,{ROOT}.3.6.0,Counter32,,change per second,rps,0,0,0,0
sr3.decryption.errors,SNMPv3 decryption errors per second,{ROOT}.3.7.0,Counter32,,change per second,rps,0,0,0,0
sr3.time.window,SNMPv3 requests outside the time window per second,{ROOT}.3.8.0,Counter32,,change per second,rps,0,0,0,0
sr3.rate.limited,SNMPv3 requests dropped by the rate limit per second,{ROOT}.3.11.0,Counter32,,change per second,rps,0,0,0,0
sr3.set.refused,SNMPv3 SET requests refused per second,{ROOT}.3.12.0,Counter32,,change per second,rps,0,0,0,0
sr3.reader.admin,Reader administrative status,{ROOT}.5.2.1.0,INTEGER,"1 enabled, 2 disabled, 3 other",,,1,1,1,1
sr3.reader.oper,Reader operational status,{ROOT}.5.2.2.0,INTEGER,"1 enabled, 2 disabled, 3 other",,,1,1,1,1
sr3.rfid.reset,RFID statistics since last reset,{ROOT}.5.2.3.0,Gauge32,seconds since the statistics were reset,,uptime,1298,1230,535,460
sr3.rfid.age,RFID statistics age,{ROOT}.5.3.1.0,Gauge32,seconds since collected,,s,46,41,54,40
sr3.rfid.collection,RFID statistics collection,{ROOT}.5.3.2.0,INTEGER,"0 not collected, 1 ok, 2 timeout, 3 paused, 4 error",,,1,1,1,1
sr3.antennas.walk,Antenna table (walk),walk[{ROOT}.5.1.1],walk,the antenna table,,,92 objects (below),text; feeds the antenna discovery,92 objects,text; feeds the antenna discovery
"snmptrap[""netSnmpPlaypen\.7\.0\.|8072\.9999\.9999\.7\.0\.""]",Trap: SmartReader SNMPv3 notification,{ROOT}.0.* (INFORM),SNMPv3 INFORM,notification,,,snmpTrapOID.0 = NET-SNMP-MIB::netSnmpPlaypen.7.0.1,trap text (below),snmpTrapOID.0 = NET-SNMP-MIB::netSnmpPlaypen.7.0.1,trap text (below)
```

**Antenna table** — low-level discovery turns each row of `{ROOT}.5.1.1` into 23 items. `{N}` is the
port, which becomes `{#SNMPINDEX}` in the item keys. `source` is the `show rfid stat` key, or the
SmartReader setting the column comes from. The examples are port 1, the port with an antenna on both agents.

```csv
column,oid,source,snmp_type,agent_value_is,zabbix_key,zabbix_preprocessing,zabbix_units,r700_port1_snmp,r700_port1_zabbix,simulator_port1_snmp,simulator_port1_zabbix
1,{ROOT}.5.1.1.1.{N},antenna port,Integer32,port number,{#SNMPINDEX},,,1,(index),1,(index)
2,{ROOT}.5.1.1.2.{N},Antenna{N}AdministrativeStatus,INTEGER,"1 enabled, 2 disabled, 3 other",sr3.antenna.admin[{#SNMPINDEX}],,,1,1,1,1
3,{ROOT}.5.1.1.3.{N},Antenna{N}OperationalStatus,INTEGER,"1 enabled, 2 disabled, 3 other",sr3.antenna.oper[{#SNMPINDEX}],,,1,1,1,1
4,{ROOT}.5.1.1.4.{N},Antenna{N}LastPowerLevel,Integer32,cdBm,sr3.antenna.power[{#SNMPINDEX}],multiply by 0.01,dBm,1550,15.5,1550,15.5
5,{ROOT}.5.1.1.5.{N},Antenna{N}LastNoiseLevel,Integer32,as the reader reports it,sr3.antenna.noise[{#SNMPINDEX}],,,0,0,0,0
6,{ROOT}.5.1.1.6.{N},Antenna{N}EnergizedTime,Counter64,milliseconds,sr3.antenna.energized[{#SNMPINDEX}],multiply by 0.001,uptime,628431,594.115,503558,470.328
7,{ROOT}.5.1.1.7.{N},Antenna{N}UniqueInventoryCount,Gauge32,tags,sr3.antenna.unique[{#SNMPINDEX}],,,4,4,4,4
8,{ROOT}.5.1.1.8.{N},Antenna{N}TotalInventoryCount,Counter64,tag inventories,sr3.antenna.inventory[{#SNMPINDEX}],,,165063,156047,125890,117583
8,{ROOT}.5.1.1.8.{N},Antenna{N}TotalInventoryCount,Counter64,tag inventories,sr3.antenna.inventory.rate[{#SNMPINDEX}],change per second,tags/s,165063,173.5768,125890,245.0037
9,{ROOT}.5.1.1.9.{N},Antenna{N}FailedInventoryCount,Counter64,count,sr3.antenna.inventory.failed[{#SNMPINDEX}],,,0,0,0,0
10,{ROOT}.5.1.1.10.{N},Antenna{N}ReadCount,Counter64,count,sr3.antenna.reads[{#SNMPINDEX}],,,0,0,0,0
11,{ROOT}.5.1.1.11.{N},Antenna{N}FailedReadCount,Counter64,count,sr3.antenna.reads.failed[{#SNMPINDEX}],,,0,0,0,0
12,{ROOT}.5.1.1.12.{N},Antenna{N}WriteCount,Counter64,count,sr3.antenna.writes[{#SNMPINDEX}],,,0,0,0,0
13,{ROOT}.5.1.1.13.{N},Antenna{N}FailedWriteCount,Counter64,count,sr3.antenna.writes.failed[{#SNMPINDEX}],,,0,0,0,0
14,{ROOT}.5.1.1.14.{N},Antenna{N}LockCount,Counter64,count,sr3.antenna.locks[{#SNMPINDEX}],,,0,0,0,0
15,{ROOT}.5.1.1.15.{N},Antenna{N}FailedLockCount,Counter64,count,sr3.antenna.locks.failed[{#SNMPINDEX}],,,0,0,0,0
16,{ROOT}.5.1.1.16.{N},Antenna{N}KillCount,Counter64,count,sr3.antenna.kills[{#SNMPINDEX}],,,0,0,0,0
17,{ROOT}.5.1.1.17.{N},Antenna{N}FailedKillCount,Counter64,count,sr3.antenna.kills.failed[{#SNMPINDEX}],,,0,0,0,0
18,{ROOT}.5.1.1.18.{N},Antenna{N}EraseCount,Counter64,count,sr3.antenna.erases[{#SNMPINDEX}],,,0,0,0,0
19,{ROOT}.5.1.1.19.{N},Antenna{N}FailedEraseCount,Counter64,count,sr3.antenna.erases.failed[{#SNMPINDEX}],,,0,0,0,0
20,{ROOT}.5.1.1.20.{N},antennaStates (SmartReader setting),INTEGER,"1 yes, 2 no",sr3.antenna.enabled[{#SNMPINDEX}],,,1,1,1,1
21,{ROOT}.5.1.1.21.{N},antennaZones (SmartReader setting),OCTET STRING,zone name,sr3.antenna.zone[{#SNMPINDEX}],,,Cabinet,Cabinet,Dock door 1,Dock door 1
22,{ROOT}.5.1.1.22.{N},transmitPower (SmartReader setting),Integer32,cdBm,sr3.antenna.txpower[{#SNMPINDEX}],multiply by 0.01,dBm,1550,15.5,1550,15.5
23,{ROOT}.5.1.1.23.{N},receiveSensitivity (SmartReader setting),Integer32,dBm,sr3.antenna.rxsensitivity[{#SNMPINDEX}],,dBm,-80,-80,-92,-92
```

Every key was collected on both hosts: 32 SNMP items and 92 discovered antenna items (23 for each of
4 ports) with a value and none unsupported, plus the trap item with an INFORM from each side.

On the bench reader all four ports are enabled in SmartReader's settings (column 20 is 1 on every port), but
only port 1 has an antenna, so the reader reports port 1 as enabled and ports 2 to 4 as disabled (column 3 is
1, 2, 2, 2). The antenna trigger therefore opens for ports 2 to 4 there: that mismatch between the settings
and the hardware is what it is for. On the simulator only port 1 is enabled, and the trigger stays quiet.

### Raw SNMP answers

A walk of `{ROOT}` on each agent in the same run, with Net-SNMP 5.9 over authPriv from the lab's network.
Values under `{ROOT}.2` are scaled integers (see `agent_value_is`): `{ROOT}.2.1.0` is percent × 100 and
`{ROOT}.2.6.0` is °C × 10.

R700, `{ROOT}.2` (health) and `{ROOT}.3` (agent counters since the CAP started):

```text
.1.3.6.1.4.1.8072.9999.9999.7.2.1.0 = Gauge32: 1482
.1.3.6.1.4.1.8072.9999.9999.7.2.2.0 = Gauge32: 192
.1.3.6.1.4.1.8072.9999.9999.7.2.3.0 = Gauge32: 4395
.1.3.6.1.4.1.8072.9999.9999.7.2.4.0 = Gauge32: 1383
.1.3.6.1.4.1.8072.9999.9999.7.2.5.0 = Gauge32: 1284
.1.3.6.1.4.1.8072.9999.9999.7.2.6.0 = Gauge32: 489
.1.3.6.1.4.1.8072.9999.9999.7.2.7.0 = Gauge32: 800
.1.3.6.1.4.1.8072.9999.9999.7.2.8.0 = Gauge32: 489
.1.3.6.1.4.1.8072.9999.9999.7.2.9.0 = Gauge32: 1
.1.3.6.1.4.1.8072.9999.9999.7.2.10.0 = Gauge32: 54
.1.3.6.1.4.1.8072.9999.9999.7.2.20.0 = Gauge32: 201363456
.1.3.6.1.4.1.8072.9999.9999.7.2.21.0 = Counter64: 557809
.1.3.6.1.4.1.8072.9999.9999.7.2.22.0 = Gauge32: 59510452
.1.3.6.1.4.1.8072.9999.9999.7.2.23.0 = Gauge32: 28
.1.3.6.1.4.1.8072.9999.9999.7.3.1.0 = Counter32: 896
.1.3.6.1.4.1.8072.9999.9999.7.3.2.0 = Counter32: 896
.1.3.6.1.4.1.8072.9999.9999.7.3.3.0 = Counter32: 378
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
.1.3.6.1.4.1.8072.9999.9999.7.3.16.0 = Counter32: 1
.1.3.6.1.4.1.8072.9999.9999.7.3.17.0 = Counter32: 1
.1.3.6.1.4.1.8072.9999.9999.7.3.18.0 = Counter32: 0
```

The counters in `{ROOT}.3`, in order: 1 requests received · 2 responses sent · 3 discovery requests ·
4 unknown user names · 5 unknown engine IDs · 6 wrong digests · 7 decryption errors · 8 outside the time
window · 9 unsupported security levels · 10 SNMPv1/v2c messages dropped · 11 dropped by the rate limit ·
12 SET requests refused · 13 malformed messages · 14 responses too big · 15 other errors · 16 INFORMs sent ·
17 INFORMs acknowledged · 18 INFORMs failed. The template polls 1, 4, 6, 7, 8, 11 and 12.

R700, `{ROOT}.5` (antenna table, then the reader's RFID status and the collection). The rows run column by
column: column 2 for ports 1 to 4, then column 3, and so on.

```text
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.1.1 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.1.2 = INTEGER: 2
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.1.3 = INTEGER: 3
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.1.4 = INTEGER: 4
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.2.1 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.2.2 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.2.3 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.2.4 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.3.1 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.3.2 = INTEGER: 2
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.3.3 = INTEGER: 2
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.3.4 = INTEGER: 2
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.4.1 = INTEGER: 1550
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.4.2 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.4.3 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.4.4 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.5.1 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.5.2 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.5.3 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.5.4 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.6.1 = Counter64: 628431
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.6.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.6.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.6.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.7.1 = Gauge32: 4
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.7.2 = Gauge32: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.7.3 = Gauge32: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.7.4 = Gauge32: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.8.1 = Counter64: 165063
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.8.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.8.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.8.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.9.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.9.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.9.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.9.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.10.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.10.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.10.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.10.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.11.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.11.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.11.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.11.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.12.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.12.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.12.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.12.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.13.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.13.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.13.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.13.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.14.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.14.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.14.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.14.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.15.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.15.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.15.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.15.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.16.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.16.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.16.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.16.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.17.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.17.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.17.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.17.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.18.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.18.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.18.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.18.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.19.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.19.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.19.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.19.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.20.1 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.20.2 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.20.3 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.20.4 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.21.1 = STRING: "Cabinet"
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.21.2 = STRING: "Cabinet"
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.21.3 = STRING: "Cabinet"
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.21.4 = STRING: "Cabinet"
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.22.1 = INTEGER: 1550
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.22.2 = INTEGER: 1500
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.22.3 = INTEGER: 1500
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.22.4 = INTEGER: 1500
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.23.1 = INTEGER: -80
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.23.2 = INTEGER: -80
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.23.3 = INTEGER: -80
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.23.4 = INTEGER: -80
.1.3.6.1.4.1.8072.9999.9999.7.5.2.1.0 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.2.2.0 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.2.3.0 = Gauge32: 1298
.1.3.6.1.4.1.8072.9999.9999.7.5.3.1.0 = Gauge32: 23
.1.3.6.1.4.1.8072.9999.9999.7.5.3.2.0 = INTEGER: 1
```

Simulator, `{ROOT}.2`, `{ROOT}.3` and `{ROOT}.5`:

```text
.1.3.6.1.4.1.8072.9999.9999.7.2.1.0 = Gauge32: 3604
.1.3.6.1.4.1.8072.9999.9999.7.2.2.0 = Gauge32: 176
.1.3.6.1.4.1.8072.9999.9999.7.2.3.0 = Gauge32: 2835
.1.3.6.1.4.1.8072.9999.9999.7.2.4.0 = Gauge32: 78828
.1.3.6.1.4.1.8072.9999.9999.7.2.5.0 = Gauge32: 513
.1.3.6.1.4.1.8072.9999.9999.7.2.6.0 = Gauge32: 550
.1.3.6.1.4.1.8072.9999.9999.7.2.7.0 = Gauge32: 1050
.1.3.6.1.4.1.8072.9999.9999.7.2.8.0 = Gauge32: 554
.1.3.6.1.4.1.8072.9999.9999.7.2.9.0 = Gauge32: 1
.1.3.6.1.4.1.8072.9999.9999.7.2.10.0 = Gauge32: 0
.1.3.6.1.4.1.8072.9999.9999.7.2.20.0 = Gauge32: 208093154
.1.3.6.1.4.1.8072.9999.9999.7.2.21.0 = Counter64: 143853
.1.3.6.1.4.1.8072.9999.9999.7.2.22.0 = Gauge32: 93669705
.1.3.6.1.4.1.8072.9999.9999.7.2.23.0 = Gauge32: 27
.1.3.6.1.4.1.8072.9999.9999.7.3.1.0 = Counter32: 256
.1.3.6.1.4.1.8072.9999.9999.7.3.2.0 = Counter32: 256
.1.3.6.1.4.1.8072.9999.9999.7.3.3.0 = Counter32: 1
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
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.1.1 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.1.2 = INTEGER: 2
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.1.3 = INTEGER: 3
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.1.4 = INTEGER: 4
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.2.1 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.2.2 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.2.3 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.2.4 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.3.1 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.3.2 = INTEGER: 2
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.3.3 = INTEGER: 2
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.3.4 = INTEGER: 2
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.4.1 = INTEGER: 1550
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.4.2 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.4.3 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.4.4 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.5.1 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.5.2 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.5.3 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.5.4 = INTEGER: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.6.1 = Counter64: 503558
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.6.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.6.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.6.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.7.1 = Gauge32: 4
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.7.2 = Gauge32: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.7.3 = Gauge32: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.7.4 = Gauge32: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.8.1 = Counter64: 125890
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.8.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.8.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.8.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.9.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.9.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.9.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.9.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.10.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.10.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.10.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.10.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.11.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.11.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.11.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.11.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.12.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.12.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.12.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.12.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.13.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.13.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.13.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.13.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.14.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.14.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.14.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.14.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.15.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.15.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.15.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.15.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.16.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.16.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.16.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.16.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.17.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.17.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.17.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.17.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.18.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.18.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.18.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.18.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.19.1 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.19.2 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.19.3 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.19.4 = Counter64: 0
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.20.1 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.20.2 = INTEGER: 2
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.20.3 = INTEGER: 2
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.20.4 = INTEGER: 2
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.21.1 = STRING: "Dock door 1"
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.21.2 = STRING: "Unused"
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.21.3 = STRING: "Unused"
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.21.4 = STRING: "Unused"
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.22.1 = INTEGER: 1550
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.22.2 = INTEGER: 1550
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.22.3 = INTEGER: 1550
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.22.4 = INTEGER: 1550
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.23.1 = INTEGER: -92
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.23.2 = INTEGER: -92
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.23.3 = INTEGER: -92
.1.3.6.1.4.1.8072.9999.9999.7.5.1.1.23.4 = INTEGER: -92
.1.3.6.1.4.1.8072.9999.9999.7.5.2.1.0 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.2.2.0 = INTEGER: 1
.1.3.6.1.4.1.8072.9999.9999.7.5.2.3.0 = Gauge32: 513
.1.3.6.1.4.1.8072.9999.9999.7.5.3.1.0 = Gauge32: 33
.1.3.6.1.4.1.8072.9999.9999.7.5.3.2.0 = INTEGER: 1
```

SmartReader's agent keeps its engine ID and boots across CAP restarts and reboots: on the first test build
the ID stayed the same while boots climbed from 1 to 7. A new CAP install starts with a new engine ID
(`80 00 65 1A 05 E3 EF CA 5F 21 07 4D 3E` after installing the build with the antenna table), because the
installer does not carry the agent's state over yet. The simulator gets a new engine ID each time its
container is recreated, because it keeps no state.

### What an INFORM looks like

As the trap item stores it, from the same run.

From the CAP on the R700. Docker Desktop shows the lab network's gateway as the source, so Zabbix matches it
to the reader's trap-only interface. The reader's host name is masked. The test build's notification is a
test: its last varbind is a fixed `1`, not a reading.

```text
2026-10-13T18:32:33+0000 UDP: [172.31.67.1]:48116->[172.31.67.3]:1162
DISMAN-EVENT-MIB::sysUpTimeInstance = 136538
SNMPv2-MIB::snmpTrapOID.0 = NET-SNMP-MIB::netSnmpPlaypen.7.0.1
SNMPv2-MIB::sysName.0 = impinj-xx-xx-xx
NET-SNMP-MIB::netSnmpPlaypen.7.2.4.0 = 1
```

From the simulator. It arrives from the container's own address, so it lands on the simulator's host:

```text
2026-10-13T18:32:33+0000 UDP: [172.31.67.20]:42926->[172.31.67.3]:1162
DISMAN-EVENT-MIB::sysUpTimeInstance = 70889304
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
| Reader RFID not operational | High |
| RFID statistics older than 5 minutes | Warning |
| The CAP cannot collect RFID statistics (no successful collection in 10 minutes) | Warning |
| *Prototype:* antenna enabled in SmartReader but not operational, one per discovered port | Average |

On the reader's host, the HTTP template raises its own MQTT and disk problems from `/metrics`, and the
native SNMP v2c template its own antenna and RFID problems from the EPCglobal MIB. The lab keeps them all so
you can compare them; a production setup would pick one source for each.

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

Checked on 2026-10-13: the file imported into Zabbix 7.0.31 with 33 items, all enabled, 13 triggers and the
antenna discovery rule (23 item prototypes, 1 trigger prototype). On a host pointed at the simulator, 32 of
the 32 SNMP items and 92 of the 92 discovered antenna items collected a value.

## Checked on

| | |
|---|---|
| Date | 2026-10-13 |
| Reader | R700 Rev1, firmware 10.4.0 |
| CAP | SmartReader SNMPv3 test build |
| Zabbix | 7.0.31 |
| Results | All SNMPv3 items supported over authPriv SHA-256 / AES-128, on the reader and on the simulator: the 33 keys of the template and the 92 discovered antenna items collected in one run (18:32 UTC, [above](#item-keys-and-values-read-in-the-tests)). The CAP's INFORM was acknowledged and matched on the reader's host; the simulator's on its own host. *Requests with a wrong key* opened for requests with a wrong key. The reader's v2c items and traps worked as before. The published template imported and collected, antenna discovery included |

An earlier run against the same agent (2026-10-09) also passed SHA-512 / AES-256 and SHA-384 / AES-192 from
Net-SNMP 5.9, and SHA-512 / AES-256 from a Zabbix 7.0 interface.

## Notes

- **A wrong key often shows up as a decryption error, not an authentication failure.** The test build's
  agent decrypts a request before it checks the digest, so a request with both keys wrong counts as a
  decryption error. The wrong-key trigger watches both counters.
- **The first values of the hourly items** (description, object ID, engine ID) come from the check that
  `provision.py` requests. Without it, an item enabled after creation is first polled somewhere inside its
  hour.
- **AES-192 and AES-256** have two key-extension variants in the SNMP world (Net-SNMP's `AES-256` and the
  Cisco-style `AES-256-C`). With SHA-256 or stronger the localized key is long enough that they coincide, so
  either name works and no particular pairing is needed.
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
| `check` says `Unknown user name` | The user in `.env` is not the agent's | Set `SR_SNMPV3_USER`, or run `credentials` to copy it from the CAP |
| `credentials` says the CAP has no SNMPv3 user | The agent is not set up on the CAP's SNMP Monitoring page | Enable it there, set the user and both passphrases, apply, then run `credentials` again |
| `Authentication failure` or `Decryption error` | Wrong passphrase or protocol | Check the `SR_SNMPV3_*` values against the CAP's SNMP Monitoring page. The CAP cannot show the passphrases again: if you lost them, generate new ones there |
| `Timeout` from `check` (reader) | The CAP has no SNMPv3 agent, or UDP 1161 is blocked on the way | A released CAP does not have the agent yet; use the simulator |
| SNMPv3 items show values of the reader's own agent | The items were polled on the v2c interface | Re-run `provision.py`; it moves and enables them |
| INFORMs time out | snmptrapd does not know the user | `python smartreader_snmpv3.py traps` after every change of the `SR_SNMPV3_*` user |
| The simulator exits at start | `SR_SNMPV3_USER` or a passphrase is empty | Fill them in `.env`, then `docker compose --profile snmpv3-sim up -d` |
