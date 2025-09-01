# Implementation in Go

## Dependencies
- Standard library for core functionality
    - `net`, `net/netip`, 
    - `bufio`, `flag`, `os`, `strings`, `fmt`, `time`, `bytes`
    - `crypto/tls`, `crypto/sha256`, `crypto/rand`
    - `encoding/pem`, `encoding/json`, `math/rand`
    - `path/filepath`, `archive/zip`,
- Additional, gated dependencies
    - github.com/miekg/dns v1.1.x (widely used, actively maintained)

## Steps
1. Set up the module and define the project layout<br/>

    - Create directories and files for the project. <br/>
        ```bash
        mkdir -p smtp-probe/cmd/smtp-probe
        mkdir -p smtp-probe/internal/{cli,core,probe,dnsutil,tlsdiag,smtpflow,envsnap,redact,classify,bundle,report/templates}
        cd smtp-probe
        ```

    - Create the module file, `go.mod`<br/>
        ```go
        go mod init your.org/smtp-probe
        go version  # ensure Go 1.21+
        ```

    **Packages**
    | Package | Responsibilities |
    | ---     | ---------------- |
    | `internal/cli` | parse flags, validate combos, compute defaults, orchestrate a run |
    | `internal/probe` | high‑level orchestration (DNS→TCP→TLS→SMTP), timings, artifacts |
    | `internal/dnsutil` | system DNS (+ optional deep DNS under a build tag) |
    | `internal/tlsdiag` | TLS context + chain dump + fingerprints |
    | `internal/smtpflow` | low‑level SMTP client (EHLO/STARTTLS/AUTH/MAIL/RCPT/DATA) with transcript & timings |
    | `internal/envsnap` | OS/proxy/timezone/DNS resolver capture (text + JSON) |
    | `internal/redact` | secret & PII masking (emails, tokens, passwords) |
    | `internal/classify` | error mapping to Gmail‑aware verdicts & actions |
    | `internal/bundle` | write files and zip the run directory |
    | `internal/report` | render summary.md from a template + machine report.json |

---
2. Set up the CLI<br/>
    
    **CLI Flags**
    ```
    --host [smtp.gmail.com]     --port [465|587]
    --mode implicit|starttls|plain
    --auth none|login|plain|xoauth2
    --username USER --password PASS --oauth-token TOKEN
    --from FROM --to TO --subject SUBJ --body BODY
    --send                        # actually send DATA (off by default)
    --timeout 15s                 # per-step timeout
    --attempts 1 --attempt-delay 0s
    --dns system|deep             # deep requires build tag dnsdeep
    --ipv4-only | --ipv6-only
    --outdir PATH [auto]          # run-YYYYmmdd-HHMMSS
    --zip PATH                    # write ZIP bundle
    --redact                      # on by default
    --verbose
    ```

    Define the skeleton in `internal/cli/cli.go`
    ```go
    package cli
    
    import (
        "flag"
        "fmt"
        "time"
        "os"
        "path/filepath"
        "org/smtp-probe/internal/probe"
    )

    func Run(args []string) int {
        fs := flag.NewFlagSet("smtp-probe", flag.ContinueOnError)
        host := fs.String("host", "smtp.gmail.com", "SMTP host")
        port := fs.Int("port", 465, "SMTP port")
        mode := fs.String("mode", "implicit", "implicit|starttls|plain")
        auth := fs.String("auth", "none", "none|login|plain|xoauth2")
        user := fs.String("username", "", "Username")
        pass := fs.String("password", "", "Password")
        token := fs.String("oauth-token", "", "OAuth2 access token")
        from := fs.String("from", "", "MAIL FROM")
        to := fs.String("to", "", "RCPT TO (comma-separated)")
        subject := fs.String("subject", "probe", "Subject")
        body := fs.String("body", "probe body", "Body")
        send := fs.Bool("send", false, "Send a test message")
        timeout := fs.Duration("timeout", 15*time.Second, "Step timeout")
        attempts := fs.Int("attempts", 1, "Attempts per IP")
        attemptDelay := fs.Duration("attempt-delay", 0, "Delay between attempts")
        dnsMode := fs.String("dns", "system", "system|deep")
        ipv4 := fs.Bool("ipv4-only", false, "Force IPv4")
        ipv6 := fs.Bool("ipv6-only", false, "Force IPv6")
        outdir := fs.String("outdir", "", "Output dir (auto if empty)")
        zipPath := fs.String("zip", "", "ZIP output path")
        redact := fs.Bool("redact", true, "Redact secrets in artifacts")
        verbose := fs.Bool("verbose", false, "Verbose logging to stdout")

        if err := fs.Parse(args); err != nil { return 2 }
        if *ipv4 && *ipv6 { fmt.Fprintln(os.Stderr, "--ipv4-only and --ipv6-only are mutually exclusive"); return 2 }
        if *auth != "none" && *user == "" && *auth != "xoauth2" { fmt.Fprintln(os.Stderr, "--username required for auth"); return 2 }
        if *auth == "login" && *pass == "" { fmt.Fprintln(os.Stderr, "--password required for auth=login"); return 2 }
        if *auth == "plain" && *pass == "" { fmt.Fprintln(os.Stderr, "--password required for auth=plain"); return 2 }
        if *auth == "xoauth2" && (*user == "" || *token == "") { fmt.Fprintln(os.Stderr, "--username and --oauth-token required for auth=xoauth2"); return 2 }

        if *outdir == "" {
            *outdir = time.Now().UTC().Format("run-20060102-150405Z")
        }
        if err := os.MkdirAll(*outdir, 0o755); err != nil { fmt.Fprintln(os.Stderr, "mkdir outdir:", err); return 1 }

        cfg := probe.Config{
            Host: *host, Port: *port, Mode: *mode,
            Auth: *auth, Username: *user, Password: *pass, OAuthToken: *token,
            From: *from, ToCSV: *to, Subject: *subject, Body: *body, DoSend: *send,
            Timeout: *timeout, Attempts: *attempts, AttemptDelay: *attemptDelay,
            DNSMode: *dnsMode, IPv4Only: *ipv4, IPv6Only: *ipv6,
            OutDir: *outdir, ZipPath: *zipPath, Redact: *redact, Verbose: *verbose,
        }
        code := probe.Run(cfg)
        if *zipPath != "" {
            if err := probe.ZipDir(*outdir, *zipPath); err != nil {
                fmt.Fprintln(os.Stderr, "zip:", err)
                if code == 0 { code = 1 }
            } else {
                fmt.Println("Wrote ZIP:", filepath.Clean(*zipPath))
            }
        }
        return code
    }
    ```
---
3. Build the evidence schema module (`internal/probe/types.go`).<br/>
    Package:    `probe`<br/>
    Path:       `internal/probe/types.go`<br/>
    Structs:    `TLSInfo`, `SMTPStep`, `Attempt`, `Report`<br/>
    Functions:  --<br/>
---

4. Create the **Environment Snapshot** module.<br/>
    Package:    `envsnap`<br/>
    Path:       `internal/envsnap/envsnap.go`<br/>
    Structs:    `Snapshot`<br/>
    Functions:  `Collect`, `showDNS`<br/>
---

5. Define the **dnsutil** module<br/>
    Package:    `dnsutil`<br/>
    Path:       `internal/dnsutil/dns.go`<br/>
    Structs:    `Answer`<br/>
    Functions:  `Resolve`<br/>
---

6. Define **tlsdiag** package <br/>
    ```
    Package:    'tlsdiag'
    Path:       internal/tlsdiag/tlsdiag.go
    Structs:    Info
    Functions:  'StartTLS', WrapAnd'Handshake, 'versionString', 'cipherString'
    ```
    **Struct**
    ```Go
    type Info struct {
        Version, Cipher, ALPN, SNI string
        Subject, Issuer string
        SAN []string
        NotBefore, NotAfter string
        FingerprintSHA256 string
        Validated bool
        ChainPEMPath string
    }
    ```

---

7. Create a SMTP clinet using manual read/write<br/>
    ```
    Package:    smtpflow
    Path:       internal/smtpflow/client.go
    Structs:    Client
    Functions:  'New', 'isDigit', 'atoi', 'ms', 'lastLine'
    Methods:    Client struct pointer{
                    readResponse, writeLine, GreetAndEHLO, StartTlS, AuthLogin,
                    AuthPlain, AuthXOAUTH2, MailFrom, Data, Quit}
    ```

    Struct: `Client` <br/>
    ```Go
    type Client struct {
        Conn net.Conn
        R *bufio.Reader
        W *bufio.Writer
        Transcript *bytes.Buffer
        Step func(name string, durMs int, code int, line string)
        Timeout time.Duration
    }
    ```
---

8. Define **redact** package <br/>
    Package:    `redact`<br/>
    Path:       `internal/redact/redact.go`<br/>
    Structs:    `Secrets`<br/>
    Functions:  `Email`<br/>
---

9. Define **classify** package <br/>
    Package:    `classify`<br/>
    Path:       `internal/classify/classify.go`<br/>
    Structs:    `Verdict`<br/>
    Functions:  `FromDNS`, `FromConnect`, `FromTLS`, `FromSMTP`<br/>
---

10. Define a summary generator and bundler <br/>

    ```
    Package     'report'
    Path        'internal/report/report.go'
    Functions   'Render'
    ```

    **Define the module**<br/>
    ```go
    //go:embed templates/summary.md.tmpl
    var fs embed.FS

    func Render(r probe.Report, verd string, actions []string) string {
        t, _ := template.ParseFS(fs, "templates/summary.md.tmpl")
        var b bytes.Buffer
        _ = t.Execute(&b, map[string]any{
            "Verdict": verd,
            "R": r,
            "Actions": actions,
        })
        return b.String()
    }
    ```
    
    **Create the template**
    ```md
    # SMTP Probe Summary — {{ .R.Tool.Name }} v{{ .R.Tool.Version }}

    **Verdict:** {{ .Verdict }}

    **Path:** {{ .R.Host }}:{{ .R.Port }} ({{ .R.Mode }}) — Auth: {{ .R.Auth }} — Attempts: {{ .R.Attempts }}

    ## What failed / why
    - {{ .Verdict }}

    ## Timings (per attempt)
    {{- range $i, $a := .R.AttemptsDetail }}
    - IP {{$a.IP}} ({{$a.Family}}): {{ $a.TimingsMs }}
    {{- end }}

    ## Evidence
    - SMTP transcripts: `transcripts/`
    - TLS: `tls/tls.json`, `tls/cert_chain.pem`
    - DNS: `dns/dns.json`
    - System: `system/env.json`

    ## Recommended next actions
    {{- range .Actions }}
    - {{ . }}
    {{- end }}
    ```
    **Set up bundling**

    ```
    Package     'bundle'
    Path        'internal/bundle/bundle.go'
    Functions   'WriteJSON', 'WriteText', 'ZipDir'
    ```
---

11. Put it all together
    ```
    Package     'probe'
    Path        'internal/probe/run.go'
    Structs     'Config'
    Functions   'ZipDir', 'Run', 'doAttempt', 'writeTLSJSON', 'redactIf', 
                'buildRFC5322', 'splitCSV', 'hasCapability', 'last', 'exitCode'
    Import      fmt, net, time, strings, 
                smtp-probe/internal/{dnsutil, smtpflow, tlsdiag, classify, envsnap, bundle, redact}
    ```

    **Config**<br/>
    ```Go
    type Config struct {
        Host string; Port int; Mode string
        Auth string; Username string; Password string; OAuthToken string
        From string; ToCSV string; Subject string; Body string; DoSend bool
        Timeout time.Duration; Attempts int; AttemptDelay time.Duration
        DNSMode string; IPv4Only bool; IPv6Only bool
        OutDir string; ZipPath string; Redact bool; Verbose bool
    }
    ```

    **Functions**<br/>
    ZipDir<br/>
    ```Go
    func ZipDir(dir, zipPath string) error { return bundle.ZipDir(dir, zipPath) }
    ```
    Run<br/>
    ```Go
    func Run(cfg Config) int {
        // env
        // DNS
        // Iterate IPs, attempts
        // Return final verdict
        // Summarize
    }
    ```