# SmartReader SNMPv3 simulator: Net-SNMP's agent answering for SmartReader's experimental SNMPv3 objects.
FROM alpine:3.20
RUN apk add --no-cache net-snmp net-snmp-tools python3
COPY smartreader_sim.py /usr/local/bin/smartreader_sim.py
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/smartreader_sim.py
EXPOSE 1161/udp
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
