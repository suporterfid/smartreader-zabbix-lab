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

`{ROOT}` is `{$SR.SNMP.ROOT}`.

| Items | OIDs | Notes |
|---|---|---|
| Agent uptime, description, object ID | SNMPv2-MIB `system` | `sysUpTime` is the agent's uptime, by definition |
| Engine ID, engine boots | SNMP-FRAMEWORK-MIB `snmpEngine` | A boots change means the agent restarted |
| CAP CPU, memory, file system, CPU temperature (current, limit, peak) | `{ROOT}.2.1–2.8` | Scaled integers; the template converts them to %, bytes and °C |
| Reader OS uptime, CAP uptime | `{ROOT}.2.4`, `{ROOT}.2.5` | Reboot and restart triggers use these |
| MQTT connected, messages pending | `{ROOT}.2.9`, `{ROOT}.2.10` | |
| CAP resident memory, CPU (% of one core), managed heap, threads | `{ROOT}.2.20–2.23` | |
| Requests, unknown users, wrong digests, decryption errors, time-window misses, rate-limited, refused SETs | `{ROOT}.3.*` | As rates |
| SmartReader notifications | INFORMs under `{ROOT}.0` | One trap item for all of them |

Triggers:

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
