# Troubleshooting — the 8 pitfalls

Each of these cost us hours. Learn from our pain.

## 1. Firewall: UDP, and only ever ADD rules

ZeroTier is UDP. A TCP rule does nothing. Worse: **editing** an existing cloud-security-group rule silently kills the original port. Always add new rules.

Probe from outside: `echo t | nc -u -w1 <server-ip> <port>` while tcpdump-ing on the server. Zero packets = firewall.

## 2. MTU black hole (cellular)

**Symptom**: ping works, latency looks fine, TCP handshakes complete — web pages spin forever.
**Cause**: default MTU 2800 > cellular path MTU (~1400). Large packets are silently dropped.
**Fix**: set network `mtu: 1300` and reconnect clients.
**Mnemonic**: *ping works + web dead = check MTU first.*

## 3. Controller cannot be a planet root

The 1.14.2 client will not send join requests to a peer whose role is PLANET. Keep the controller as LEAF; the moon introduces it. (We built a 3-root planet to "solve" this once — the join silently went nowhere.)

## 4. Hand-written member files don't authorize

Controller needs the member's `identity` field, which is only written when the device actually joins. Let it join (controller writes a skeleton with `authorized: false`), then flip the flag — via zt-admin, ideally.

## 5. "DIRECT but dead" after network changes

Hotel/office WiFi: session tables hold stale paths. Restart the ZeroTier service on **both** ends. (Android bonus: disable battery optimization or the app dies in the background.)

## 6. Controller DB layout (FileDB)

```
controller.d/network/<nwid>.json            # flat file, name exactly 21 chars
controller.d/network/<nwid>/member/<id>.json # 15 chars
```
Field is `"id"`, not `"nwid"`.

## 7. macOS: planet file swap needs a kickstart

```
sudo cp <file> "/Library/Application Support/ZeroTier/One/planet"
sudo launchctl kickstart -k system/com.zerotier.one
```

## 8. Docker image pulls behind GFW

`docker pull` from mainland China often times out. Recipe: pull on a machine with a proxy (or via a registry mirror), `docker save` → `scp` → `docker load`.
