# Engineering Specifications and Checklist
## 1 - Specs
### 1.1 Problem and objective
Automation Anywhere's Email Automation package can be pointed at Gmail (server and port), but it doesn't expose network-level telemetry when sends fail. The goal is a small CLI tool that:
- Reproduces the exact path the bot uses (host/port/mod)
- Captures only the most relevant evidence for transient/production issues
- Classifies the failure succinctly and bundles a shareable ZIP with a one-page summary and raw artifacts.

> **Primary Objective**: retrieve the most relevant logs automatically, with minimal noise, to accelerate triage.

### 1.2 High-level capabilities
- **Active probe**: resolve, connect, TLS (implicit/STARTTLS), EHLO, AUTH test
- **Multi-IP sweep**: try each resolved A/AAAA; track per-IP outcomes to expose transient fault(s)
- **Failure classification**: `dns`, `connect`, `tls`, `auth`, `smtp-policy`, `rate-limit`, `proxy`, `ok`, `unknown`
- **Evidence capture**: DNS answers + timings, connect/TLS timings, TLS params and cert chain, SMTP codes/lines (sanitized), environment crumbs (OS, proxy hints, clock skew)
- **Bundle**: `report.md`, `probe_summary.json`, transcripts, TLS details, DNS results, env snapshot --> single ZIP
- **Automation Anywhere integration**: simple exit codes, JSON output path for ingestion

### 1.3 CLI
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

### 1.4 Data captured
| Capture | Why it matters | How |
| --- | --- | ---|
| DNS answers (A/AAAA, TTL, resolver IPs, query time) | Detect AAAA pitfalls, per-ip fault | system resolver by default; optional override |
| TCP connect timing (reset vs timeout) | firewall/proxy vs latent path | socket connect. + errno |
| TLS details (version, cipher, ALPN, SNI, chain validity, issuer) | TLS policy/inspection/time skew | `ssl`/`crypto`/`tls` connection state |
| SMTP transcript | classify 5xx/4xx; show last useful line | read server banners, EHLO caps, STARTTLS, AUTH codes; mask payloads |
| Per-IP retries, statistics | prove transience vs systemic | configurable attempts per IP |
| Environment crumbs | context; proxy, route, clock skew | OS + env vars; netsh or env; system time vs cert validity |
| AA context | tie probe to bot run | ingest small json from bot |

### 1.5 Failure classification
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

### 1.6 Artifact layout

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

### 1.7 Implementation
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

### 1.8 Security
- Never log credentials or the payload of AUTH lines (mask base64 after the verb).
- Mask tokens if --auth-test xoauth2 is used (read token from stdin; never echo).
- Do not capture message content; this tool is about connection/auth only.
- Zip is local‑only; tool makes no outbound HTTP calls.
- Optionally hash hostnames/usernames when --redact is set.

### 1.9 Automation Anywhere integration
1. Pre-flight
2. On Failure
    1. Run `smtp-probe diagnose --server $server$ --port $port$ --mode $mode$ --zip-out $artifactZip$`
    2. Read `probe_summary.json` -- derive a short message
    3. Attach `$artifaceZip$` to alert for support

**AA Variables** 
- pass server/port/mode from bot config
- capture `exit code` to branch on class

### 1.10 Acceptance criteria
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

## 2 - Checklists
### 2.1 Build checklist
- [ ] Parse CLI flags and subcommands; implement stable exit codes.
- [ ] Resolver: system DNS and optional overrides; collect answers + TTL + timing.
- [ ] Per-IP probe loop with configurable attempts, timeout, parallelism
- [ ] TLS handshake capture: version, cipher, ALPN, SNI, cert chain, validity, hostname match.
- [ ] SMTP dialogue: banner &rarr; EHLO &rarr; (STARTTLS if requested) &rarr; EHLO &rarr; [AUTH]
- [ ] Sanitization: strip/mask AUTH payloads, secrets
- [ ] Classifier: implement rules, remidation short text
- [ ] Writers: `probe_summary.json`, transcripts, TLS details, `report.md`, optional ZIP
- [ ] `--collect-env`: OS, hostname, timezone, proxy env, clock skew; Windows WinHTTP proxy readout.
- [ ] Logging: quiet by default; `--verbose` logs to stderr (not artifacts)
- [ ] Deterministic file names, inclusive of ISO8601 timestamps
### 2.2 Test matrix
**Ports/Modes**
- [ ] 465 (implicit TLS)
- [ ] 587 (STARTTLS)
- [ ] Plain text (lab only)

**Network scenarios**
- [ ] DNS timeout / bad resolver
- [ ] AAAA present but IPv6 path blocked
- [ ] TCP blocked (timeout)
- [ ] TCP reset by firewall
- [ ] TLS handshake alert (server requires newer TLS)
- [ ] Corporate SSL inspection (issuer != Google Trust Services)
- [ ] System clock skew (+/- 1 day)
**SMTP / auth**
- [ ] AUTH PLAIN invalid app password &rarr; `535`
- [ ] XOAUTH2 expired token &rarr; `534 5.7.14`
- [ ] No AUTH where required &rarr; `530` policy
- [ ] Rate limit &rarr; `421 4.7.0` (simulate w/throttle or mocking)
**Functionality**
- [ ] `--parallelism` > 1 behaves properly
- [ ] `--redact` masks username / tokens / IPs as designed
- [ ] ZIP size under 1MB typical; includes all expected files
- [ ] Exit codes match classification

### 2.3 Release checklist
- [ ] Version stamped in `probe_summary.json.tool.version`.
- [ ] Build for Windows x64
- [ ] Smoke test on clean runner VM
- [ ] Publish checksum, changelog
- [ ] Update AA bot snippet to read JSON and attach ZIP

### 2.4 Security checklist
- [ ] No secrets written to disk; AUTH payload masking verified in unit tests
- [ ] Token read via stdin when XOAUTH2 is used; never echoed.
- [ ] Redaction path exercised in CI
- [ ] Tool makes no external HTTP telemetry calls

## 3 - Template (`Report.md`)
```markdown
# SMTP Probe Report — {{tool.name}} v{{tool.version}}

- **Run ID:** {{run_id}}
- **Host:** {{environment.hostname}} ({{environment.os}})
- **When:** {{started_at}} → {{finished_at}} ({{duration_ms}} ms)
- **Tested:** {{server}}:{{port}} (mode: {{mode}}, family: {{family}})
{{#if aa_context.bot_name}}
- **AA Context:** bot={{aa_context.bot_name}}, run_id={{aa_context.run_id}}, activity={{aa_context.activity_name}}
{{/if}}

---

## Summary

- **Attempts:** {{summary.attempts_total}}  
- **Success:** {{summary.attempts_ok}} ({{summary.success_rate}}%)  
- **Failures:** {{summary.attempts_failed}}  
- **Top classification:** {{summary.top_classification}}  

**Recommendations:**  
{{#if summary.recommendations}}
{{#each summary.recommendations}}
- {{this}}
{{/each}}
{{else}}
- (none)
{{/if}}

---

## Per‑IP Outcomes

| IP | Fam | OK | Fail | p50 connect (ms) | p50 TLS (ms) | Last class |
|---|---:|---:|---:|---:|---:|---|
{{#each summary.per_ip}}
| {{ip}} | {{family}} | {{ok_count}} | {{fail_count}} | {{connect_ms_p50}} | {{tls_ms_p50}} | {{last_classification}} |
{{/each}}

---

## DNS & Environment (abridged)

- **Resolvers:** {{#each dns.resolver_addresses}}{{this}}{{#unless @last}}, {{/unless}}{{/each}}
- **Answers:** {{#each dns.answers}}{{ip}} ({{family}}){{#unless @last}}, {{/unless}}{{/each}}
- **DNS time:** {{dns.query_ms}} ms
{{#if environment.proxy.detected}}
- **Proxy detected:** yes ({{environment.proxy.winhttp_proxy}}{{environment.proxy.https_proxy}})
{{/if}}
- **Clock skew:** {{environment.clock_skew_ms}} ms (approx)

---

## Last Failure Evidence

{{#if last_failure}}
- **Classification:** {{last_failure.classification}}
- **IP:** {{last_failure.ip}}:{{last_failure.port}}
- **Evidence:**  
```

## 4 - JSON schema (`probe_summary.json`)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SMTP Probe Summary",
  "type": "object",
  "required": [
    "tool",
    "run_id",
    "started_at",
    "server",
    "port",
    "mode",
    "family",
    "attempt_plan",
    "attempts",
    "summary"
  ],
  "properties": {
    "tool": {
      "type": "object",
      "required": ["name", "version"],
      "properties": {
        "name": { "type": "string", "const": "smtp-probe" },
        "version": { "type": "string" }
      }
    },
    "run_id": { "type": "string" },
    "started_at": { "type": "string", "format": "date-time" },
    "finished_at": { "type": "string", "format": "date-time" },
    "duration_ms": { "type": "integer", "minimum": 0 },
    "server": { "type": "string" },
    "port": { "type": "integer", "minimum": 1, "maximum": 65535 },
    "mode": { "type": "string", "enum": ["starttls", "implicit-tls", "plain"] },
    "family": { "type": "string", "enum": ["ipv4", "ipv6", "dual"] },
    "dns": {
      "type": "object",
      "properties": {
        "resolver_addresses": { "type": "array", "items": { "type": "string" } },
        "answers": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["ip", "family"],
            "properties": {
              "ip": { "type": "string" },
              "family": { "type": "string", "enum": ["ipv4", "ipv6"] },
              "ttl": { "type": "integer", "minimum": 0 },
              "rcode": { "type": "string" }
            }
          }
        },
        "query_ms": { "type": "integer", "minimum": 0 }
      }
    },
    "attempt_plan": {
      "type": "object",
      "required": ["per_ip_attempts", "timeout_ms", "auth_test"],
      "properties": {
        "per_ip_attempts": { "type": "integer", "minimum": 1 },
        "timeout_ms": { "type": "integer", "minimum": 1 },
        "auth_test": { "type": "string", "enum": ["none", "plain", "login", "xoauth2"] },
        "parallelism": { "type": "integer", "minimum": 1 }
      }
    },
    "environment": {
      "type": "object",
      "properties": {
        "os": { "type": "string" },
        "hostname": { "type": "string" },
        "timezone": { "type": "string" },
        "clock_skew_ms": { "type": "integer" },
        "proxy": {
          "type": "object",
          "properties": {
            "http_proxy": { "type": "string" },
            "https_proxy": { "type": "string" },
            "no_proxy": { "type": "string" },
            "winhttp_proxy": { "type": "string" },
            "detected": { "type": "boolean" }
          }
        }
      }
    },
    "aa_context": {
      "type": "object",
      "properties": {
        "bot_name": { "type": "string" },
        "run_id": { "type": "string" },
        "activity_name": { "type": "string" },
        "aa_host": { "type": "string" },
        "log_window_start": { "type": "string", "format": "date-time" },
        "log_window_end": { "type": "string", "format": "date-time" }
      }
    },
    "attempts": {
      "type": "array",
      "items": { "$ref": "#/$defs/attempt" }
    },
    "summary": { "$ref": "#/$defs/summary" },
    "last_failure": { "$ref": "#/$defs/attempt" }
  },
  "$defs": {
    "attempt": {
      "type": "object",
      "required": ["ip", "family", "port", "started_at", "classification", "ok"],
      "properties": {
        "ip": { "type": "string" },
        "family": { "type": "string", "enum": ["ipv4", "ipv6"] },
        "port": { "type": "integer" },
        "ip_source": { "type": "string", "enum": ["dns", "override", "cache"] },
        "started_at": { "type": "string", "format": "date-time" },
        "finished_at": { "type": "string", "format": "date-time" },
        "timings_ms": {
          "type": "object",
          "properties": {
            "dns": { "type": "integer", "minimum": 0 },
            "connect": { "type": "integer", "minimum": 0 },
            "starttls": { "type": "integer", "minimum": 0 },
            "tls": { "type": "integer", "minimum": 0 },
            "ehlo": { "type": "integer", "minimum": 0 },
            "auth": { "type": "integer", "minimum": 0 }
          }
        },
        "tls": {
          "type": "object",
          "properties": {
            "sni": { "type": "string" },
            "version": { "type": "string" },
            "cipher": { "type": "string" },
            "alpn": { "type": "string" },
            "peer_cert": {
              "type": "object",
              "properties": {
                "subject": { "type": "string" },
                "issuer": { "type": "string" },
                "san": { "type": "array", "items": { "type": "string" } },
                "not_before": { "type": "string", "format": "date-time" },
                "not_after": { "type": "string", "format": "date-time" },
                "validated": { "type": "boolean" }
              }
            }
          }
        },
        "smtp": {
          "type": "object",
          "properties": {
            "greeting": { "type": "string" },
            "caps": { "type": "array", "items": { "type": "string" } },
            "last_code": { "type": "integer" },
            "last_enhanced_status": { "type": "string", "pattern": "^\\d\\.\\d\\.\\d$" },
            "last_line": { "type": "string" }
          }
        },
        "ok": { "type": "boolean" },
        "classification": {
          "type": "string",
          "enum": ["ok", "dns", "connect", "tls", "auth", "smtp-policy", "rate-limit", "proxy", "unknown"]
        },
        "evidence": { "type": "string" },
        "artifacts": {
          "type": "object",
          "properties": {
            "smtp_transcript": { "type": "string" },
            "tls_handshake": { "type": "string" }
          }
        }
      }
    },
    "summary": {
      "type": "object",
      "required": ["attempts_total", "attempts_ok", "attempts_failed", "success_rate", "per_ip"],
      "properties": {
        "attempts_total": { "type": "integer" },
        "attempts_ok": { "type": "integer" },
        "attempts_failed": { "type": "integer" },
        "success_rate": { "type": "number", "minimum": 0, "maximum": 100 },
        "classification_counts": {
          "type": "object",
          "additionalProperties": { "type": "integer" }
        },
        "per_ip": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["ip", "ok_count", "fail_count"],
            "properties": {
              "ip": { "type": "string" },
              "family": { "type": "string" },
              "ok_count": { "type": "integer" },
              "fail_count": { "type": "integer" },
              "connect_ms_p50": { "type": "number" },
              "tls_ms_p50": { "type": "number" },
              "last_classification": { "type": "string" }
            }
          }
        },
        "top_classification": { "type": "string" },
        "recommendations": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```