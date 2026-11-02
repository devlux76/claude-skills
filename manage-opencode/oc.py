#!/usr/bin/env python3
"""oc.py: watch and drive our OpenCode server (2.x API, http://127.0.0.1:4096).

  oc.py status                       server, running sessions, pending forms/permissions, update status
  oc.py monitor [--stall-min N]      red-flag check of the open assignment (exit 20 = attention)
  oc.py sessions [--limit N] [--dir D]
  oc.py show SID [--last N]          recent turns: text, tool calls, errors
  oc.py new --dir D [--title T] [--model PROV/ID] TEXT|@FILE   create a session and queue a prompt
  oc.py say SID TEXT|@FILE [--steer] queue a prompt (or steer the running turn)
  oc.py interrupt SID
  oc.py wait SID [--timeout S]       block until the session stops running or asks something (exit 0 idle, 10 form, 11 permission, 3 timeout)
  oc.py forms [SID] | answer SID FORMID FIELD=VALUE...
  oc.py permissions [SID] | allow SID REQID [--always] | deny SID REQID [MESSAGE]
  oc.py update                       daily fork update status (opencode-update)

Auth: none by default (loopback server, OPENCODE_SERVER_AUTH=disabled); OPENCODE_PASSWORD or server.env if one is set. Exit 1 on HTTP errors.
"""
import argparse, base64, json, os, re, sys, time, urllib.error, urllib.request

URL = os.environ.get("OPENCODE_URL", "http://127.0.0.1:4096")
ENVFILE = os.path.expanduser("~/.config/opencode-local/server.env")
ASSIGNMENT = os.path.expanduser("~/.local/share/claude-handoff/opencode-assignment.json")
UPDATE_STATUS = os.path.expanduser("~/.local/state/opencode-local/status.json")

RED_TEXT = [
    (re.compile(r"hidden (grader|test)|grader will|the grader|benchmark.*hidden", re.I),
     "believes in hidden tests/grader: steer (it designs the API and writes the tests)"),
    (re.compile(r"free usage|usage limit|rate.?limit|subscribe to (opencode )?go", re.I),
     "quota or rate limit: queue the work, do not absorb it"),
]
RED_CMD = [
    (re.compile(r"\bfind\s+/(\s|$)|grep\s+-[a-zA-Z]*r[a-zA-Z]*\s+\S+\s+/(\s|$)"), "whole-disk search: interrupt, read only the named repo"),
    (re.compile(r"\bgit\s+stash\b"), "git stash (shared across worktrees)"),
    (re.compile(r"\bgit\s+(push|merge|reset --hard)\b"), "push/merge/reset --hard (not its job)"),
    (re.compile(r"systemctl\s+(--user\s+)?(restart|stop)|hot-load"), "service restart/hot-load (not its job)"),
]


def password():
    pw = os.environ.get("OPENCODE_PASSWORD")
    if pw:
        return pw
    try:
        for line in open(ENVFILE):
            if line.startswith("OPENCODE_PASSWORD="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None  # our server runs without a password (OPENCODE_SERVER_AUTH=disabled)


PW = password()
AUTH = {"authorization": "Basic " + base64.b64encode(f"opencode:{PW}".encode()).decode()} if PW else {}


class CallError(Exception):
    """A failed request, raised instead of exiting when the caller asked for soft=True."""
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def call(method, path, body=None, ok=(200,), soft=False):
    req = urllib.request.Request(URL + path, method=method, headers={**AUTH, "content-type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if e.code in ok:
            return None
        err = CallError(f"{method} {path} -> {e.code}: {e.read()[:300].decode(errors='replace')}", e.code)
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            err = CallError(f"OpenCode server unresponsive at {URL}: {method} {path} timed out (journalctl --user -u opencode)")
        else:
            err = CallError(f"OpenCode server unreachable at {URL}: {e.reason} (systemctl --user status opencode)")
    except TimeoutError:
        # urlopen raises a bare socket timeout (not URLError) when a connected server stops answering
        err = CallError(f"OpenCode server unresponsive at {URL}: {method} {path} timed out (journalctl --user -u opencode)")
    if soft:
        raise err
    sys.exit(str(err))


def text_of(arg):
    return open(arg[1:]).read() if arg.startswith("@") else arg


def ago(ms):
    s = max(0, time.time() - ms / 1000)
    return f"{int(s)}s" if s < 120 else f"{int(s // 60)}m" if s < 7200 else f"{s / 3600:.1f}h"


def active():
    return call("GET", "/api/session/active")["data"]


def pending(kind, sid):
    return call("GET", f"/api/session/{sid}/{kind}")["data"]


def messages(sid, limit=30):
    return call("GET", f"/api/session/{sid}/message?limit={limit}")["data"]  # newest first


def tool_arg(part):
    inp = (part.get("state") or {}).get("input") or {}
    return inp.get("command") or inp.get("filePath") or inp.get("path") or inp.get("pattern") or json.dumps(inp)[:120]


def describe(m):
    t = m.get("type")
    if t == "user":
        return [f"USER: {m.get('text', '')[:300]}"]
    if t == "assistant":
        out = []
        for c in m.get("content") or []:
            if c.get("type") == "text":
                out.append(f"SAYS: {c['text'][:400]}")
            elif c.get("type") == "tool":
                out.append(f"TOOL {c.get('name')} [{(c.get('state') or {}).get('status')}]: {str(tool_arg(c))[:200]}")
        if m.get("error"):
            out.append(f"ERROR: {m['error'].get('message')}")
        return out
    if m.get("error"):
        return [f"{t.upper()}: {m.get('outcome', '')} {m['error'].get('message')}"]
    return []


def cmd_status(a):
    run = active()
    recent = call("GET", "/api/session?limit=8")["data"]
    print(f"server {URL} | running: {', '.join(run) or 'none'}")
    for s in recent:
        sid = s["id"]
        flags = []
        for kind in ("form", "permission"):
            try:
                n = len(call("GET", f"/api/session/{sid}/{kind}", soft=True)["data"])
            except CallError as e:
                # one bad session (e.g. its worktree was deleted -> 404 LocationNotFound) must not hide the rest
                flags.append("location missing" if e.code == 404 else f"{kind} check failed: {str(e)[:80]}")
                break
            if n:
                flags.append(f"{n} {kind}")
        state = "RUNNING" if sid in run else "idle"
        print(f"  {sid} {state:7} {ago(s['time']['updated']):>5} ago  {s.get('title', '')[:60]}  "
              f"[{(s.get('location') or {}).get('directory', '?')}] {' '.join(flags)}")
    cmd_update(a)


def cmd_sessions(a):
    q = f"/api/session?limit={a.limit}" + (f"&directory={urllib.request.quote(a.dir)}" if a.dir else "")
    for s in call("GET", q)["data"]:
        m = s.get("model") or {}
        print(f"{s['id']} {ago(s['time']['updated']):>5} ago {m.get('providerID')}/{m.get('id')} "
              f"{s.get('title', '')[:60]} [{(s.get('location') or {}).get('directory', '?')}]")


def cmd_show(a):
    for m in reversed(messages(a.sid, a.last)):
        for line in describe(m):
            print(f"{ago(m['time']['created']):>5} {line}")


def cmd_new(a):
    body = {"title": a.title, "location": {"directory": os.path.abspath(a.dir)}}
    if a.model:
        prov, _, mid = a.model.partition("/")
        body["model"] = {"providerID": prov, "id": mid}
    sid = call("POST", "/api/session", body)["data"]["id"]
    call("POST", f"/api/session/{sid}/prompt", {"text": text_of(a.text), "delivery": "queue"})
    print(sid)


def cmd_say(a):
    call("POST", f"/api/session/{a.sid}/prompt", {"text": text_of(a.text), "delivery": "steer" if a.steer else "queue"})
    print("queued" if not a.steer else "steering")


def cmd_interrupt(a):
    call("POST", f"/api/session/{a.sid}/interrupt")
    print("interrupted")


def cmd_wait(a):
    """Event-driven: re-check on each session event; the timeout is a backstop."""
    deadline = time.time() + a.timeout
    while True:
        if pending("form", a.sid):
            print("waiting on a form: oc.py forms " + a.sid); sys.exit(10)
        if pending("permission", a.sid):
            print("waiting on a permission: oc.py permissions " + a.sid); sys.exit(11)
        if a.sid not in active():
            print("idle"); sys.exit(0)
        left = deadline - time.time()
        if left <= 0:
            print("still running"); sys.exit(3)
        req = urllib.request.Request(URL + "/api/event", headers={**AUTH, "accept": "text/event-stream"})
        try:
            with urllib.request.urlopen(req, timeout=left) as stream:
                for raw in stream:
                    line = raw.decode(errors="replace")
                    if line.startswith("data:") and a.sid in line and re.search(
                            r'"type":"(session\.(idle|execution\.\w+)|form\.\w+|permission\.\w+)', line):
                        break
        except (TimeoutError, OSError):
            pass


def cmd_forms(a):
    sids = [a.sid] if a.sid else list(active()) + [s["id"] for s in call("GET", "/api/session?limit=8")["data"]]
    for sid in dict.fromkeys(sids):
        for f in pending("form", sid):
            print(f"{sid} {f['id']}: {f['title']}")
            print("   fields: " + json.dumps(f.get("fields"))[:600])


def cmd_answer(a):
    answer = {}
    for kv in a.fields:
        k, _, v = kv.partition("=")
        answer[k] = json.loads(v) if v[:1] in "[{" or v in ("true", "false") else v
    call("POST", f"/api/session/{a.sid}/form/{a.form}/reply", {"answer": answer})
    print("answered")


def cmd_permissions(a):
    sids = [a.sid] if a.sid else list(active()) + [s["id"] for s in call("GET", "/api/session?limit=8")["data"]]
    for sid in dict.fromkeys(sids):
        for p in pending("permission", sid):
            print(f"{sid} {p.get('id')}: {json.dumps(p)[:400]}")


def cmd_allow(a):
    call("POST", f"/api/session/{a.sid}/permission/{a.req}/reply", {"decision": "always" if a.always else "once"})
    print("allowed")


def cmd_deny(a):
    call("POST", f"/api/session/{a.sid}/permission/{a.req}/reply", {"decision": "reject", "message": a.message})
    print("denied")


def cmd_update(a):
    try:
        s = json.load(open(UPDATE_STATUS))
        print(f"fork update: {s['result']} at {s['time']}: {s['message']} (current {s['current']})")
    except OSError:
        print("fork update: no status yet (opencode-update has not run)")


def cmd_monitor(a):
    alerts, run = [], active()
    job = None
    try:
        job = json.load(open(ASSIGNMENT))
    except (OSError, ValueError):
        pass
    if job and not job.get("done") and job.get("parked"):
        print(f"assignment PARKED ({job['parked']}): {job.get('task')}")
    elif job and not job.get("done"):
        age = time.time() - float(job.get("dispatched", time.time()))
        print(f"assignment: {job.get('task')} | worktree {job.get('worktree')} | {int(age // 60)}m ago")
        if not run:
            alerts.append("assignment open but nothing is running: read its last turn (oc.py show), then re-steer or mark done")
        wt = job.get("worktree")
        if wt and not os.path.isdir(wt) and age > a.stall_min * 60:
            alerts.append(f"assigned worktree {wt} still missing after {int(age // 60)}m")
    else:
        print("no open assignment")
    if len(run) > 1:
        # Free service: concurrent sessions (including OpenCode's own subagents) risk a ban.
        alerts.append(f"{len(run)} sessions RUNNING at once ({', '.join(run)}): parallel use risks a ban; "
                      "steer the parent to run subagents one at a time, interrupt extras")
    for sid in run or [s["id"] for s in call("GET", "/api/session?limit=1")["data"]]:
        try:
            for kind in ("form", "permission"):
                if call("GET", f"/api/session/{sid}/{kind}", soft=True)["data"]:
                    alerts.append(f"{sid}: pending {kind} (oc.py {kind}s {sid})")
            ms = call("GET", f"/api/session/{sid}/message?limit=30", soft=True)["data"]
        except CallError as e:
            # one unreadable session (e.g. deleted worktree) must not hide the other alerts
            alerts.append(f"{sid}: " + ("location missing (worktree deleted?)" if e.code == 404 else f"check failed: {str(e)[:100]}"))
            continue
        last = max((m["time"].get("completed") or m["time"]["created"] for m in ms), default=0)
        if sid in run and last and time.time() - last / 1000 > a.stall_min * 60:
            alerts.append(f"{sid}: running but no new message for {ago(last)}: read it, interrupt + steer")
        cmds = []
        for m in ms:
            for c in m.get("content") or []:
                txt = c.get("text") or ""
                for rx, why in RED_TEXT:
                    if rx.search(txt):
                        alerts.append(f"{sid}: {why}")
                if c.get("type") == "tool":
                    arg = str(tool_arg(c))
                    cmds.append(arg)
                    for rx, why in RED_CMD:
                        if rx.search(arg):
                            alerts.append(f"{sid}: {why}: {arg[:120]}")
            if m.get("error"):
                for rx, why in RED_TEXT:
                    if rx.search(m["error"].get("message", "")):
                        alerts.append(f"{sid}: {why}")
        if len(cmds) >= 6 and len(set(cmds[:6])) <= 2:
            alerts.append(f"{sid}: same command repeated: {cmds[0][:100]}")
    for line in dict.fromkeys(alerts):
        print("ATTENTION " + line)
    sys.exit(20 if alerts else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("monitor"); p.add_argument("--stall-min", type=int, default=15); p.set_defaults(fn=cmd_monitor)
    p = sub.add_parser("sessions"); p.add_argument("--limit", type=int, default=15); p.add_argument("--dir"); p.set_defaults(fn=cmd_sessions)
    p = sub.add_parser("show"); p.add_argument("sid"); p.add_argument("--last", type=int, default=12); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("new"); p.add_argument("--dir", required=True); p.add_argument("--title", default="Claude task")
    p.add_argument("--model"); p.add_argument("text"); p.set_defaults(fn=cmd_new)
    p = sub.add_parser("say"); p.add_argument("sid"); p.add_argument("text"); p.add_argument("--steer", action="store_true"); p.set_defaults(fn=cmd_say)
    p = sub.add_parser("interrupt"); p.add_argument("sid"); p.set_defaults(fn=cmd_interrupt)
    p = sub.add_parser("wait"); p.add_argument("sid"); p.add_argument("--timeout", type=float, default=1800); p.set_defaults(fn=cmd_wait)
    p = sub.add_parser("forms"); p.add_argument("sid", nargs="?"); p.set_defaults(fn=cmd_forms)
    p = sub.add_parser("answer"); p.add_argument("sid"); p.add_argument("form"); p.add_argument("fields", nargs="+"); p.set_defaults(fn=cmd_answer)
    p = sub.add_parser("permissions"); p.add_argument("sid", nargs="?"); p.set_defaults(fn=cmd_permissions)
    p = sub.add_parser("allow"); p.add_argument("sid"); p.add_argument("req"); p.add_argument("--always", action="store_true"); p.set_defaults(fn=cmd_allow)
    p = sub.add_parser("deny"); p.add_argument("sid"); p.add_argument("req"); p.add_argument("message", nargs="?"); p.set_defaults(fn=cmd_deny)
    sub.add_parser("update").set_defaults(fn=cmd_update)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
