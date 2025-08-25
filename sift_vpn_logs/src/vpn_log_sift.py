#!/usr/bin/env python3
import argparse, csv, io, json, re, sys, zipfile
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
try:
    from dateutil import parser as dtparse
except ImportError:
    dtparse = None

TS_RX = re.compile(r'(?P<ts>\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)')
IPV4_RX = re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b')
PORTAL_RX = re.compile(r'(?i)\bportal\b.*?\b(?P<portal>[A-Za-z0-9\.\-]+)')
GW_RX = re.compile(r'(?i)\b(?:gateway|gw)\b.*?\b(?P<gateway>[A-Za-z0-9\-\._]+)')
USER_RX = re.compile(r'(?i)\buser(?:name)?[=:]\s*(?P<user>[A-Za-z0-9\.\-_\\@]+)')

PATTERNS = [
    (re.compile(r'(?i)connecting to portal (?P<portal>\S+)'),      ('portal_connect_start','portal',None)),
    (re.compile(r'(?i)portal .* (success|connected)'),             ('portal_connect_success','portal',None)),
    (re.compile(r'(?i)portal .* (fail|unreachable|timeout)'),      ('portal_connect_fail','portal','network')),

    (re.compile(r'(?i)auth(entication)? (start|begin)'),           ('auth_start','auth',None)),
    (re.compile(r'(?i)auth(entication)? (success|succeeded)'),     ('auth_success','auth',None)),
    (re.compile(r'(?i)(auth(entication)? failed|invalid credential|mfa (deny|timeout)|saml .*error)'),
                                                                  ('auth_fail','auth','auth')),

    (re.compile(r'(?i)tls handshake (start|begin)'),               ('tls_handshake_start','tls',None)),
    (re.compile(r'(?i)tls handshake (success|complete)'),          ('tls_handshake_success','tls',None)),
    (re.compile(r'(?i)(tls handshake failed|certificate (expired|untrusted|mismatch|validation failed))'),
                                                                  ('tls_handshake_fail','tls','cert')),

    (re.compile(r'(?i)(selecting|selected) gateway (?P<gateway>\S+)'),
                                                                  ('gateway_select_success','gateway',None)),
    (re.compile(r'(?i)no available gateway|gateway .* (fail|timeout)'),
                                                                  ('gateway_select_fail','gateway','config')),

    (re.compile(r'(?i)tunnel is up'),                              ('tunnel_up','service',None)),
    (re.compile(r'(?i)tunnel is down'),                            ('tunnel_down','service',None)),
    (re.compile(r'(?i)reconnect(ing)?'),                           ('reconnect','service',None)),

    (re.compile(r'(?i)dns (set|server)|route (add|delete)|interface (up|down)'),
                                                                  ('net_change','network',None)),
]

@dataclass
class Event:
    ts: datetime
    severity: str
    component: str
    etype: str
    msg: str
    portal: str = None
    gateway: str = None
    user: str = None
    client_ip: str = None
    reason: str = None
    src: str = None    # file name

@dataclass
class Session:
    session_id: int
    start_ts: datetime
    end_ts: datetime = None
    outcome: str = 'unknown'  # success|fail|unknown
    fail_reason: str = None
    fail_detail: str = None
    portal: str = None
    gateway: str = None
    user: str = None
    client_ip: str = None
    reconnects: int = 0
    phase_start: dict = field(default_factory=dict)
    phase_ms: dict = field(default_factory=lambda: {'portal':None,'auth':None,'gateway':None,'tunnel':None})
    events: list = field(default_factory=list)

def parse_ts(line):
    m = TS_RX.search(line)
    if not m: return None
    t = m.group('ts')
    if dtparse:
        try: return dtparse.parse(t, fuzzy=True)
        except Exception: return None
    # Fallback minimal parser (YYYY/MM/DD HH:MM:SS[.ms] or YYYY-MM-DD ...)
    for fmt in ("%Y/%m/%d %H:%M:%S.%f","%Y-%m-%d %H:%M:%S.%f","%Y/%m/%d %H:%M:%S","%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(t, fmt)
        except Exception: pass
    return None

def classify(line):
    etype, comp, reason = ('', 'unknown', None)
    portal = gateway = user = client_ip = None
    for rx,(e,c,r) in PATTERNS:
        if rx.search(line):
            etype, comp, reason = e, c, r
            break
    pm = PORTAL_RX.search(line);  portal = pm.group('portal') if pm else None
    gm = GW_RX.search(line);      gateway = gm.group('gateway') if gm else None
    um = USER_RX.search(line);    user = um.group('user') if um else None
    im = IPV4_RX.search(line);    client_ip = im.group(0) if im else None
    return etype or 'error', comp, reason, portal, gateway, user, client_ip

def iter_zip_text(zf, name):
    with zf.open(name) as f:
        data = f.read()
    for enc in ('utf-8','utf-16','cp1252','latin-1'):
        try:
            text = data.decode(enc, errors='ignore')
            break
        except Exception:
            continue
    for line in io.StringIO(text):
        yield line.rstrip('\r\n')

def stream_events_from(zf, fname):
    for line in iter_zip_text(zf, fname):
        ts = parse_ts(line)
        if not ts:
            continue
        sev = 'INFO' if 'INFO' in line.upper() else ('ERROR' if 'ERR' in line.upper() else 'WARN' if 'WARN' in line.upper() else '')
        etype, comp, reason, portal, gateway, user, client_ip = classify(line)
        yield Event(ts, sev, comp, etype, line, portal, gateway, user, client_ip, reason, fname)

def sessionize(events, idle_gap=timedelta(seconds=90)):
    sessions = []
    cur = None
    sid = 0
    def close(reason=None, detail=None):
        nonlocal cur
        if cur:
            cur.end_ts = cur.end_ts or (cur.events[-1].ts if cur.events else cur.start_ts)
            if reason and not cur.fail_reason:
                cur.fail_reason = reason
            if detail and not cur.fail_detail:
                cur.fail_detail = detail[:300]
            if cur.outcome == 'unknown' and cur.fail_reason:
                cur.outcome = 'fail'
            sessions.append(cur)
            cur = None

    last_ts = None
    for ev in events:
        if not cur or (last_ts and ev.ts - last_ts > idle_gap) or ev.etype in ('portal_connect_start','auth_start','tls_handshake_start'):
            close()
            sid += 1
            cur = Session(session_id=sid, start_ts=ev.ts)
        last_ts = ev.ts
        cur.events.append(ev)
        # Fill session fields
        cur.portal = cur.portal or ev.portal
        cur.gateway = cur.gateway or ev.gateway
        cur.user = cur.user or ev.user
        cur.client_ip = cur.client_ip or ev.client_ip
        # Phase timers
        if ev.etype == 'portal_connect_start':
            cur.phase_start['portal'] = ev.ts
        if ev.etype == 'portal_connect_success' and cur.phase_start.get('portal'):
            cur.phase_ms['portal'] = int((ev.ts - cur.phase_start['portal']).total_seconds()*1000)
        if ev.etype == 'auth_start':
            cur.phase_start['auth'] = ev.ts
        if ev.etype == 'auth_success' and cur.phase_start.get('auth'):
            cur.phase_ms['auth'] = int((ev.ts - cur.phase_start['auth']).total_seconds()*1000)
        if ev.etype == 'gateway_select_success':
            cur.phase_ms['gateway'] = cur.phase_ms.get('gateway') or int((ev.ts - cur.start_ts).total_seconds()*1000)
        if ev.etype == 'tunnel_up':
            cur.phase_ms['tunnel'] = int((ev.ts - cur.start_ts).total_seconds()*1000)
            cur.outcome = 'success'
            cur.end_ts = ev.ts
        if ev.etype in ('auth_fail','portal_connect_fail','tls_handshake_fail','gateway_select_fail'):
            cur.fail_reason = cur.fail_reason or ev.reason or ('network' if 'timeout' in ev.msg.lower() else 'unknown')
            cur.fail_detail = cur.fail_detail or ev.msg[:300]
            cur.outcome = 'fail'
            cur.end_ts = ev.ts
        if ev.etype == 'reconnect':
            cur.reconnects += 1
    close()
    return sessions

def redact_value(v):
    if not v: return v
    # lightweight reversible-ish hash: keep first/last, mask middle
    if len(v) <= 3: return '*'*len(v)
    return v[0] + '*'*(len(v)-2) + v[-1]

def main():
    ap = argparse.ArgumentParser(description="Sift GlobalProtect PanGP logs in a .zip")
    ap.add_argument("--zip", required=True, help="Path to GlobalProtect log bundle .zip")
    ap.add_argument("--since", help="Only include events on/after this time (e.g., 2025-08-01 00:00)")
    ap.add_argument("--until", help="Only include events before this time")
    ap.add_argument("--export-events", help="Write NDJSON or JSON array depending on extension (.ndjson or .json)")
    ap.add_argument("--export-sessions", help="Write sessions CSV")
    ap.add_argument("--redact", action="store_true", help="Redact usernames/IPs/hostnames")
    args = ap.parse_args()

    tmin = dtparse.parse(args.since) if (args.since and dtparse) else None
    tmax = dtparse.parse(args.until) if (args.until and dtparse) else None

    wanted = {'pangps.txt','pangpa.txt','pangpa.log.old','panplapprovider.txt','pan_gp_event.txt'}
    events = []

    with zipfile.ZipFile(args.zip) as zf:
        names = {n:n for n in zf.namelist()}  # original case
        # Collect candidate logs in a stable order
        ordered = [n for n in names if n.lower().split('/')[-1] in wanted]
        if not ordered:
            # fallback: try to find PanGPS.txt anywhere
            ordered = [n for n in names if n.lower().endswith('pangps.txt')]
        for name in sorted(ordered, key=lambda s: s.lower()):
            for ev in stream_events_from(zf, name):
                if tmin and ev.ts < tmin: 
                    continue
                if tmax and ev.ts >= tmax: 
                    continue
                events.append(ev)

    events.sort(key=lambda e: e.ts)
    sessions = sessionize(events)

    # Summary
    attempts = len(sessions)
    successes = sum(1 for s in sessions if s.outcome == 'success')
    failures = attempts - successes
    connect_ms = [s.phase_ms.get('tunnel') for s in sessions if s.phase_ms.get('tunnel') is not None]
    p50 = (sorted(connect_ms)[len(connect_ms)//2]/1000.0) if connect_ms else None
    reasons = Counter(s.fail_reason for s in sessions if s.fail_reason)

    print(f"Attempts: {attempts} | Success: {successes} ({(successes/attempts*100 if attempts else 0):.1f}%) | Failures: {failures}")
    if p50 is not None:
        print(f"Median time-to-connect: {p50:.2f}s (n={len(connect_ms)})")
    if reasons:
        top = ', '.join(f"{r}({c})" for r,c in reasons.most_common(5))
        print(f"Top failure reasons: {top}")

    # Pretty print last N sessions (up to 3)
    for s in sessions[-3:]:
        u = redact_value(s.user) if args.redact else (s.user or '')
        p = redact_value(s.portal) if args.redact else (s.portal or '')
        g = redact_value(s.gateway) if args.redact else (s.gateway or '')
        ip = redact_value(s.client_ip) if args.redact else (s.client_ip or '')
        dur = (s.end_ts - s.start_ts).total_seconds() if (s.end_ts and s.start_ts) else None
        print("\n--- Session #{sid} {outcome} ---".format(sid=s.session_id, outcome=s.outcome.upper()))
        print(f"Start: {s.start_ts}  End: {s.end_ts}  Duration: {dur:.2f}s" if dur is not None else f"Start: {s.start_ts}")
        print(f"User: {u}  Portal: {p}  Gateway: {g}  Assigned IP: {ip}")
        print(f"Reconnects: {s.reconnects}  Phase ms: {s.phase_ms}")
        if s.outcome == 'fail':
            print(f"Fail reason: {s.fail_reason}  Detail: {s.fail_detail}")

    # Exports
    if args.export_events:
        if args.export_events.lower().endswith('.ndjson'):
            with open(args.export_events,'w',encoding='utf-8') as f:
                for ev in events:
                    d = asdict(ev)
                    if args.redact:
                        for k in ('user','portal','gateway','client_ip'):
                            d[k] = redact_value(d[k])
                    f.write(json.dumps(d, default=str) + "\n")
        else:
            with open(args.export_events,'w',encoding='utf-8') as f:
                arr = []
                for ev in events:
                    d = asdict(ev)
                    if args.redact:
                        for k in ('user','portal','gateway','client_ip'):
                            d[k] = redact_value(d[k])
                    arr.append(d)
                json.dump(arr, f, ensure_ascii=False, indent=2, default=str)

    if args.export_sessions:
        with open(args.export_sessions,'w',newline='',encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=[
                'session_id','start_ts','end_ts','outcome','fail_reason','fail_detail',
                'portal','gateway','user','client_ip','reconnects','portal_ms','auth_ms','gateway_ms','tunnel_ms'
            ])
            w.writeheader()
            for s in sessions:
                row = {
                    'session_id': s.session_id,
                    'start_ts': s.start_ts, 'end_ts': s.end_ts, 'outcome': s.outcome,
                    'fail_reason': s.fail_reason, 'fail_detail': s.fail_detail,
                    'portal': redact_value(s.portal) if args.redact else s.portal,
                    'gateway': redact_value(s.gateway) if args.redact else s.gateway,
                    'user': redact_value(s.user) if args.redact else s.user,
                    'client_ip': redact_value(s.client_ip) if args.redact else s.client_ip,
                    'reconnects': s.reconnects,
                    'portal_ms': s.phase_ms.get('portal'),
                    'auth_ms': s.phase_ms.get('auth'),
                    'gateway_ms': s.phase_ms.get('gateway'),
                    'tunnel_ms': s.phase_ms.get('tunnel'),
                }
                w.writerow(row)

if __name__ == "__main__":
    main()
