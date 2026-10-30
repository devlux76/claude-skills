"""Checked launch with explicit token budgets and observation through completion."""
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
CLEANUP = Path(__file__).with_name("case_cleanup.py")

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
    unless record.task["reasoning_budget_tokens"] == __THINKING__, do: raise("thinking budget mismatch")
    :persistent_term.put(key, %{profile | case: id})
    :ok = Trailblazer.Planner.Companion.observe(id)
    :ok = Trailblazer.Loop.CaseRecord.event(id, :attempt, %{stage: :supervision_policy, max_tokens: 4096, check_interval_seconds: 1800, read_rounds: __ROUNDS__, reasoning_budget_tokens: __THINKING__})
  _ -> raise("trial profile ownership mismatch")
end
IO.puts("exact case bound")
'''


def launch(ref, check, files, read_rounds, reasoning_tokens):
    if type(read_rounds) is not int or not 0 <= read_rounds <= 6:
        raise ValueError("read_rounds must be 0..6")
    if type(reasoning_tokens) is not int or not 0 <= reasoning_tokens < 4096:
        raise ValueError("reasoning tokens must be 0..4095, leaving room for edits")
    if not CLEANUP.is_file():
        raise ValueError("native cleanup observer missing; no admission attempted")
    env = os.environ | {"RELEASE_DISTRIBUTION": "name", "RELEASE_NODE": "trailblazer@127.0.0.1",
                        "ERL_EPMD_ADDRESS": "127.0.0.1", "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
                        "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{os.getuid()}/bus"}
    def run(argv, timeout=40):
        return subprocess.run(argv, check=True, capture_output=True, text=True, env=env, cwd=ROOT, timeout=timeout)
    owner = uuid.uuid4().hex
    run([str(RELEASE), "rpc", PREPARE.replace("__OWNER__", owner)])
    # A failed preparation raises above: it cannot fall through to admission.
    argv = [str(PLANNER), "--actor", "codex", "assign", ref, "trailblazer", "--check", check,
            "--read-rounds", str(read_rounds),
            "--reasoning-tokens", str(reasoning_tokens)]
    for path in files:
        argv += ["--file", path]
    result = json.loads(run(argv, timeout=90).stdout)
    case = result["case"]
    if result.get("dispatched") is not True or not re.fullmatch(r"vortex-[0-9a-f]{64}", case):
        raise ValueError("fresh admission not confirmed; reconcile existing assignment/profile")
    print(json.dumps({"admitted_case": case}), file=sys.stderr, flush=True)
    code = BIND.replace("__CASE__", case).replace("__OWNER__", owner).replace("__ROUNDS__", str(read_rounds)).replace("__THINKING__", str(reasoning_tokens))
    run([str(RELEASE), "rpc", code])
    unit = "trailblazer-cleanup-" + case.removeprefix("vortex-")[:12]
    run([str(SYSTEMD_RUN), "--user", "--unit=" + unit, "--collect", "--property=Type=exec",
         sys.executable, str(CLEANUP), case])
    return result | {"cleanup_unit": unit, "check_interval_seconds": 1800, "output_cap": 4096, "read_rounds": read_rounds, "reasoning_budget_tokens": reasoning_tokens}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ref")
    parser.add_argument("--check", required=True)
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--read-rounds", type=int, required=True)
    parser.add_argument("--reasoning-tokens", type=int, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(launch(args.ref, args.check, args.file, args.read_rounds, args.reasoning_tokens)))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        print(json.dumps({"error": "Launch stopped. Reconcile the recorded assignment/profile before retrying.",
                          "detail": detail[-2000:]}), file=sys.stderr)
        sys.exit(1)
