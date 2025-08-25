# Engineering Spec
## 1.1 Problem and objective
Automation Anywhere's Email Automation package can be pointed at Gmail (server and port), but it doesn't expose network-level telemetry when sends fail. The goal is a small CLI tool that:
- Reproduces the exact path the bot uses (host/port/mod)
- Captures only the most relevant evidence for transient/production issues
- Classifies the failure succinctly and bundles a shareable ZIP with a one-page summary and raw artifacts.

> **Primary Objective**: retrieve the most relevant logs automatically, with minimal noise, to accelerate triage.
