# zt-homelab 🌐

**Self-hosted ZeroTier in one box** — your own virtual LAN with zero dependency on ZeroTier's official cloud. One cheap VPS runs everything: moon (rendezvous/relay) + network controller + a clean web admin panel.

完全自主的内网穿透方案：一台最便宜的云服务器，跑起你的整个虚拟局域网。

```
┌─────────── Your VPS (1C1G is enough) ───────────┐
│  ZeroTier 1.14.2 (docker)                        │
│    ├─ moon / root server   "帮你找到对方"          │
│    └─ network controller   "管理成员资格"          │
│  zt-admin (python, zero-dep)                     │
│    └─ web authorization panel  "一键授权"          │
└──────────────────────────────────────────────────┘
        ▲                    ▲                  ▲
     📱 phone            💻 laptop         🖥️ NAS ...
   (ZerotierFix app)   (official client)   (any client)
```

## Why

- ZeroTier's official planet/roots are overseas — slow or throttled in some networks (especially cellular)
- Official controller outages lock you out entirely (this actually happened — member certs couldn't renew)
- ZeroTier 1.16+ removed the controller from the free package; 1.14.2 is the last free version with it

This project ships all three pieces that make you **fully self-hosted**.

## Quick Start

```bash
git clone https://github.com/<you>/zt-homelab.git
cd zt-homelab/server
sudo bash setup.sh
```

The script prints your network ID, moon endpoint and admin panel URL when done.

**Cloud firewall**: open **UDP 9993** (ZeroTier is UDP — a TCP rule does nothing, this is the #1 gotcha).

## Components

| Path | What | License |
|---|---|---|
| `app/` | ZerotierFix v5 — Android client fork with **per-moon enable switch** + **use a moon file as custom planet** | GPL-2.0 (upstream: [kaaass/ZerotierFix](https://github.com/kaaass/ZerotierFix)) |
| `server/setup.sh` | One-box deployment: controller + moon + admin, one command | MIT |
| `server/zt-admin.py` | Zero-dependency web panel: list members, one-click authorize/deauthorize/rename/kick | MIT |
| `docs/` | Architecture, deployment deep-dive, troubleshooting | CC-BY-4.0 |

## Client setup

**Desktop** (has ZeroTier installed):

```bash
sudo zerotier-cli orbit <moon-id> <moon-id>   # e.g. 0123456789 0123456789
sudo zerotier-cli join <network-id>
# then authorize in web panel
```

**Android**: install the `app/` build (ZerotierFix v5) —
import the `.moon` file via menu → Orbit → ➕ → Import from file; then add the network.

**Restricted networks** (cellular / hotel WiFi): enable "Custom Planet" in ZerotierFix settings and import the same `.moon` file — all root traffic goes through your server.

## Hard-won lessons (see docs/troubleshooting.md)

1. **UDP, not TCP** in your firewall rules. "Editing" a rule kills the old port — always add new.
2. **MTU 1300**, not the default 2800 — cellular silently drops large packets (the classic "ping works, web pages spin forever" trap).
3. Controller **cannot** be a planet root at the same time (1.14.2 client refuses to join) — keep it as LEAF + moon does the introducing.
4. Hand-written member JSON files lack the `identity` field — let the device join first, controller generates the skeleton, then flip `authorized: true`.
5. ZT "DIRECT but no traffic" after changing networks = stale session cache — restart the service on **both** ends.

## Docs

- [Architecture](docs/architecture.md) — why one box is enough
- [Deployment](docs/deployment.md) — step by step with details
- [Troubleshooting](docs/troubleshooting.md) — the 8 pitfalls above, expanded
- [Custom client build](docs/client-build.md) — building & signing the Android app

## License

- `app/` — **GPL-2.0**, inherited from [kaaass/ZerotierFix](https://github.com/kaaass/ZerotierFix). Embedded ZeroTier core is under its own license (BSL 1.1 → Apache 2.0 for 1.14.x), see `app/externals/core/LICENSE.txt`.
- `server/` — **MIT**
- `docs/` — CC-BY-4.0

Non-commercial use as-is; see each LICENSE file.
