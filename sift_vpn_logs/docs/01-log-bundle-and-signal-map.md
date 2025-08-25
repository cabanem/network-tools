# GlobalProtect Client Log Bundle — Signal Map & Extraction Guide

**Audience:** engineers and support analysts triaging GlobalProtect client issues.  
**Scope:** explains what’s inside the **Collect Logs** bundle and how to extract the useful bits quickly.

---

## 1) What’s in the bundle (at a glance)

> Typical bundle contents:
>
> `debug_drv.txt`, `DriverInfo.txt`, `IpConfig.txt`, `LogonUi.txt`, `NetStat.txt`,  
> `NicConfig.txt`, `NicDetails.txt`, `pan_gp_event.txt`, `pan_gp_hrpt.txt`,  
> `PanGPA.txt`, `PanGPA.log.old`, `PanGpHip.txt`, `PanGpHipMp.txt`, `PanGPMsi.txt`,  
> `PanGPS.txt`, `PanPlapProvider.txt`, `ProcessInfo.txt`, `regval.txt`,  
> `RoutePrint.txt`, `ServiceInfo.txt`, `setupapi.app.txt`, `setupapi.dev.txt`,  
> `SystemInfo.txt`, `TcpipBind.txt`

### High‑value, time‑series logs (primary signal)

- **`PanGPS.txt` — Service log**  
  Core sequence: **portal → auth → gateway select → tunnel up/down**, reconnects, errors.

- **`PanGPA.txt` / `PanGPA.log.old` — Agent/UI log**  
  User actions, portal selection, SSO/SAML browser hand‑off, MFA prompts, UX errors.

- **`PanPlapProvider.txt` — Pre‑logon (PLAP)**  
  Connection attempts before Windows logon if pre‑logon is enabled.

- **`PanGpHip.txt` / `PanGpHipMp.txt` — HIP posture**  
  HIP collection and HIP match results; explains posture‑policy failures.

- **`pan_gp_event.txt` — Windows Event Log extract for GP**  
  Often clean timestamps; sometimes clearer phrasing of the same errors.

### Snapshot/diagnostic logs (context)

- **`IpConfig.txt`** — PANGP adapter addresses, DNS servers, suffix list (confirms what the client received).  
- **`RoutePrint.txt`** — Routing table; **split‑tunnel vs full‑tunnel** clues (default routes, metrics).  
- **`NetStat.txt`** — Live connections to portal/gateway IP:port (443/4501); corroborates handshake/connectivity.  
- **`NicConfig.txt`, `NicDetails.txt`, `TcpipBind.txt`** — Adapter settings/binding order; spot unusual metrics or disabled bindings.  
- **`ServiceInfo.txt`** — Whether the PanGPS service is running/healthy.  
- **`regval.txt`** — Client registry (portal list, saved state). **Sensitive**: parse only keys you need.  
- **`SystemInfo.txt`, `ProcessInfo.txt`** — OS build, AV/EDR, and processes that may interfere (proxies, filters).  
- **`debug_drv.txt`, `DriverInfo.txt`, `setupapi.*`, `PanGPMsi.txt`, `LogonUi.txt`** — Driver install, PLAP, installer details. Usually outside core triage unless adapter/driver issues are suspected.  
- **`pan_gp_hrpt.txt`** — Vendor‑tool dependent heartbeat/status. Treat as weak corroborating signal: parse timestamps + status keywords.

---

## 2) Where to look for answers (signal map)

**Most questions are answered by `PanGPS.txt`** (service view).  
Use `PanGPA*.txt` when you need **user context** (SAML/MFA/UX).  
Use **snapshots** to confirm what the system looks like at collection time.

| Question | Best source(s) |
|---|---|
| Did the user connect? When? | `PanGPS.txt` |
| Which portal/gateway? | `PanGPS.txt`; sometimes `PanGPA*.txt` |
| Why did it fail? | `PanGPS.txt`, `PanGPA*.txt`; verify with `pan_gp_event.txt` |
| How long did it take? | `PanGPS.txt` (phase timestamps) |
| Was it stable? | `PanGPS.txt` (reconnects, tunnel up/down) |
| What IP/DNS/routes were assigned? | `IpConfig.txt`, `RoutePrint.txt`; corroborate with `PanGPS.txt` |
| Posture failures (HIP)? | `PanGpHip*.txt` |

---

## 3) Concrete extraction targets (per file)

### 3.1 `PanGPS.txt` (must‑parse)
- **Fields:** timestamp, severity, component (if any), message text.
- **Entities:** portal FQDN, gateway name/IP, assigned tunnel IP, DNS servers, routes added/removed.
- **Match keys (examples):**
  - `connecting to portal (?P<portal>\S+)`
  - `gateway (?P<gateway>\S+) selected` or `selected gateway (?P<gateway>\S+)`
  - `authentication (succeeded|failed)`; `invalid credential|SAML|timeout`
  - `certificate (verification|validation) failed|untrusted|expired|hostname`
  - `tls handshake (start|failed|success)`
  - `tunnel is up|tunnel is down|reconnecting`
  - `assign ip (?P<client_ip>\d+\.\d+\.\d+\.\d+)` (capture IPv6 too)
  - `set dns server|add route|delete route`

### 3.2 `PanGPA*.txt` (agent/UI)
- User‑initiated actions, portal chosen, embedded browser/SAML redirects, MFA prompts/denials.  
- Often clarifies **why** authentication failed (user canceled vs. MFA denied vs. timeout).

### 3.3 `PanGpHip*.txt`
- HIP collect start/end, HIP match pass/fail; capture first failing object/policy name.

### 3.4 `pan_gp_event.txt`
- Timestamps + succinct error text. Use as **secondary truth** when `PanGPS.txt` timestamps look odd.

### 3.5 Snapshots (`IpConfig`, `RoutePrint`, `ServiceInfo`, `regval`)
- PANGP adapter IP/DNS/suffix; presence of default routes; PanGPS service state; default portal from registry.

---

## 4) Event taxonomy (reference)

> **Authoritative taxonomy lives in** `02-functional-spec-and-design.md#event-taxonomy`.  
> Parsers should normalize raw lines into these event types and reasons.

- **Event types:**  
  `portal_connect_start|portal_connect_success|portal_connect_fail|auth_start|auth_success|auth_fail|tls_handshake_start|tls_handshake_success|tls_handshake_fail|gateway_select_success|gateway_select_fail|tunnel_up|tunnel_down|reconnect|net_change|error`

- **Failure reasons:**  
  `auth|cert|network|hip|config|service|unknown`

---

## 5) Edge cases & gotchas

- **Timestamp drift / timezone:** regional formats vary; prefer stable parsers and allow user‑override for `--since/--until`.  
- **Rotation:** watch for `PanGPA.log.old` and occasionally rotated `PanGPS.txt.N`.  
- **PLAP vs user logon:** pre‑logon flows appear in `PanPlapProvider.txt`.  
- **HIP verbosity:** keep `hip_*` events summarized (first failing object + policy).

