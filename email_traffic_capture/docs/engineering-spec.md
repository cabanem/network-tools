# Engineering Spec
## 1.1 Problem and objective
Automation Anywhere's Email Automation package can be pointed at Gmail (server and port), but it doesn't expose network-level telemetry when sends fail. The goal is a small CLI tool that:
- Reproduces the exact path the bot uses (host/port/mod)
- Captures only the most relevant evidence for transient/production issues
- Classifies the failure succinctly and bundles a shareable ZIP with a one-page summary and raw artifacts.

> **Primary Objective**: retrieve the most relevant logs automatically, with minimal noise, to accelerate triage.

## 1.2 High-level capabilities
- **Active probe**: resolve, connect, TLS (implicit/STARTTLS), EHLO, AUTH test
- **Multi-IP sweep**: try each resolved A/AAAA; track per-IP outcomes to expose transient fault(s)
- **Failure classification**: `dns`, `connect`, `tls`, `auth`, `smtp-policy`, `rate-limit`, `proxy`, `ok`, `unknown`
- **Evidence capture**: DNS answers + timings, connect/TLS timings, TLS params and cert chain, SMTP codes/lines (sanitized), environment crumbs (OS, proxy hints, clock skew)
- **Bundle**: `report.md`, `probe_summary.json`, transcripts, TLS details, DNS results, env snapshot --> single ZIP
- **Automation Anywhere integration**: simple exit codes, JSON output path for ingestion

## 1.3 CLI
```json
smtp-probe probe
  --server <hostname>                # e.g., smtp.gmail.com
  --port <465|587|...>
  --mode <starttls|implicit-tls|plain>
  --attempts <N>                     # total attempts per resolved IP (default: 2)
  --family <dual|ipv4|ipv6>          # default: dual
  --timeout-ms <int>                 # socket/TLS step timeout (default: 5000)
  --auth-test <none|plain|login|xoauth2>  # default: none
  --username <user>                  # only if --auth-test != none
  --per-ip-attempts <int>           # alias of --attempts for clarity
  --parallelism <int>               # default: 2
  --out-dir <path>                   # where artifacts are written (auto if omitted)
  --zip-out <path.zip>               # create a single zip with all artifacts
  --dns <system|ip1,ip2>             # resolver(s); default: system
  --family-order <ipv4-first|ipv6-first>  # default: system order
  --collect-env                      # include env snapshot (OS, proxies, routes)
  --redact                           # mask secrets, usernames, tokens

smtp-probe diagnose                  # wrapper to include env + AA context
  --server ... --port ... --mode ...
  --aa-json <aa_context.json>        # optional; pulled into summary
  [all probe flags] --collect-env --zip-out probe_artifacts.zip
```
**Exit codes**
- `0` = ok
- `70` dns, `71` connect, `72` tls, `73` auth, `74` smtp-policy, `75` rate-limit, `76` proxy, `1` unknown/other

## 1.4 Data captured
| Capture | Why it matters | How |
| --- | --- | ---|
| DNS answers (A/AAAA, TTL, resolver IPs, query time) | Detect AAAA pitfalls, per-ip fault | system resolver by default; optional override |
| TCP connect timing (reset vs timeout) | firewall/proxy vs latent path | socket connect. + errno |
| TLS details (version, cipher, ALPN, SNI, chain validity, issuer) | TLS policy/inspection/time skew | `ssl`/`crypto`/`tls` connection state |
| SMTP transcript | classify 5xx/4xx; show last useful line | read server banners, EHLO caps, STARTTLS, AUTH codes; mask payloads |
| Per-IP retries, statistics | prove transience vs systemic | configurable attempts per IP |
| Environment crumbs | context; proxy, route, clock skew | OS + env vars; netsh or env; system time vs cert validity |
| AA context | tie probe to bot run | ingest small json from bot |

## 1.5 Failure classification
- dns: NXDOMAIN, SERVFAIL, or timeout; no connect attempted.
- connect: socket timeout or ECONNREFUSED/ECONNRESET before TLS.
- tls: handshake failure, cert invalid/untrusted/expired/NotYetValid; ALPN/SNI mismatch; TLS version/cipher alert.
- auth: 535, 534 5.7.14 (Gmail), 530 5.7.0 Authentication required after AUTH attempt.
- smtp-policy: 550/552/553/554 policy/content; 530 when not using AUTH but policy requires it for relay.
- rate-limit: 421 or 4.7.x deferrals (temporary).
- proxy: explicit proxy demanded (407/HTTP interception), or TLS chain anchored to corporate interception CA.
- ok: reached EHLO over TLS; if --auth-test used, reached 235 success.
- unknown: anything else; store last evidence line.

Each attempt stores classification + a single evidence string: the most useful server line or local error.

## 1.6 Artifact layout

```
smtp-probe-YYYYMMDD_HHMMSS/
├─ report.md
├─ probe_summary.json
├─ dns_resolution.json
├─ env_snapshot.json             # only with --collect-env
├─ smtp_transcript_<ip>_<n>.txt  # sanitized; one per attempt
├─ tls_handshake_<ip>.txt
└─ <zip specified by --zip-out>  # optional bundling of everything above
```

## 1.7 Implementation
**Modules**
- `resolver.* ` — system DNS (and optional override), A/AAAA + timing.
- `dial.*` — connect with timeout, measure connect_ms, capture local bind addr.
- `tlsdiag.*` — wrap connection, set SNI, capture protocol/cipher/ALPN, certs, validity, chain, hostname match.
- `smtpflow.*` — banner/EHLO caps/STARTTLS/Auth test; sanitize logs; compute timings for each step.
- `classifier.*` — map outcomes → classes + remediation hint.
- `envsnap.*` — OS, hostname, timezone, proxy env, (Windows) netsh winhttp show proxy, clock skew estimate.
- `bundle.*` — write artifacts, compose report.md, compress ZIP.
- `cli.*` — flags, subcommands, exit codes; stable JSON.

**Language choice**
- Go (single static binary, great TLS APIs)
- Python (fastest iteration)

## 1.8 Security
- Never log credentials or the payload of AUTH lines (mask base64 after the verb).
- Mask tokens if --auth-test xoauth2 is used (read token from stdin; never echo).
- Do not capture message content; this tool is about connection/auth only.
- Zip is local‑only; tool makes no outbound HTTP calls.
- Optionally hash hostnames/usernames when --redact is set.

## 1.9 Automation Anywhere integration
1. Pre-flight
2. On Failure
    1. Run `smtp-probe diagnose --server $server$ --port $port$ --mode $mode$ --zip-out $artifactZip$`
    2. Read `probe_summary.json` -- derive a short message
    3. Attach `$artifaceZip$` to alert for support

**AA Variables** 
- pass server/port/mode from bot config
- capture `exit code` to branch on class

## 1.10 Acceptance criteria
- Produces report.md + probe_summary.json on every run, even on fatal errors.
- Correctly classifies at least these scenarios: 
    1. wrong port
    2. IPv6 unreachable but AAAA present
    3. corporate TLS interception
    4. nvalid XOAUTH2 token
    5. Gmail rate limit (4.7.x)
    6. firewall TCP reset.
- `ZIP` bundle under 1 MB in typical cases.
- No secrets in any artifact with --redact; `AUTH` payloads masked even without --redact.

