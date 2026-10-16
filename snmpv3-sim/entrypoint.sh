#!/bin/sh
# Builds snmpd.conf from the SR_SNMPV3_* settings and runs Net-SNMP's agent in the foreground.
set -eu

: "${SR_SNMPV3_USER:?set SR_SNMPV3_USER in .env}"
: "${SR_SNMPV3_AUTH_PASSPHRASE:?set SR_SNMPV3_AUTH_PASSPHRASE in .env}"
: "${SR_SNMPV3_PRIV_PASSPHRASE:?set SR_SNMPV3_PRIV_PASSPHRASE in .env}"
PORT="${SR_SNMPV3_PORT:-1161}"
ROOT="${SR_SNMP_ROOT:-.1.3.6.1.4.1.8072.9999.9999.7}"

# Zabbix spells the protocols SHA256 / AES128; Net-SNMP wants SHA-256 / AES.
case "${SR_SNMPV3_AUTH_PROTOCOL:-SHA256}" in
    SHA1) AUTH=SHA ;; SHA224) AUTH=SHA-224 ;; SHA256) AUTH=SHA-256 ;; SHA384) AUTH=SHA-384 ;; SHA512) AUTH=SHA-512 ;;
    *) echo "unsupported SR_SNMPV3_AUTH_PROTOCOL" >&2; exit 1 ;;
esac
case "${SR_SNMPV3_PRIV_PROTOCOL:-AES128}" in
    AES128) PRIV=AES ;; AES192) PRIV=AES-192 ;; AES256) PRIV=AES-256 ;;
    *) echo "unsupported SR_SNMPV3_PRIV_PROTOCOL" >&2; exit 1 ;;
esac

mkdir -p /var/lib/net-snmp
cat > /etc/snmp/snmpd.conf <<EOF
agentaddress udp:${PORT},udp6:${PORT}
createUser ${SR_SNMPV3_USER} ${AUTH} "${SR_SNMPV3_AUTH_PASSPHRASE}" ${PRIV} "${SR_SNMPV3_PRIV_PASSPHRASE}"
rouser ${SR_SNMPV3_USER} priv
sysobjectid ${ROOT}.1.1
sysdescr SmartReader SNMPv3 simulator (lab, synthetic values)
syscontact SmartReader Zabbix lab
syslocation lab
pass_persist ${ROOT} /usr/bin/python3 /usr/local/bin/smartreader_sim.py
EOF

# An INFORM to the lab's trap receiver at start, like an agent coming up. snmpd sends coldStart to it.
if [ -n "${SR_SNMPV3_INFORM_TARGET:-}" ]; then
    cat >> /etc/snmp/snmpd.conf <<EOF
trapsess -Ci -v 3 -l authPriv -u ${SR_SNMPV3_USER} -a ${AUTH} -A "${SR_SNMPV3_AUTH_PASSPHRASE}" -x ${PRIV} -X "${SR_SNMPV3_PRIV_PASSPHRASE}" ${SR_SNMPV3_INFORM_TARGET}
EOF
fi

exec /usr/sbin/snmpd -f -Lo -C -c /etc/snmp/snmpd.conf
