# vpn\_log\_sift.py

A small, purpose‑built utility to **analyze GlobalProtect (PanGP/PanGPS) client log bundles** and produce clear answers about connection attempts, failures, timings, and assigned tunnel details.

> **Scope:** This script is optimized for the **GlobalProtect “Collect Logs” .zip** produced on Windows/macOS clients. It focuses on the *service* and *agent* logs (PanGPS/PanGPA) and emits per‑attempt/session summaries plus machine‑readable exports (JSON/CSV).

---

## Table of contents

* [What problems this solves](#what-problems-this-solves)
* [What inputs it expects](#what-inputs-it-expects)
* [Installation](#installation)
* [Quick start](#quick-start)
* [CLI usage](#cli-usage)
* [Outputs](#outputs)

  * [Console summary](#console-summary)
  * [Events (JSON / NDJSON)](#events-json--ndjson)
  * [Sessions (CSV)](#sessions-csv)
* [How it works](#how-it-works)

  * [Event taxonomy](#event-taxonomy)
  * [Sessionization](#sessionization)
  * [Failure reasons](#failure-reasons)
* [Privacy & redaction](#privacy--redaction)
* [Customizing patterns](#customizing-patterns)
* [Performance notes](#performance-notes)
* [Troubleshooting](#troubleshooting)
* [File signal map](#file-signal-map)
* [Roadmap](#roadmap)
* [FAQ](#faq)
* [License](#license)

---

## What problems this solves

Given a GlobalProtect client log bundle, `vpn_log_sift.py` answers:

* **Did the user connect?** When did each attempt start/end; success/failure.
* **Where did they connect?** Portal FQDN, selected gateway, tunnel IP.
* **Why did it fail?** Normalized reasons (auth, cert, network, HIP, config, service, unknown) with the exact source message.
* **How long did it take?** Timing across phases (portal → auth → gateway → tunnel up).
* **How stable was it?** Reconnects and tunnel up/down transitions.

---

## What inputs it expects

Point the script at the **.zip** produced by *GlobalProtect → Help → Collect Logs* (or equivalent). A typical bundle includes many files; the high‑value ones are:

```
PanGPS.txt, PanGPA.txt, PanGPA.log.old, PanPlapProvider.txt,
PanGpHip.txt, PanGpHipMp.txt, pan_gp_event.txt, pan_gp_hrpt.txt,
IpConfig.txt, RoutePrint.txt, NetStat.txt, ServiceInfo.txt, regval.txt,
SystemInfo.txt, ProcessInfo.txt, NicConfig.txt, NicDetails.txt, TcpipBind.txt,
debug_drv.txt, DriverInfo.txt, LogonUi.txt, PanGPMsi.txt,
setupapi.app.txt, setupapi.dev.txt
```

> The MVP focuses primarily on **PanGPS.txt** (service) and, if present, **PanGPA.txt** / **PanGPA.log.old** (agent/UI). Other files are optionally referenced for context later.

---

## Installation

**Requirements**

* Python **3.9+**
* Optional but recommended: `python-dateutil` for robust timestamp parsing

```bash
# Option A: user environment
pip install python-dateutil

# Option B: virtualenv (recommended)
python -m venv .venv
. .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install python-dateutil
```

Place `vpn_log_sift.py` anywhere on your PATH or run it in place with `python`.

---

## Quick start

```bash
# Basic summary
python vpn_log_sift.py --zip /path/to/GP_Collect_Logs.zip

# Time window + exports (JSON events and CSV sessions)
python vpn_log_sift.py \
  --zip /path/to/GP_Collect_Logs.zip \
  --since "2025-08-01 00:00" --until "2025-08-24 23:59" \
  --export-events ./gp_events.json \
  --export-sessions ./gp_sessions.csv

# Same, but with privacy redaction (usernames/IPs/hostnames masked)
python vpn_log_sift.py --zip ./logs.zip --redact --export-sessions ./sessions.csv
```

Windows PowerShell examples:

```powershell
# If "py" launcher is installed
py -3 vpn_log_sift.py --zip "C:\Users\me\Desktop\GP_Collect_Logs.zip"
```

---

## CLI usage

```
python vpn_log_sift.py --zip <bundle.zip> [options]

Required:
  --zip PATH                Path to the GlobalProtect log bundle (.zip)

Filters:
  --since "YYYY-MM-DD HH:MM"   Include events on/after this time
  --until "YYYY-MM-DD HH:MM"   Exclude events at/after this time

Exports:
  --export-events PATH      Write events as JSON (.json) or NDJSON (.ndjson)
  --export-sessions PATH    Write sessions as CSV

Privacy:
  --redact                  Mask usernames, IPs, and hostnames in outputs
```

Notes:

* The timestamp parser is flexible (requires `python-dateutil` for best results).
* Paths with spaces should be quoted.

---

## Outputs

### Console summary

A compact rollup + the last few sessions:

```
Attempts: 42 | Success: 36 (85.7%) | Failures: 6
Median time-to-connect: 2.40s (n=33)
Top failure reasons: auth(3), cert(2), network(1)

--- Session #40 SUCCESS ---
Start: 2025-08-21 13:05:11  End: 2025-08-21 13:05:13  Duration: 2.30s
User: j***e  Portal: v*************m  Gateway: g**********t  Assigned IP: 1*********4
Reconnects: 0  Phase ms: {'portal': 850, 'auth': 1200, 'gateway': 700, 'tunnel': 2300}
```

### Events (JSON / NDJSON)

Each parsed **event** is a flat object:

```json
{
  "ts": "2025-08-21T13:09:01.234000",
  "severity": "INFO",
  "component": "portal",
  "etype": "portal_connect_start",
  "msg": "Connecting to portal vpn.example.com",
  "portal": "vpn.example.com",
  "gateway": null,
  "user": "jdoe",
  "client_ip": null,
  "reason": null,
  "src": "PanGPS.txt"
}
```

**Fields**

* `ts` — event timestamp (local parsed time; no timezone info attached)
* `severity` — INFO / WARN / ERROR (best‑effort)
* `component` — `portal|gateway|auth|tls|service|network|unknown` (best‑effort)
* `etype` — normalized event type (see [Event taxonomy](#event-taxonomy))
* `msg` — original log line (trimmed)
* `portal`, `gateway`, `user`, `client_ip` — heuristically extracted entities (may be null)
* `reason` — normalized failure reason if applicable (see [Failure reasons](#failure-reasons))
* `src` — source file within the zip (e.g., `PanGPS.txt`)

> Use `.ndjson` if you want line‑delimited JSON for SIEM ingestion.

### Sessions (CSV)

Each **session** aggregates a connection attempt:

| Column                                      | Meaning                                                                  |
| ------------------------------------------- | ------------------------------------------------------------------------ |
| `session_id`                                | Sequential ID within the run                                             |
| `start_ts` / `end_ts`                       | Attempt bounds                                                           |
| `outcome`                                   | `success` \| `fail` \| `unknown`                                         |
| `fail_reason`                               | One of: `auth`, `cert`, `network`, `hip`, `config`, `service`, `unknown` |
| `fail_detail`                               | First source message that explains the failure (trimmed)                 |
| `portal` / `gateway` / `user` / `client_ip` | Entities seen in this session                                            |
| `reconnects`                                | Count of reconnnect events within the attempt                            |
| `portal_ms`                                 | Portal phase duration (ms)                                               |
| `auth_ms`                                   | Authentication phase duration (ms)                                       |
| `gateway_ms`                                | Time until gateway selection (ms, best‑effort)                           |
| `tunnel_ms`                                 | Time from start to `tunnel_up` (ms)                                      |

---

## How it works

1. **Read the .zip** and locate high‑value files (`PanGPS.txt`, `PanGPA.txt`, `PanGPA.log.old`, `PanPlapProvider.txt`, `pan_gp_event.txt` if present).
2. **Parse lines** with a tolerant timestamp detector and a small library of regex **patterns**.
3. **Normalize to events** (e.g., `portal_connect_start`, `auth_success`, `tunnel_up`).
4. **Sessionize** by grouping events into attempts using **start markers** and **idle gaps**.
5. **Summarize** to console and optionally **export** events (JSON/NDJSON) and sessions (CSV).

### Event taxonomy

Normalized `etype` values (expandable):

* `portal_connect_start | portal_connect_success | portal_connect_fail`
* `auth_start | auth_success | auth_fail`
* `tls_handshake_start | tls_handshake_success | tls_handshake_fail`
* `gateway_select_success | gateway_select_fail`
* `tunnel_up | tunnel_down | reconnect`
* `net_change` (DNS set, route add/remove, interface up/down)
* `error` (unclassified catch‑all)

### Sessionization

* A session starts on `portal_connect_start`/`auth_start`/`tls_handshake_start`, or after an **idle gap** (default \~90s) between events.
* A session ends on `tunnel_up` (success), a clear failure (`*_fail`), or when a new attempt begins.
* Phase timers are derived from first/last matching events within the attempt.

### Failure reasons

A small, human‑readable taxonomy:

* `auth` — invalid credentials, SAML/OAuth errors, MFA deny/timeout
* `cert` — certificate validation failures, untrusted/expired/hostname mismatch
* `network` — timeouts, DNS failures, unreachable portal/gateway
* `hip` — Host Information Profile collection or policy non‑compliance
* `config` — no available gateway, license/config issues
* `service` — client service/driver issues
* `unknown` — anything else; original message preserved

---

## Privacy & redaction

* `--redact` masks usernames, IPs, and hostnames in console and export outputs (simple first/last‑char masking).
* The script performs **no network calls** and works entirely offline.
* Avoid sharing raw logs. If you must, prefer exporting **sessions.csv** (and optionally NDJSON events) with redaction enabled.

---

## Customizing patterns

The MVP embeds a small pattern set (regex list) that maps raw lines → normalized events and optionally extracts fields (`portal`, `gateway`, `user`, `client_ip`) or a `reason`.

To extend:

1. Open `vpn_log_sift.py` and locate the `PATTERNS` list.
2. Add a new tuple: `(re.compile(r'<your-regex>', re.I), ('<etype>','<component>','<reason|None>'))`.
3. For entity extraction that isn’t covered by the generic heuristics, use **named groups** (e.g., `(?P<gateway>\S+)`) in your regex, then update the extraction code if needed.

> Tip: keep the taxonomy small and meaningful. It’s better to capture one clear failure reason than many overlapping ones.

---

## Performance notes

* Typical GlobalProtect bundles are tens of MB; the script is fast enough on a laptop.
* **Encoding:** It tries `utf-8`, then `utf-16`, `cp1252`, and `latin-1`.
* **Memory:** The current reader loads each target file from the zip into memory once, then iterates lines. For unusually large files (>100 MB), converting to a true streaming text wrapper is straightforward but not implemented in the MVP.

---

## Troubleshooting

**“Attempts: 0” or no events found**

* Drop `--since/--until` to confirm your time window.
* Install `python-dateutil` so non‑standard timestamps parse cleanly.
* Ensure you’re pointing to the **.zip** (not an extracted folder).

**Wrong or missing portal/gateway/user/IP**

* Patterns are conservative. Add/adjust a regex in `PATTERNS` to match your organization’s exact log phrases.

**Too many sessions**

* Lower traffic can fragment attempts. Increase the idle gap in `sessionize()` (default \~90s) if needed.

**Outputs show sensitive info**

* Re‑run with `--redact` to mask usernames, IPs, and hostnames.

**PLAP / Pre‑logon flows**

* If you rely on pre‑logon, consider adding or enabling matches for `PanPlapProvider.txt` with the same taxonomy.

---

## File signal map

**Time‑series (primary)**

* `PanGPS.txt` — Core service sequence: portal → auth → gateway → tunnel up/down; reconnects; errors.
* `PanGPA.txt`, `PanGPA.log.old` — UI/agent context: user actions, SAML/MFA prompts, portal selection.
* `pan_gp_event.txt` — Windows Event Log extract for GP; timestamps are often clean.

**Context/snapshots (secondary)**

* `IpConfig.txt` — Tunnel adapter IP/DNS/suffix; confirms assigned client IP.
* `RoutePrint.txt` — Routing table at collection; shows full vs split‑tunnel posture.
* `NetStat.txt` — Live connections to portal/gateway (443/4501).
* `ServiceInfo.txt` — Service health.
* `regval.txt` — Portal list and client settings (sensitive).
* `SystemInfo.txt`, `ProcessInfo.txt`, `Nic*`, `TcpipBind.txt` — Environment and network stack details.
* `PanGpHip*.txt` — HIP collection and match results (posture failures).

---

## Roadmap

* [ ] Optional external `patterns.yaml` so non‑coders can update signatures without touching Python.
* [ ] HTML report (`--report html`) with a sessions table, failure counts, and a simple timeline.
* [ ] True streaming decode from zip for very large logs.
* [ ] Additional entity extractors (assigned IPv6, certificate CN/issuer).
* [ ] Correlate PanGPS and PanGPA entries more tightly (shared thread IDs when available).
* [ ] Unit tests with golden log snippets.

---

## FAQ

**Q: Does this tool upload logs anywhere?**
A: No. It’s fully offline. It reads your zip, parses, and writes local outputs.

**Q: Can it read extracted folders instead of the zip?**
A: Today it expects `--zip` explicitly. You can extend it to accept directories if needed.

**Q: Will it work on macOS logs?**
A: Yes, as long as the macOS “Collect Logs” bundle contains `PanGPS.txt`/`PanGPA.txt`. Patterns are case‑insensitive and fairly generic.

**Q: Can I feed the outputs into a SIEM?**
A: Use `--export-events <file>.ndjson` for line‑delimited JSON that’s SIEM‑friendly.

---

**Name & command**
You selected **`vpn_log_sift.py`** as the script name. If you later package it, a natural CLI alias would be `vpn-log-sift`.
