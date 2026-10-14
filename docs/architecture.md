# Architecture

## Why one box is enough

ZeroTier has two server-side roles that matter for self-hosting:

| Role | Job | Analogy |
|---|---|---|
| **moon** (root server) | Helps peers find each other; relays traffic when NAT hole-punching fails | Introducer / matchmaker |
| **controller** | Defines networks, issues and verifies member credentials | Doorman |

They are **two switches on the same process**, not two programs. A ZeroTier 1.14.2 instance can be both at once.

```
Client A ──WHOIS──> moon ──"B is at 1.2.3.4:9993"──> A
   A ──────────── direct / relayed ──────────────> B
   A ──join request──> controller ──config + cert──> A
```

## Version story (why 1.14.2)

- ZeroTier 1.16+ moved the controller into a non-free package. The official apt/deb binaries no longer include it.
- 1.14.2 is the last release with a freely redistributable controller.
- This project runs 1.14.2 inside a container (`keynetworks/ztncui`) which bundles it with a legacy web UI (we replace the UI with `zt-admin`).

## The addressing chain (debug this first when joins fail)

```
device join → WHOIS to a root → does the root know the controller?
```

The controller must orbit the moon (or be the same process as it) for the WHOIS answer to exist. Single-box deployments get this for free: the controller IS the root.

## Why the client fork (app/)

- Official ZeroTier mobile apps cannot import a custom moon (no root on Android; impossible on iOS).
- [kaaass/ZerotierFix](https://github.com/kaaass/ZerotierFix) added moon import; our fork adds:
  - **Per-moon enable switch** — toggle a moon on/off without deleting/re-importing it
  - **Moon file as custom planet** — for networks where even the official planet list is unreachable
