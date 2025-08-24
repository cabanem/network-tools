## Collect logs bundle
### Files
> `debug_drv.txt`, `DriverInfo.txt`, `IpConfig.txt`, `LogonUi.txt`, `NetStat.txt`, `NicConfig.txt`, `NicDetails.txt`, `pan_gp_event.txt`, `pan_gp_hrpt.txt`, `PanGPA.txt`, `PanGPA.log.old`, `PanGpHip.txt`, `PanGpHipMp.txt`, `PanGPMsi.txt`, `PanGPS.txt`, `PanPlapProvider.txt`, `ProcessInfo.txt`, `regval.txt`, `RoutePrint.txt`, `ServiceInfo.txt`, `setupapi.app.txt`, `setupapi.dev.txt`, `SystemInfo.txt`, `TcpipBind.txt`

### Signal Map
#### High-value and time-series files
- `PanGPS.txt`
  - service log
  - Represents the core sequence: portal -> auth -> gateway select -> tunnel up/down, reconnects, errors
- `PanGPA.txt` / `PanGPA.log.old`
  - UI/agent log
  - Contains data for:
    - user actions
    - portal selection
    - SSO/SAML browser hand-off
    - MFA prompts
    - UX errors
- `PanPlapProvider.txt`
  - Pre-logon (PLAP) flow before Windows logon
- `PanGpHip.txt` / `PanGpHipMp.txt`
  - Information regarding posture-policy failures
  - HIP collection, HIP match results
- `pan_gp_event.txt`
  - Windows event log extract for GP
  - Includes stable timestamps
  - Error text can vary from other files  
#### Snapshot and diagnostic files (for context)
- `IpConfig.txt` &rarr; Client receipt confirmaiton. Contains tunnel adapter (PANGP) addresses, DNS servers, suffix list
- `RoutePrint.txt` &rarr; routing table; split-tunnel vs full-tunnel clues
- `NetStat.txt` &rarr; live connnections to poral/gateway IP:port, can corroborate handshake/connectivity
- `NicConfig.txt`, `NicDetails.txt`, `TcpipBind.txt` &rarr; adapter settings/binding order; look for unusual metrics or disabled bindings
- `ServiceInfo.txt` &rarr; whether PanGPS service is running/healthy
- `regval.txt` &rarr; GP client registry (portal list, saved state). Treat as sensitive; only parse needed keys
- `SystemInfo.txt`, `ProcessInfo.txt` &rarr; OS build, AV/EDR, processes that might interfere (proxies, filters)
- `debug_drv.txt`
- `DriverInfo.txt`, `setupapi.*`, `PanGPMsi.txt`, `LogonUI.txt` &rarr; Driver install/PLAP/installer detail. Outside of core triage. Useful for debugging adapter/driver issues. 
- `pan_gp_hrpt.txt` &rarr; vendor tool dependent; when present, typically a hearbeat/status or periodic report. Parse timestamps + status keywords; treat as weak corroborating source.

## Event taxonomy
- Normalized event types
  - `portal_connect_start` / `success` / `fail`
  - `auth_start` / `success` / `fail`(includes SAML/OAuth/MFA timeouts)
  - `tls_handshake_start` / `success` / `fail` (certificate errors)
  - `gateway_select_start` / `success` / `fail`
  - `hip_start` / `success` / `fail`
  - `tunnel_up` / `tunnel_down` / `reconnect`
  - `dns_set` / `route_add` / `route_remove` / `interface_up` / `interface_down`
  - `error` (unclassified)
    
- Failure reasons
>`auth`, `cert`, `network`, `hip`, `config`, `service`, `unknown`
 
## Concrete extraction targets per file
1. PanGPS.txt
   - Timestamps severity, component, message text
   - Portal FQDN; gateway name/IP; assigned tunnel IP; DNS set; routes added/removed
   - Key strings to match
     - "connecting to portal (?P<portal>\S+)"
     - "gateway (?P<gateway>\S+) selected" or "selected gateway (?P<gateway>\S+)"
     - "authentication (succeeded|failed)", "invalid credential|SAML|timeout"
     - "certificate (verification|validation) failed|untrusted|expired|hostname"
     - "tls handshake (start|failed|success)"
     - "tunnel is up|tunnel is down|reconnecting"
     - "assign ip (?P<client_ip>\d+\.\d+\.\d+\.\d+)" (IPv6 too)
     - "set dns server|add route|delete route"
2. PanGPA.txt
   - User-initiated actions, portal chosen, embedded browser/SAML redirects, MFA prompts/denials
   - Often clarifies _why_ auth failed

3. PanGpHip.txt
   - HIP collect start/end; HIP match pass/fail; failing object names/policies
     
4. pan_gp_event.txt
   - Timestamps and event text; use as a secondary truth when PanGPS timestamps look odd.
6. Snapshots/miscellaneous
   - IpConfig/RoutePrint/ServiceInfo/regval
   - PANGP adapter address/DNS/suffix; default routes; PanGPS service running; default portal from registry.
## Expected outputs
- Per attempt/session (CSV + JSON):
  - Start/end, outcome, durations per phase (portal/auth/gateway/tunnel).
  - Portal, gateway, assigned IP, reconnect count.
  - On failure: reason (auth/cert/...) + raw evidence string.
- Rollup summary (console):
  - Attempts, success rate, p50/p95 time‑to‑connect, top N failures (with counts), top gateways.

## Edge cases
- Timestamp drift/timezon
- Rotation
- PLAP vs user logon
- HIP noise
