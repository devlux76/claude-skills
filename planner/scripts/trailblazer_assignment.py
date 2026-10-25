"""Model-free supervisor for explicit planner-to-Trailblazer assignments."""
import argparse
import contextlib
from datetime import datetime, timedelta, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time


def command(argv, check=True, combined=False, timeout=None, **kwargs):
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=True, **kwargs) as child:
        try:
            out, err = child.communicate(timeout=timeout)
        except BaseException:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            child.communicate()
            raise
        if check and child.returncode:
            raise ValueError((err or out or f"command exited {child.returncode}")[-1600:])
        return out+err if combined else out


def configuration(path):
    value = json.loads(path.read_text())
    for key in ("vortex_command", "case_command"):
        if not isinstance(value.get(key), list) or not value[key] or not all(isinstance(x, str) for x in value[key]):
            raise ValueError(f"dispatch config needs {key} as a command array")
    if not value.get("peer") or not value.get("vortex_dir"):
        raise ValueError("dispatch config needs the admitted peer and owner-local VORTEX directory")
    seconds = float(value.get("deadline_seconds", 4*60*60))
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("assignment deadline_seconds must be positive and finite")
    value["deadline_seconds"] = seconds
    return value


def remaining(config):
    seconds = config["_deadline"]-time.monotonic()
    if seconds <= 0:
        raise TimeoutError("assignment deadline reached")
    return seconds


def validate(repo, check, files, config):
    if check not in config.get("repos", {}).get(str(repo), []):
        raise ValueError("repository/check is not admitted in the local dispatch configuration")
    manifest = subprocess.run(["git", "-C", str(repo), "show", "HEAD:mix.exs"], capture_output=True, text=True)
    if repo.name == "trailblazer" or re.search(r"\bapp:\s*:trailblazer\b", manifest.stdout):
        raise ValueError("Trailblazer self-repair is forbidden")
    for name in files:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("task files must be repository-relative paths")


def process_identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()+":"+fields[19]
    except (OSError, IndexError):
        return None


def launch(args, ref, job_id):
    logs = args.state_dir/"assignments"
    logs.mkdir(mode=0o700, exist_ok=True)
    with (logs/(job_id+".log")).open("a") as output:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
            "--ref", ref, "--repos-file", str(args.repos_file.resolve()),
            "--state-dir", str(args.state_dir.resolve()), "--config", str(args.dispatch_config.resolve())],
            stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True,
            close_fds=True)
    return child.pid


@contextlib.contextmanager
def state(args):
    with (args.state_dir/"lock").open("a") as lock, contextlib.closing(sqlite3.connect(args.state_dir/"board.sqlite3")) as db:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield db


def update(args, **changes):
    with state(args) as db:
        job = json.loads(db.execute("SELECT data FROM assignments WHERE ref=?", (args.ref,)).fetchone()[0])
        job.update(changes)
        with db:
            db.execute("UPDATE assignments SET data=? WHERE ref=?", (json.dumps(job), args.ref))
        return job


def planner(args, action, text=None):
    argv = [sys.executable, str(Path(__file__).with_name("planner.py")),
            "--actor", "trailblazer", "--repos-file", str(args.repos_file),
            "--state-dir", str(args.state_dir), action, args.ref]
    return command(argv+(["--evidence", text] if action == "done" else [text] if text is not None else []))


def owned(args):
    card = json.loads(planner(args, "show"))
    if card["column"] != "doing" or not card.get("claim") or card["claim"]["actor"] != "trailblazer":
        raise ValueError("assignment is no longer active and owned by trailblazer")


def vortex(config, op, *args):
    result = json.loads(command(config["vortex_command"]+[op, "--dir", config["vortex_dir"], *args],
                                check=op != "wait", timeout=remaining(config)))
    if op == "wait" and result.get("error") == "wait timed out":
        return {"events": [], "cursor": int(args[args.index("--after")+1])}
    if result.get("error"):
        raise ValueError(result["error"])
    return result


def send(config, message):
    body = "From Codex, not typed by the operator:\n"+json.dumps(message)
    if len(body.encode()) > 16384:
        raise ValueError("task card exceeds the VORTEX envelope limit; narrow the assignment")
    result = vortex(config, "send", "--peer", config["peer"], "--text", body)
    if not result.get("sent"):
        raise ValueError("VORTEX did not confirm the transport write")


def envelope(job, kind, payload):
    return {"protocol":"trailblazer/1", "type":kind, "id":job["id"]+":"+kind,
            "request_id":job["id"], "payload":payload}


def admitted(args, job, config):
    cursor = 0
    while True:
        page = vortex(config, "read", "--after", str(cursor))
        cursor = page["cursor"]
        if not page.get("events"):
            break
    request = (job["card"]["title"][:100]+" bug:"+job["ref"].split(":")[1]+"\n\n"+
               job["card"]["body"]+"\n\nCurrent checkpoints:\n"+"\n".join(job["card"]["recent"]))
    payload = {"repo":job["repo"], "request":request, "check":job["check"], "files":job["files"],
               "design":["Current planner card "+job["ref"]+". The assignment supervisor owns planner checkpoints. "
                         "Return a checked candidate; never merge or push. Commit messages must cite this repository's issue and fit 255 characters."]}
    update(args, state="sending")
    send(config, envelope(job, "task", payload))
    update(args, state="waiting_admission")
    while True:
        page = vortex(config, "wait", "--after", str(cursor), "--for", "message", "--timeout", "60")
        cursor = page["cursor"]
        for event in page.get("events", []):
            if event.get("peer") != config["peer"] or event.get("kind") != "message":
                continue
            try:
                message = json.loads(event["body"].split("\n",1)[1])
            except (ValueError, KeyError, IndexError):
                continue
            if message.get("protocol") != "trailblazer/1" or message.get("request_id") != job["id"]:
                continue
            if message.get("type") == "rejected":
                raise ValueError("Trailblazer rejected the assigned task")
            if message.get("type") == "accepted":
                send(config, envelope(job, "receipt", {"message_id":message["id"]}))
                return message["payload"]["case"]


def verify(job, report, config):
    commit = report.get("commit", "")
    branch = "trailblazer/"+report["case"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit or "") or report.get("branch") != branch:
        raise ValueError("verification requires the assigned case's committed candidate")
    actual = command(["git", "-C", job["repo"], "rev-parse", "refs/heads/"+branch]).strip()
    if actual != commit:
        raise ValueError("verification candidate does not match the repository's case branch")
    with tempfile.TemporaryDirectory(prefix="planner-verification-") as root:
        worktree = Path(root)/"candidate"
        command(["git", "-C", job["repo"], "worktree", "add", "--detach", str(worktree), commit])
        try:
            for name in ("node_modules", "deps"):
                source = Path(job["repo"])/name
                if source.is_dir() and not (worktree/name).exists():
                    (worktree/name).symlink_to(source, target_is_directory=True)
            try:
                output = command(["bash", "-c", job["check"]], cwd=worktree,
                                 combined=True, timeout=remaining(config))
            except ValueError as error:
                raise ValueError("independent verification failed: "+str(error).replace(str(worktree), "<verification-worktree>")) from None
            dirty = command(["git", "-C", str(worktree), "status", "--porcelain", "--untracked-files=no"])
            if dirty:
                raise ValueError("verification changed tracked candidate files")
            return ("Independent verification passed (exit 0): "+job["check"]+". Candidate "+commit+
                    "; not merged. "+output[-900:])
        finally:
            command(["git", "-C", job["repo"], "worktree", "remove", "--force", str(worktree)])


def run(args):
    with state(args) as db:
        row = db.execute("SELECT data FROM assignments WHERE ref=?", (args.ref,)).fetchone()
        if not row:
            raise ValueError("no durable assignment")
        job = json.loads(row[0])
        if job["state"] != "assigned":
            return
        job["state"] = "running"
        with db:
            db.execute("UPDATE assignments SET data=? WHERE ref=?", (json.dumps(job), args.ref))
    try:
        config = configuration(args.config)
        config["_deadline"] = time.monotonic()+config["deadline_seconds"]
        config["_deadline_label"] = (datetime.now(timezone.utc)+timedelta(seconds=config["deadline_seconds"])).strftime("%Y-%m-%d %H:%M:%S UTC")
        update(args, deadline=config["_deadline_label"])
        validate(Path(job["repo"]), job["check"], job["files"], config)
        owned(args)
        planner(args, "note", "Intent: dispatch through the VORTEX resource gate; await checked candidate. Deadline: "+config["_deadline_label"]+".")
        case = admitted(args, job, config)
        update(args, state="working", case=case)
        planner(args, "note", "Result: Trailblazer accepted the assignment. Next: independently verify its candidate.")
        report = json.loads(command(config["case_command"]+["case", case, "--follow"], timeout=remaining(config)))
        if report.get("case") != case or report.get("status") != "fixed":
            raise ValueError("Trailblazer did not return a fixed candidate: "+str(report.get("summary",report.get("status"))))
        owned(args)
        evidence = verify(job, report, config)
        owned(args)
        planner(args, "done", evidence)
        update(args, state="done", commit=report["commit"])
    except BaseException as error:
        if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
            reason = "No admission/result by "+config["_deadline_label"]+" (assignment deadline); investigate the existing case"
        else:
            reason = str(error).replace(str(Path.home()), "~") or "assignment supervisor interrupted"
        update(args, state="blocked", reason=reason)
        planner(args, "block", reason+". Reconcile explicitly; no automatic retry.")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("ref", "repos-file", "state-dir", "config"):
        parser.add_argument("--"+name, required=True, type=str if name=="ref" else Path)
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt("assignment supervisor stopped")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        run(parser.parse_args())
    except (ValueError, OSError, KeyboardInterrupt) as error:
        print(json.dumps({"error":str(error)}), file=sys.stderr)
        sys.exit(1)
