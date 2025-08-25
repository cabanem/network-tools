# Functional Spec & Design -- `vpn-log-sift`

**Goal:** quickly answer connection, failure, and timing questions from GlobalProtect client bundles.  
**Outcomes:** human‑readable summaries and machine‑readable exports (JSON/CSV).

---

## 1) Purpose & outcomes

1. Did the user connect (start/end, success/failure)?
2. Which portal/gateway, and what IP/DNS/routes were assigned?
3. Why did it fail (normalized reason + source evidence)?
4. How stable was the session (reconnects, tunnel up/down)?
5. How long did it take (phase timings)?
6. What changed on the endpoint (DNS/routes/interface toggles)?
7. What’s most common across attempts (success rate, top errors/gateways)?

---

## 2) Inputs & scope

- **Inputs:** GP client bundles (`.zip`), single files, or rotated sequences.
- **Primary logs:** `PanGPS.txt` (service), `PanGPA*.txt` (agent/UI).  
  Secondary: `PanPlapProvider.txt`, `PanGpHip*.txt`, `pan_gp_event.txt`.  
  Snapshots: `IpConfig.txt`, `RoutePrint.txt`, `ServiceInfo.txt`, `regval.txt`.
- **Platforms:** Windows/macOS/Linux bundles (do not hardcode paths).
- **Sizes:** tens to hundreds of MB — stream; avoid full in‑memory reads.

---

## 3) Functional requirements

### 3.1 Ingestion
- Accept `--input` (file, directory) or `--zip` (bundle).
- Auto‑discover rotated logs; sort by timestamp/sequence.
- Read compressed files (`.zip`, `.gz`, `.bz2`) where applicable.
- Handle mixed encodings (UTF‑8 default; fall back to cp1252/latin‑1).
- Tolerate very long lines.

### 3.2 Parsing & normalization
- **Timestamps:** robust parsing, optional milliseconds; local → UTC normalization with `--tz` override.
- **Fields:** severity, component/module (best‑effort), thread/PID when present, raw message.
- **Classification:** map raw messages to normalized **event types** (below).
- **Entity extraction:** username, portal FQDN, gateway, IPs (client/portal/gateway), region, cert CN/issuer, error codes.
- **Session stitching:** group lines into connection attempts via start markers + idle gaps; compute phase durations and outcomes.

### 3.3 Filtering (CLI)
- `--since/--until`, `--user`, `--portal`, `--gateway`, `--event-type`, `--severity`, `--contains "text"`.

### 3.4 Summaries & metrics
- **Per attempt:** start/end, outcome, phase durations, failure reason + evidence.
- **Aggregates:** success rate; attempts per hour/day; median/95p time‑to‑connect; top failure reasons (with examples); top gateways; reconnect frequency & triggers.

### 3.5 Output & UX
- Human‑readable console output; `--verbose` for per‑event timelines.
- Exports:
  - `--export-events` → JSON array or NDJSON (line‑delimited) of **events**
  - `--export-sessions` → CSV of **sessions**
  - *(optional)* `--report html` for a compact dashboard.

### 3.6 Performance & reliability
- Stream processing; O(1) memory relative to file size.
- Gracefully handle malformed lines; count and report “lines skipped”.
- Deterministic output (stable sort & timestamps).

---

## 4) Event taxonomy

### 4.1 Event types
- portal_connect_start
- portal_connect_success
- portal_connect_fail
- auth_start
- auth_success
- auth_fail
- tls_handshake_start
- tls_handshake_success
- tls_handshake_fail
- gateway_select_success
- gateway_select_fail
- tunnel_up
- tunnel_down
- reconnect
- net_change # DNS set, route add/remove, interface up/down
- error # unclassified

### 4.2 Failure reasons
auth | cert | network | hip | config | service | unknown

---

## 5) Data model

### 5.1 Event (flat)
```json
{
  "ts": "2025-08-21T13:09:01.234Z",
  "severity": "INFO|WARN|ERROR",
  "component": "portal|gateway|hip|network|tls|dns|route|service|ui|unknown",
  "etype": "portal_connect_start|...|error",
  "msg": "raw log line message",
  "user": "jdoe",
  "portal": "vpn.example.com",
  "gateway": "gw-us-west",
  "client_ip": "10.8.12.34",
  "portal_ip": "203.0.113.10",
  "code": "-121"
}
```
### 5.2 Session (derived)
```json
{
  "session_id": "derived-uuid",
  "user": "jdoe",
  "portal": "vpn.example.com",
  "gateway": "gw-us-west",
  "start_ts": "...",
  "end_ts": "...",
  "outcome": "success|fail|unknown",
  "fail_reason": "auth|cert|network|hip|config|service|unknown",
  "fail_detail": "TLS handshake failure: cert expired",
  "phase_durations_ms": { "portal": 850, "auth": 1200, "gateway": 700, "tunnel": 2300 },
  "reconnects": 2,
  "client_ip": "10.8.12.34"
}
```
## 6) CLI design (examples)
```
# Basic: summarize attempts & print last sessions
python vpn_log_sift.py --zip ./GP_Collect_Logs.zip

# Time window + exports
python vpn_log_sift.py --zip ./GP_Collect_Logs.zip \
  --since "2025-08-01 00:00" --until "2025-08-24 23:59" \
  --export-events ./gp_events.ndjson \
  --export-sessions ./gp_sessions.csv

# With privacy redaction
python vpn_log_sift.py --zip ./logs.zip --redact --export-sessions ./sessions.csv
Common flags: --since/--until, --user, --portal, --gateway, --event-type, --severity, --contains.
```

## 7) MVP vs. nice‑to‑have
### MVP
- Streamed parsing, simple robust timestamp detection.
- Substring/regex patterns for core events; session stitching via idle gap.
- Summaries (success rate, top errors) + CSV/JSON exports.
- Redaction for usernames/IPs/hostnames.
### Nice‑to‑have
- HTML report (sessions table, failure chart, simple timeline).
- Rich extractors (TLS/OS error codes; assigned IPv6; cert CN/issuer).
- Tight correlation between PanGPS and PanGPA (thread IDs).
- External patterns.yaml so non‑coders can update signatures.
- Unit tests with golden logs; NDJSON for SIEM pipelines.

## 8) Implementation sketch
- Core libs - argparse, pathlib, io, zipfile/gzip, re, json, csv, datetime, dateutil |
- UX - optional rich/pandas for nicer console/HTML (not required). |
- Flow:
  - Resolve inputs → (file, line) stream iterator.
  - Parse lines → timestamps, severity, message → classify into events.
  - Sessionize via start markers + idle gap → compute phase durations/outcomes.
  - Aggregate stats; write summaries and exports |

## 9) Privacy & security
- Default to masking usernames, device names, public IPs unless --no-redact.
- Never include raw logs in reports unless explicitly requested.
- Entirely offline; no network calls.

## 10) Acceptance criteria
- From a directory or zip of PanGPS logs, a single command:
  - Lists all connection attempts with timestamps and outcomes.
  - Explains failures with a normalized reason and the original evidence line.
  - Shows a simple timing breakdown (portal → auth → gateway → tunnel).
  - Produces CSV/JSON artifacts ready for tickets or BI tools.
- With `--since 2025-08-01`:
  - Prints success rate, top 5 errors, p50/p95 time‑to‑connect, and top gateways.
