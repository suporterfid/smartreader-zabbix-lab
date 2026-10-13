# snmptrapd configuration (generated)

This folder is mounted into the `zabbix-snmptraps` container as its persistent configuration directory
(`/var/lib/zabbix/snmptrapd_config`).

- `snmptrapd_custom.conf` holds the SNMPv3 user SmartReader's informs are sent with. It is written by
  `python smartreader_snmpv3.py traps` from the `SR_SNMPV3_*` settings in `.env`, and holds passphrases,
  so git ignores it.
- `snmptrapd.conf` is written by snmptrapd itself: its engine ID and the localized keys of the users.

Delete both and run `python smartreader_snmpv3.py traps` again to start over.
