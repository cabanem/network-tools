# SMTP Probe

## Understanding the Challenge
When Automation Anywhere bots fail to send emails through Gmail, there can be little network-level visibility. Regardless of the cause of the failure, you'll often see a message like, "There was an error sending the email message. Please check your connection details provided and try again." The generic nature of this error can make troubleshooting and resolution challenging. 

Our objective with this tool is to build a small, cross-platform 'SMTP probe and collector' that can (a) reproduce the exact SMTP/Gmail path used by AA bots, (b) collect the right diagnostics (DNS, TLS, SMTP transcript, timing, OS/network facts), (c) classify the failure with clear, actionable reasons, and (d) package in a single, shareable ZIP with a human summary and raw evidence.

## Architecture Overview

| Layer | Description              |
| ----  | -------------------------|
| Probe | Reproduces the exact connection path of the Automation Anywhere bot |
| Collection | Captures all relevant diagnostic data during the connection attempt |
| Analysis | Interprets the collected data to classify the failure |
| Packaging | Bundles everything into an actionable report |

## Building the solution
1. Install `Go`
2. Create the project structure
   - Main program entrypoint `cmd/smtp-probe/`
   - Private packages in `internal/`
   - Single-responsibility sub-folders in `internal/`

    **Linux**
    ```bash
    mkdir -p smtp-probe/cmd/smtp-probe
    mkdir -p smtp-probe/internal/{cli,probe,dnsutil,classify,bundle,envsnap,report/templates,smtpflow,tlsdiag}
    cd smtp-probe
    ```
    **Windows**
    ```powershell
    New-Item -ItemType Directory -Force smtp-probe\cmd\smtp-probe | Out-Null
    "cli","probe","dnsutil","classify","bundle","envsnap","report\templates","smtpflow","tlsdiag" |
    ForEach-Object { New-Item -ItemType Directory -Force ("smtp-probe\internal\{0}" -f $_) | Out-Null }
    cd smtp-probe
    ```
3. Create a file `go.mod` in the directory, `smtp-probe/`
    ```go
    module smtp-probe

    go 1.21
    ```
    >**Understand Go Modules**
    >Go uses a [module system](https://go.dev/ref/mod) to manage dependencies. `go.mod` can be thought of as a recipe card that lists all the ingrediates (packages) required by your dish (program) 
4. Create each file

    | File name | Description      |
    | --------- | -----------------|
    | `main.go` | Reads input commands and routes to appropriate function |
    | `cli.go`  | Handles command line args; interprets flags and options |
    | `probe.go`| Orchestrates testing process; coordinates DNS lookups, connection attempts, result compilation |
    | `dnsutil/dns.go` | Looks up the domain name associated with each IP address |
    | `classify/classify.go` | Examines error messages and response codes to determine the type of problem |

5. Build your program

    Compile source code into an executable. On success you'll see a new file, `smtp-probe` (or `smtp-probe.exe` on Windows)
    ```go
    go build ./cmd/smtp-probe
    ```
6. Test

    The command below tests Gmail's SMTP server on port 587 using STARTTLS mode. Output should be a timestamped folder containing the files, `report.md`, `probe_summary.json`, `smtp_transcript_*.txt`, `dns_resolution.json`. 

    ```bash
    ./smtp-probe probe --server smtp.gmail.com --port 587 --mode starttls
    ```
