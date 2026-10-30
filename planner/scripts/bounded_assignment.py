"""Checked launcher for the operator's existing 4096-token, at-most-30min trial."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path.home() / "projects/trailblazer"
RELEASE = ROOT / "_build/prod/rel/trailblazer/bin/trailblazer"
PLANNER = Path.home() / ".local/bin/planner"
SYSTEMD_RUN = "systemd-run"
WATCHDOG = Path.home() / ".local/state/planner/trials/bounded_case_watchdog.py"

PREPARE = '''
key = {:trailblazer, :bounded_smoke_profile}
s = :sys.get_state(Trailblazer.Loop.Runner)
r = :sys.get_state(Trailblazer.Vortex.Resource)
b = Trailblazer.Vortex.Bridge.status()
unless s.active == nil and :queue.is_empty(s.queue) and
       Trailblazer.Loop.CaseRecord.open_cases() == [] and r.held == nil and
       b.active == nil and not b.resource_release_blocked and
       :persistent_term.get(key, nil) == nil, do: raise("work or ownership not idle")
base = String.trim_trailing(Trailblazer.Config.get(:code_model_url), "/v1")
{:ok, response} = Req.get(base <> "/models")
unless response.status == 200 and response.body["data"] != [] and
       Enum.all?(response.body["data"], &(get_in(&1, ["status", "value"]) == "unloaded")),
       do: raise("model work not idle")
previous = Application.fetch_env(:trailblazer, :code_model_max_tokens)
:persistent_term.put(key, %{owner_ref: "__OWNER__", case: nil, previous: previous})
Application.put_env(:trailblazer, :code_model_max_tokens, 4096)
IO.puts("bounded profile prepared")
'''

BIND = '''
id = "__CASE__"
owner = "__OWNER__"
key = {:trailblazer, :bounded_smoke_profile}
case :persistent_term.get(key, nil) do
  %{owner_ref: ^owner, case: nil} = profile ->
    unless Application.get_env(:trailblazer, :code_model_max_tokens) == 4096,
      do: raise("token cap changed externally")
    record = Trailblazer.Loop.CaseRecord.get(id, inline: false)
    unless record.task["read_rounds"] == __ROUNDS__, do: raise("read budget mismatch")
    :persistent_term.put(key, %{profile | case: id})
    Trailblazer.Loop.CaseRecord.event(id, :trial_budget, %{max_tokens: 4096, wall_seconds: __SECONDS__, read_rounds: __ROUNDS__})
  _ -> raise("trial profile ownership mismatch")
end
IO.puts("exact case bound")
'''


def launch(ref, check, files, read_rounds, seconds):
    if type(read_rounds) is not int or not 0 <= read_rounds <= 6 or type(seconds) is not int or not 0 < seconds <= 1800:
        raise ValueError("read_rounds must be 0..6 and wall seconds 1..1800")
    if not WATCHDOG.is_file():
        raise ValueError("native watchdog missing; no admission attempted")
    env = os.environ | {"RELEASE_DISTRIBUTION": "name", "RELEASE_NODE": "trailblazer@127.0.0.1",
                        "ERL_EPMD_ADDRESS": "127.0.0.1", "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
                        "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{os.getuid()}/bus"}
    def run(argv, timeout=40):
        return subprocess.run(argv, check=True, capture_output=True, text=True, env=env, cwd=ROOT, timeout=timeout)
    owner = uuid.uuid4().hex
    run([str(RELEASE), "rpc", PREPARE.replace("__OWNER__", owner)])
    # A failed preparation raises above: it cannot fall through to admission.
    argv = [str(PLANNER), "--actor", "codex", "assign", ref, "trailblazer", "--check", check,
            "--read-rounds", str(read_rounds), "--deadline-seconds", str(seconds)]
    for path in files:
        argv += ["--file", path]
    result = json.loads(run(argv, timeout=90).stdout)
    case = result["case"]
    if result.get("dispatched") is not True or not re.fullmatch(r"vortex-[0-9a-f]{64}", case):
        raise ValueError("fresh admission not confirmed; reconcile existing assignment/profile")
    print(json.dumps({"admitted_case": case}), file=sys.stderr, flush=True)
    code = BIND.replace("__CASE__", case).replace("__OWNER__", owner).replace("__ROUNDS__", str(read_rounds)).replace("__SECONDS__", str(seconds))
    run([str(RELEASE), "rpc", code])
    unit = "trailblazer-bounded-" + case.removeprefix("vortex-")[:12]
    run([str(SYSTEMD_RUN), "--user", "--unit=" + unit, "--collect", "--property=Type=exec",
         sys.executable, str(WATCHDOG), case, str(seconds)])
    return result | {"watchdog_unit": unit, "wall_seconds": seconds, "output_cap": 4096, "read_rounds": read_rounds}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ref")
    parser.add_argument("--check", required=True)
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--read-rounds", type=int, required=True)
    parser.add_argument("--wall-seconds", type=int, default=1800)
    args = parser.parse_args()
    try:
        print(json.dumps(launch(args.ref, args.check, args.file, args.read_rounds, args.wall_seconds)))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        print(json.dumps({"error": "Launch stopped. Reconcile the recorded assignment/profile before retrying.",
                          "detail": detail[-2000:]}), file=sys.stderr)
        sys.exit(1)
