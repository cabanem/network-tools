## 1 - Purpose 

1. Did the user connect? For each attempt, when did it start/end? was it a success or failure?
2. To which portal/gateway?
3. Why did it fail?
4. How stable is the session?
5. How long did it take?
6. What changed on the endpoint?
7. What was the most common outcome?

## 2 - Inputs and scope

1. Primary files
   - PanGPS (service) logs
   - PanGPA/UI logs (for user-action content)
2. Log Sets
   - Single file, rotated sequence, or zipped bundle
3. Platforms
   - Windows/MacOS/Linux client logs
   - Don't hardcode paths - accept paths/dirs as input
4. Sizes
   - Handle tens to hundreds of MB via streaming
   - Avoid full in-memory reads
  
## 3 - Functional requirements 
### Ingestion
- Accept `--input` paths (file, directory, `.zip`)
- Auto-discover rotated logs in a directory and sort by timestamp/sequence
- Transparently read compressed files (`.zip`, `.gz`, `.bz2`)
- Handle mixed encodings (UTF-8 as default; fall back to cp1252) and long lines

### Parsing and normalization
- Timestamp parsing
  - Robust parser
  - Multiple formats, optional milliseconds
  - Local -> UTC normalization
  - `--tz` override
- Field detection
  - Extract severity, component/module, thread/PID, message
- Event classification
  - `portal_connect_start`/`success`/`fail`
  - `gateway_select`/`start`/`fail`
  - `auth_start`/`start`/`fail`
  - `tls_handshake_start`/`start`/`fail`
  - `hip_start`/`start`/`fail`
  - `tunnel_up`/`tunnel_down`/`reconnect`
  - `dns_set`/`route_add`/`route_remove`/`interface_up`/`interface_down`
  - `error` (not classified)
- Entity extraction
  - Heuristic
  - username, portal FQDN, gateway, IPs (client/portal/gate), region, cert CN/issuer, error codes
- Session stitching
  - Group related lines into connection attempts and sessions using time gaps + keywords
  - Compute durations, outcomes

### Filtering (CLI)
- `--since/--until`
- `--user`
- `--portal`
- `--gateway`
- `--event-type`
- `--severity`
- `--contains "text"`

### Summaries and metrics
- Pre-attempt summary
  - Start/end
  - Outcome
  - Durations/phase
  - Reason on failure
- Aggregates
  - Success rate, attempts per hour/day
  - Median/95p time-to-connect
  - Top N failure reasons (w/examples)
  - Top gateways
  - Reconnect frequency, most common triggers

### Output and UX
- Human readable console output (brief as default, detailed with flag `--verbose`)
- Export options
  - `--export json`
  - `--export csv`
  - `--report html` (optional, nice-to-have)
- Redaction controls
  - `--redact user, ip, host` to hash sensitive fields

### Performancea
- Stream processing; 0(1) memory w.r.t. file size
- Graceful handling of malformed lines; count, show lines 'skipped'
- Deterministic output (stable sort, timestamps)

## 3 - Acceptance criteria
- Given a directory of PanGPS logs, one command should:
  - List all connection attempts with timestamps, outcomes
  - Explains failures with normalized reason and exact source message
  - Show a timing breakdown (portal -> auth -> gateway -> tunnel up)
  - Produce a CSV/JSON artifact suitable for ticket attachments, business intelligence
- Running with `--since 2025-08-01` prints:
  - Success rate %
  - Top 5 errors
  - p50/p95 time-to-connect
  - Top gateways

## 4 - Internal data model
### Event (flat)
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
  "code": "-121"               // if present
}
```

### Session (derived)
```json
{
  "session_id": "derived-uuid",
  "user": "jdoe",
  "portal": "vpn.example.com",
  "gateway": "gw-us-west",
  "start_ts": "...",
  "end_ts": "...",
  "outcome": "success|fail",
  "fail_reason": "auth|cert|network|hip|config|unknown",
  "fail_detail": "TLS handshake failure: cert expired",
  "phase_durations_ms": { "portal": 850, "auth": 1200, "gateway": 700, "tunnel": 300 },
  "reconnects": 2,
  "client_ip": "10.8.12.34"
}
```

## 6 - Extensible pattern library
Keep message patterns out of code in a small YAML/JSON "signature" file. 
Each entry should contain: 
- match (substring or regex)
- etype (normalized event type)
- component
- optional extractors (named capturing groups)

### Example
```yaml
- match: "(?i)connecting to portal (?P<portal>\\S+)"
  etype: "portal_connect_start"
  component: "portal"

- match: "(?i)portal (?P<portal>\\S+) certificate (?:verification|validation) failed"
  etype: "tls_handshake_fail"
  component: "tls"
  extract: ["portal"]
  reason: "cert"

- match: "(?i)gateway (?P<gateway>\\S+) selected"
  etype: "gateway_select_success"
  component: "gateway"
  extract: ["gateway"]

- match: "(?i)tunnel is up"
  etype: "tunnel_up"
  component: "service"

- match: "(?i)authentication failed|invalid credentials"
  etype: "auth_fail"
  component: "auth"
  reason: "auth"
```

## 7 - CLI design
```bash
gp-sift \
  --input /path/to/logs \
  --since "2025-08-01 00:00" --until "2025-08-09 23:59" \
  --user jdoe --portal vpn.exampleportal.com \
  --summary --top-errors 10 \
  --export json:/tmp/gp_events.json csv:/tmp/gp_sessions.csv
  --redact user,ip --tz UTC
```
### Common flags
- `--input`
- `--since/--until`
- `--event-type`
- `--contains`
- `--summary`

## 8 - Minimum viable product vs nice-to-have
### MVP
- Stream files, parse timestamps, simple substring patterns for core events
- Session stitching by inactivity gap (e.g., 60s b/t attempts)
- Summaries (success rate/top n errors), CSV report
- Redaction (hash usernames, IPs)

### Nice-to-have
- HTML report with collapsible timelines.
- Regex extractors for codes (e.g., TLS, OS errors).
- Correlate PanGPS (service) with PanGPA (UI) for user actions.
- Enrichment: reverse DNS of gateways, geo of public IPs (offline DB).
- Unit tests with canned logs and golden outputs.
- Structured logging to NDJSON for SIEM ingestion.


## 9 - Implementation sketch
### Python
- Core libs
  - `argparse`, `pathlib`, `io`, `gzip`/`zipfile`
  - `re`
  - `json`, `csv`
  - `datetime`, `dateutil`
- UX
  - `pandas` for optional csv/html rendering
- Algorithm flow
  1. Resolve input paths -> iterator of (filename, line) streams
  2. For each line:
     - Parse timestamp, severity, message
     - Classify vs pattern library
     - Emit event
  3. Sessionizer
     - Maintain small sliding window; start session on `portal_connect_start` or after idle gap
     - Close session on `tunnel_down` or next attempt to start.
     - Compute duration
  4. Aggregators and exports

## 10 - Failure reason taxonomy
- `auth` - bad creds, MFA timeout/denied, SAML/OAuth failure
- `cert` -- untrusted/expired/hostname mismatch/client cert issues
- `network` - DNS failure, port unreachable, TCP timeout, proxy
- `hip` - posture checks failed/not compliant
- `config` - no available gateway, license, portal config error, region mismatch
- `service` - PanGPS service down, driver/interface errors
- `unknown` - everything else

## 11 - Privacy, security
- Default to masking usernames, device names, public IPs unless `--no-redact`
- Never write raw logs to report unless requested
- Avoid uploading logs anywhere; process locally
