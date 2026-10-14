# Deployment

`server/setup.sh` automates everything; this page explains each step.

## 0. Requirements

- One VPS (1 vCPU / 1 GB RAM is plenty — the stack uses <20 MB)
- Ubuntu/Debian, root access
- **UDP 9993 open** in your cloud firewall (add a new rule; never edit an existing one)

## 1. Controller (ZeroTier 1.14.2 in docker)

```bash
docker run -d --name zt-controller --restart unless-stopped \
  -p 9993:9993 -p 9993:9993/udp \
  -v /opt/zt-ctrl:/var/lib/zerotier-one \
  keynetworks/ztncui:latest
```

Mainland-China pull failures: use a registry mirror, or `docker save` from a proxied machine and `docker load`.

## 2. Create your network

The network ID must start with the controller's 10-char address (first 10 bytes of `identity.public`), followed by 6 hex chars of your choice:

```bash
CTRL=$(docker exec zt-controller head -c10 /var/lib/zerotier-one/identity.public)
NWID="${CTRL}e5a7c9"   # any 6 hex chars
docker exec zt-controller sh -c "cat > /var/lib/zerotier-one/controller.d/network/${NWID}.json" <<JSON
{"id":"$NWID","nwid":"$NWID","objtype":"network","name":"homelab","private":true,
 "enableBroadcast":true,"mtu":1300,"v4AssignMode":{"zt":true},
 "ipAssignmentPools":[{"network":"10.222.0.0/24","start":"10.222.0.10","end":"10.222.0.100"}],
 "routes":[{"target":"10.222.0.0/24","via":null}],
 "rules":[{"type":"ACTION_ACCEPT"}],
 "creationTime":1791000000000,"lastModified":1791000000000}
JSON
docker restart zt-controller
```

Notes: **mtu 1300** (cellular survival — pitfall #2). Flat file, 21-char name (pitfall #6).

## 3. Moon (same process)

```bash
# generate a moon definition pointing at your public IP
docker exec zt-controller sh -c 'cd /var/lib/zerotier-one && zerotier-idtool initmoon identity.public > /tmp/m.json'
# edit /tmp/m.json → roots[0].stableEndpoints = ["<PUBLIC_IP>/9993"]
docker exec zt-controller sh -c 'cd /var/lib/zerotier-one && zerotier-idtool genmoon /tmp/m.json && mkdir -p moons.d && cp 000000*.moon moons.d/'
docker restart zt-controller
```

Distribute the `.moon` file to clients; they `orbit` it (see README).

## 4. zt-admin (web panel)

```bash
sudo systemctl enable --now zt-admin   # installed by setup.sh
# or manually:
ZT_NETWORK_ID=<nwid> python3 server/zt-admin.py
```

Access via SSH tunnel (do not expose it publicly without adding auth):

```bash
ssh -L 3444:127.0.0.1:3444 your-server
# open http://127.0.0.1:3444
```

## 5. Add devices

Desktop: `sudo zerotier-cli orbit <moon-id> <moon-id> && sudo zerotier-cli join <nwid>`
Android: ZerotierFix → Orbit → import `.moon` → add network
Then authorize in zt-admin.
