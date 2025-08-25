# SMTP Probe & Collector
## Brief
> Build a small, cross-platform 'SMTP probe and collector' that can (a) reproduce the exact SMTP/Gmail path used by AA bots, (b) collect the right diagnostics (DNS, TLS, SMTP transcript, timing, OS/network facts), (c) classify the failure with clear, actionable reasons, and (d) package in a single, shareable ZIP with a human summary and raw evidence.

> **Working name**: `smtp-probe` (consider, `mailtap`, `smtp-diag`, `botmail-diag`)

---
## Issues targeted 
- DNS problems
  - Timeouts
  - Wrong resolver
  - IPv6 AAAA pref w/o IPv6 reachability
- TCP reachability
  - Firewall / proxy blocking
  - Intermittent resets
- TLS handshake failures
  - Version, cipher mismatch
  - SNI problems
  - Cert chain distrust
  - Time skew
- SMTP policy responses from Gmail
  - Auth errors
  - Rate limiting/deferrals
  - Attachment scans
- STARTTLS path vs implicit TLS path differences
- Auth flows
  - XOAUTH2 tokens expired
  - App password invalid
  - MFA policy
  - "Less secure apps" disabled
- Transient / per-IP flakiness

## Tool Objectives
1. Capture the most relevant evidence automatically
2. Pin the failure to a small reason taxonomy
3. Reproduce the path AA used
4. Summarize clearly for humans
5. Secure, lightweight

## Architecture (10,000 feet)
The tool has 3 modes. The minimum viable product contains modes 1 and 2.

### Mode 1 - Active Probe
A standalone CLI that performs the same connection as AA task bot and captures diagnostics.
1. Resolve `smtp.gmail.com` via system DNS (log resolver IPs, TTL, A/AAAA answers)
2. Attempt connections to every resolved IP on the configured port (both IPv4/6 as applicable).
3. Record TCP timing (SYN time, connect time), TLS handshake details (ALPN, version, cipher, SNI, cert chain), and SMTP transcript up to and including STARTTLS (587) or full greeting on 465.
   - Log SMTP lines w/codes; mask any AUTH/credential payloads
4. Optionally attempt AUTH (PLAIN/XOAUTH2) if a `--auth-test` flag is set; otherwise stop before sending creds.
5. Repeat N times or across IPs to surface transients; compute success rate and distribution of failures.
6. Emit: machine-readable JSON and a human-readable `report.md` with raw transcripts.

### Mode 2 - Log Collector
When a failure occurs in real runs, the CLI gathers system and app logs relevant to the event:
- DNS snapshot (current resolvers, host file overrides)
- Network snapshot (default route, active interface, public egress IP, time skew)
- OS TLS/Schannel logs (Windows) or OpenSSL errors (Linux) if available
- Automation Anywhere run logs
- Package everything and probe the output into a single zip archive.

### Mode 3 - Local SMTP "tee" proxy
A tiny local SMTP listener (e.g., `localhost:2525`) that your bot temporarily pooints to. Forwards to Gmail while logging the transcript before encryption. **Caution: not recommended for production environment**

## Logging - Prioritized Capture List
Tune the signal-to-noise ratio in logging. 
1. DNS resolution details
   - Resolvers used, query time, A/AAAA answers, selected IP, round-robin order
   - Surfaces IPv6 "works in DNS, fails on network" issues, and per-IP flakiness
2. TCP reachability and timing
   - `connect_ms`, reset vs timeout, local socket bind/egress IP
   - Distinguishes firewall resets from path latency/timeouts.
3. TLS handshake transcript
   - SNI sent, TLS version/cipher, ALPN, server cert CN/SAN, chain validity, time skew
   - Pinpoints TLS policy issues (old TLS, corporate MITM, stale root store)
4. SMTP dialog (codes and verbs)
   - Code with short reason parsing
   - Map to human reasons (mask base64 blobs after `AUTH`)
5. Retry sweep across IPs and attempts
   - `success_rate`, per-IP outcomes, min/median/max times
   - Reveals true transience
6. Environment crumbs
   - OS, clock offset, default route, proxy discovery (env vars, WinINET/WinHTTP proxy), IPv6 enabled, corporate SSL inspection detection heuristics
   - Avoids "but it works on my machine..."
7. Minimal AA context
   - Activity name, bot run ID, AA host, configured server/port/SSL mode
   - Optional input

## Failure Classification
Normalize every probe into a classification. Each classification stores the load-bearing evidence line and a short remediation hint. 

| Class | Description |
| --- | ---|
| `dns` | NXDOMAIN/timeout/wrong resolver, hosts override. |
| `connect` | TCP timeout/reset/unreachable port |
| `tls` | handshake failure, cert distrust/expired, TLS policy mismatch, SNI/ALPN mismatch |
| `auth` | 534/535 class errors, XOAUTH2 token invalid/expired |
| `smtp-policy` | 530/550/552 content/policy, “daily user sending limit exceeded”, attachment blocked|
| `rate-limit` | 421/4.7.x deferrals, greylisting/temporary failures |
| `proxy` | explicit proxy demanded/seen, MITM cert, authentication required by proxy |
| `ok` | uccess path to AUTH (or to MAIL FROM if --auth-test enabled) |
| `unknown` | anything else (include last error line) |

## Output Format
When you run `smtp-probe` it creates a new directory. 
```
smtp-probe-YYYYMMDD_HHMMSS/
├─ report.md                # 1–2 page human summary (pasteable in tickets)
├─ probe_summary.json       # structured outcome across IPs/attempts
├─ smtp_transcript_*.txt    # sanitized SMTP dialogues (one per attempt)
├─ tls_handshake_*.txt      # TLS details (one per IP/port)
├─ dns_resolution.json      # raw DNS results and timings
├─ env_snapshot.json        # OS/proxy/route/clock info
└─ attachments/
   └─ all_files.zip         # single ZIP for upload
```
## Integration with Automation Anywhere
1. Pre-flight
   - Call `smtp-probe` before enabling a bot
   - Save the ZIP archive in the run artifacts
2. On failure
   - In the bot's error handling, run `smtp-probe` with the same server/port/mode
   - Attach the resulting ZIP to the incident
3. Local tee proxy (optional, testing only)

## Implementation Notes
- Language: GO or Python
- TLS + SMTP: use standard libraries with verbose handshake hooks
   - Go: `crypto/tls`, `net/smtp`, capture `ClientHelloInfo`, `ConnectionState`
   - Python: `ssl` with `ssl.SSLContext`, `smtplib` using `SMTP_SSL` / `starttls()`, wrap socket to log bytes pre-AUTH
- DNS: query system resolver first; add flag `--dns 8.8.8.8` to compare
- Timing: capture connect, TLS, EHLO, STARTTL, AUTH latencies individually
- Sanitization: after detecting `AUTH`, log only the verb and server code (do not commit base64 payloads or message content)
- No pcap by default: keep it free of dependencies

## Scope
### Minimum Viable Product
- CLI with `probe` and `diagnose` subcommands
- Tests: 465 and 587 to `smtp.gmail.com` using no-auth by default
- JSON + `report.md` output + ZIP packer
- Failure classifier and short 'next step' hints
- Redaction and masking (keep the secrets out of the logs)
### Nice-to-have
- AUTH XOAUTH2 test (short-lived token via `--xoauth2` stdin)
- Parallel per-IP probes and percentile timing summaries
- HTML report (single file)
- Optional pcap capture w/auto-filter to Gmail IP/port
- Health checks against multiple SMTP providers
- Remote execution mode for runner machines (invoke over SSH/WinRM)

## Proof
This minimal sketch proves the concept:

resolve &rarr; connect &rarr; STARTTLS &rarr; EHLO over TLS &rarr; grab cipher/cert
```python
#!/usr/bin/env python3
import socket, ssl, smtplib, time, json
import dns.resolver # alt: socket.getaddrinfo

def resolve(host):
    infos = socket.getaddrinfo(host, None)
    addrs = []
    for fam, _, _, _, sa in infos:
        ip = sa[0]
        family = 'ipv6' if fam == socket.AF_INET6 else 'ipv4'
        addrs.append((family, ip))
    # de-dup while preserving order
    seen, uniq = set(), []
    for fam, ip in addrs:
        if ip not in seen: uniq.append((fam, ip)); seen.add(ip)
    return uniq

def probe_tls(host, port, ip, starttls=False, timeout=5.0):
    s = socket.socket(socket.AF_INET6 if ':' in ip else socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    t0 = time.time()
    s.connect((ip, port))
    connect_ms = int(1000*(time.time()-t0))
    if starttls:
        # Read greeting
        banner = s.recv(4096).decode(errors='ignore')
        s.sendall(b"EHLO smtp-probe\r\n")
        _ = s.recv(4096)
        s.sendall(b"STARTTLS\r\n")
        _ = s.recv(4096)
    ctx = ssl.create_default_context()
    tls = ctx.wrap_socket(s, server_hostname=host)
    cs = tls.cipher()
    peercert = tls.getpeercert()
    # SMTP hello over TLS
    tls.sendall(b"EHLO smtp-probe\r\n")
    ehlo = tls.recv(4096).decode(errors='ignore')
    tls.close()
    return {
        "ip": ip, "port": port, "connect_ms": connect_ms,
        "tls_cipher": cs[0] if cs else None,
        "tls_protocol": cs[1] if cs else None,
        "cert_subject": peercert.get('subject', None),
        "ehlo_sample": ehlo.splitlines()[:3]
    }

def run():
    host, port, mode = "smtp.gmail.com", 587, "starttls"  # edit as needed
    results = {"host": host, "port": port, "mode": mode, "attempts": []}
    for fam, ip in resolve(host):
        try:
            r = probe_tls(host, port, ip, starttls=(port==587))
            results["attempts"].append({"ip": ip, "ok": True, **r})
        except Exception as e:
            results["attempts"].append({"ip": ip, "ok": False, "error": str(e)})
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    run()

```
