# MIB files (optional)

Zabbix polls the reader by numeric OID, so the lab works with this folder empty. MIB files only make
values and trap names readable, for example `IMPINJ-ROOT-REG-MIB::impR700` instead of
`.1.3.6.1.4.1.25882.2.1.5`.

The Impinj MIBs are not redistributed here. To use them, download the Octane documentation bundle for
your firmware from the Impinj support portal and copy `IMPINJ-ROOT-REG-MIB` into this folder. The bundle
may name it `.mib` or `.txt`; Net-SNMP loads either. The Zabbix server and the trap receiver both read it
from `/var/lib/zabbix/mibs`. Restart them after adding a file:

```bash
docker compose restart zabbix-server zabbix-snmptraps
```
