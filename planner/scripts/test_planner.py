"""Behavioral checks against real temporary git-bug repositories."""
import json
import os
from pathlib import Path
import subprocess
import signal
import sqlite3
import sys
import tempfile
import time
import unittest
import trailblazer_assignment

CLI = Path(__file__).with_name("planner.py")


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root/"repo"
        self.repo.mkdir()
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "fixture")
        self.run_git("config", "user.email", "fixture@example.invalid")
        self.run_git("bug", "user", "new", "-n", "fixture", "-e", "fixture@example.invalid", "--non-interactive")
        self.repos = self.root/"repos"
        self.repos.write_text(str(self.repo)+"\n")
        self.base = [sys.executable, str(CLI), "--repos-file", str(self.repos), "--state-dir", str(self.root/"state")]

    def tearDown(self):
        database=self.root/"state/board.sqlite3"
        if database.exists():
            with sqlite3.connect(database) as db:
                rows=db.execute("SELECT data FROM assignments").fetchall()
            for row in rows:
                job=json.loads(row[0])
                pid=job.get("pid")
                if pid and job.get("process") == trailblazer_assignment.process_identity(pid):
                    try:
                        os.killpg(pid,signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        self.tmp.cleanup()

    def run_git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True).stdout

    def call(self, *args, actor="glm", ok=True):
        p = subprocess.run(self.base+["--actor", actor, *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0 if ok else 1, p.stdout+p.stderr)
        return json.loads(p.stdout if ok else p.stderr)

    def card(self, title="fixture task"):
        return self.call("add", "repo", "--title", title, "--plan", "verify the result")["ref"]

    def test_workflow_survives_new_process_and_separates_completion_from_closure(self):
        ref = self.card()
        self.call("start", ref, "--plan", "one bounded task")
        self.call("note", ref, "intent: write marker")
        self.call("note", ref, "result: marker exists; next: verify")
        self.call("block", ref, "quota; wait for operator")
        resumed = self.call("resume")["cards"][0]
        self.assertEqual(resumed["state"], "blocked")
        self.assertIn("marker exists", resumed["notes"][-2]["text"])
        self.call("start", ref, "--plan", "verify marker")
        self.call("done", ref, "--evidence", "marker inspected; focused checks pass")
        self.assertEqual(self.call("show", ref)["column"], "done")
        raw = json.loads(self.run_git("bug", "bug", "show", ref.split(":")[1], "-f", "json"))
        self.assertEqual(raw["status"], "open")
        self.assertEqual(self.call("resume")["cards"], [])

    def test_two_claimants_have_exactly_one_winner(self):
        ref = self.card()
        workers = [subprocess.Popen(self.base+["--actor", actor, "start", ref, "--plan", "claim"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                   for actor in ("worker-a", "worker-b")]
        results = [p.communicate() for p in workers]
        self.assertEqual(sorted(p.returncode for p in workers), [0, 1], results)
        self.assertIn("already owned", "".join(err for _, err in results))

    def test_serial_work_and_explicit_release(self):
        first, second = self.card("first"), self.card("second")
        self.call("start", first, "--plan", "first")
        self.assertIn("active work", self.call("start", second, "--plan", "second", ok=False)["error"])
        self.call("release", first, "handoff: remaining check")
        self.call("start", second, "--plan", "second")
        self.assertEqual(self.call("show", first)["column"], "todo")

    def test_sync_repairs_labels_without_duplicate_comment(self):
        ref = self.card()
        self.call("start", ref, "--plan", "claim")
        before = self.call("show", ref)
        self.run_git("bug", "bug", "label", "rm", ref.split(":")[1], "status:doing")
        self.call("sync", ref)
        after = self.call("show", ref)
        self.assertEqual(after["column"], "doing")
        self.assertEqual(before["recent"], after["recent"])

    def test_completion_requires_nonempty_evidence_and_current_actor(self):
        ref = self.card()
        self.call("start", ref, "--plan", "claim")
        self.call("done", ref, "--evidence", " ", ok=False)
        self.call("done", ref, "--evidence", "claimed result", actor="other", ok=False)
        self.assertEqual(self.call("show", ref)["column"], "doing")

    def test_board_is_bounded_and_closed_work_cannot_restart(self):
        ref = self.card()
        self.card("another")
        board = self.call("board", "--limit", "1")
        self.assertEqual(len(board["cards"]), 1)
        self.assertEqual(board["more"], 1)
        self.run_git("bug", "bug", "status", "close", ref.split(":")[1])
        self.assertIn("closed issue", self.call("start", ref, "--plan", "revive", ok=False)["error"])

    def test_unlabelled_bug_and_empty_store_are_supported(self):
        self.assertEqual(self.call("board")["cards"], [])
        ref = self.card()
        for label in ("status:todo", "kind:task", "priority:p2"):
            self.run_git("bug", "bug", "label", "rm", ref.split(":")[1], label)
        self.assertEqual(self.call("board")["cards"][0]["column"], "todo")
        self.call("start", ref, "--plan", "labelled on claim")

    def dispatch_fixture(self, ref, changed=True, pause=False):
        (self.repo/"value").write_text("base\n")
        self.run_git("add", "value")
        self.run_git("commit", "-qm", "Fixture bug:"+ref.split(":")[1])
        base = self.run_git("rev-parse", "HEAD").strip()
        candidate = self.root/"candidate"
        self.run_git("worktree", "add", "-qb", "trailblazer/fixture-case", str(candidate))
        if changed:
            (candidate/"value").write_text("changed\n")
            subprocess.run(["git", "-C", str(candidate), "commit", "-qam",
                            "Candidate bug:"+ref.split(":")[1]], check=True, capture_output=True)
        commit = subprocess.check_output(["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True).strip()
        report = {"status": "fixed", "case": "fixture-case", "commit": commit,
                  "branch": "trailblazer/fixture-case", "worktree": None, "files": ["value"],
                  "check": {"status": "pass"}, "summary": "fixture candidate"}
        (self.root/"report.json").write_text(json.dumps(report))
        fake = self.root/"dispatch.py"
        fake.write_text('''import json, pathlib, sys
root=pathlib.Path(__file__).parent
kind,op,*args=sys.argv[1:]
if kind == 'case':
    if (root/'pause').exists():
        import time
        (root/'worker-ready').touch()
        while (root/'pause').exists(): time.sleep(0.05)
    print((root/'report.json').read_text()); sys.exit(0)
if op == 'info':
    print(json.dumps({'peerId':'fixture-codex'}))
elif op == 'send':
    message=json.loads(args[args.index('--text')+1].split('\\n',1)[1])
    if message['type']=='task':
        with (root/'sent').open('a') as out: out.write(json.dumps(message)+'\\n')
        (root/'task.json').write_text(json.dumps(message))
    print(json.dumps({'sent':True}))
elif op in ('read','wait'):
    if op=='wait' and (root/'hang-admission').exists():
        import time
        time.sleep(100)
    task=root/'task.json'
    events=[]
    cursor=len((root/'sent').read_text().splitlines()) if (root/'sent').exists() else 0
    after=int(args[args.index('--after')+1])
    if task.exists() and cursor>after:
        request=json.loads(task.read_text())['request_id']
        message={'protocol':'trailblazer/1','type':'accepted','id':'accept-1',
                 'request_id':request,'payload':{'case':'fixture-case','state':'waiting_resource'}}
        events=[{'cursor':cursor,'kind':'message','peer':'fixture-trailblazer',
                 'body':'From Trailblazer, not typed by the operator:\\n'+json.dumps(message)}]
    print(json.dumps({'events':events,'cursor':cursor}))
''')
        self.config = self.root/"dispatch.json"
        self.config.write_text(json.dumps({"peer":"fixture-trailblazer",
            "vortex_command":[sys.executable,str(fake),"vortex"],
            "case_command":[sys.executable,str(fake),"case"],
            "vortex_dir":str(self.root/"vortex"),
            "repos":{str(self.repo):["test \"$(cat value)\" = changed"]}}))
        if pause:
            (self.root/"pause").touch()
        return base

    def assign(self, ref, ok=True):
        return self.call("assign", ref, "trailblazer", "--check", 'test "$(cat value)" = changed',
                         "--dispatch-config", str(self.config), actor="codex", ok=ok)

    def await_assignment(self, ref):
        deadline = time.monotonic()+20
        while time.monotonic()<deadline:
            card=self.call("show",ref)
            if card["column"] in ("done","blocked"):
                return card
            time.sleep(0.1)
        self.fail("assignment did not finish: "+json.dumps(card))

    def test_assignment_starts_once_and_verifies_candidate_without_merging(self):
        ref=self.card("bounded change")
        base=self.dispatch_fixture(ref)
        first=self.assign(ref)
        second=self.assign(ref)
        self.assertEqual(first["assignment"],second["assignment"])
        card=self.await_assignment(ref)
        self.assertEqual(card["column"],"done",card)
        self.assertEqual(card["claim"]["actor"],"trailblazer")
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)
        self.assertEqual(self.run_git("rev-parse","HEAD").strip(),base)
        self.assertEqual((self.repo/"value").read_text(),"base\n")
        self.assertIn("verification",card["recent"][-1])

    def test_assignment_blocks_when_reported_fixed_candidate_fails_real_check(self):
        ref=self.card()
        self.dispatch_fixture(ref,changed=False)
        self.assign(ref)
        card=self.await_assignment(ref)
        self.assertEqual(card["column"],"blocked",card)
        self.assertIn("verification",card["recent"][-1])
        self.assign(ref)
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def test_assignment_cannot_steal_another_actors_card(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        self.call("start",ref,"--plan","existing work",actor="glm")
        self.assertIn("owned",self.assign(ref,ok=False)["error"])
        self.assertFalse((self.root/"sent").exists())

    def test_assignment_refuses_trailblazer_self_repair_after_history_rewrite(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        (self.repo/"mix.exs").write_text('def project, do: [app: :trailblazer]\n')
        self.run_git("add","mix.exs")
        self.run_git("commit","-qm","Guard fixture bug:"+ref.split(":")[1])
        self.assertIn("self",self.assign(ref,ok=False)["error"])
        self.assertFalse((self.root/"sent").exists())

    def test_dead_assignment_worker_blocks_without_replaying_dispatch(self):
        ref=self.card()
        self.dispatch_fixture(ref,pause=True)
        self.assign(ref)
        deadline=time.monotonic()+15
        while not (self.root/"worker-ready").exists() and time.monotonic()<deadline:
            time.sleep(0.05)
        self.assertTrue((self.root/"worker-ready").exists())
        with sqlite3.connect(self.root/"state/board.sqlite3") as db:
            job=json.loads(db.execute("SELECT data FROM assignments WHERE ref=?",(ref,)).fetchone()[0])
        os.killpg(job["pid"],signal.SIGKILL)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            resumed=self.call("resume",actor="trailblazer")["cards"][0]
            if resumed["state"]=="blocked": break
            time.sleep(0.05)
        self.assertEqual(resumed["state"],"blocked",resumed)
        self.assign(ref)
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def test_candidate_from_a_different_case_branch_cannot_become_done(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        path=self.root/"report.json"
        report=json.loads(path.read_text())
        report["branch"]="some-other-candidate"
        path.write_text(json.dumps(report))
        self.assign(ref)
        card=self.await_assignment(ref)
        self.assertEqual(card["column"],"blocked",card)
        self.assertIn("candidate",card["recent"][-1])

    def test_explicit_release_after_reconciliation_allows_a_fresh_assignment(self):
        ref=self.card()
        self.dispatch_fixture(ref,changed=False)
        first=self.assign(ref)
        self.assertEqual(self.await_assignment(ref)["column"],"blocked")
        self.call("release",ref,"case closed; candidate failed verification; retry explicitly",actor="trailblazer")
        candidate=self.root/"candidate"
        (candidate/"value").write_text("changed\n")
        subprocess.run(["git","-C",str(candidate),"commit","-qam",
                        "Retry fixture bug:"+ref.split(":")[1]],check=True,capture_output=True)
        report=json.loads((self.root/"report.json").read_text())
        report["commit"]=subprocess.check_output(["git","-C",str(candidate),"rev-parse","HEAD"],text=True).strip()
        (self.root/"report.json").write_text(json.dumps(report))
        second=self.assign(ref)
        self.assertNotEqual(first["assignment"],second["assignment"])
        self.assertEqual(self.await_assignment(ref)["column"],"done")
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),2)

    def test_unresponsive_admission_blocks_at_the_deadline_without_retry(self):
        ref=self.card()
        self.dispatch_fixture(ref)
        config=json.loads(self.config.read_text())
        config["deadline_seconds"]=2
        self.config.write_text(json.dumps(config))
        (self.root/"hang-admission").touch()
        self.assign(ref)
        card=self.await_assignment(ref)
        self.assertEqual(card["column"],"blocked",card)
        self.assertIn("deadline",card["recent"][-1].lower())
        self.assign(ref)
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def test_unresponsive_case_blocks_at_the_same_deadline_without_retry(self):
        ref=self.card()
        self.dispatch_fixture(ref,pause=True)
        config=json.loads(self.config.read_text())
        config["deadline_seconds"]=2
        self.config.write_text(json.dumps(config))
        self.assign(ref)
        card=self.await_assignment(ref)
        self.assertEqual(card["column"],"blocked",card)
        self.assertIn("deadline",card["recent"][-1].lower())
        self.assertEqual(len((self.root/"sent").read_text().splitlines()),1)

    def test_concurrent_assignment_returns_same_assignment_with_one_task(self):
        ref = self.card()
        base = self.dispatch_fixture(ref)
        cmd = self.base + ["--actor", "codex", "assign", ref, "trailblazer", "--check", 'test "$(cat value)" = changed', "--dispatch-config", str(self.config)]
        workers = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        results = [p.communicate() for p in workers]
        self.assertEqual([p.returncode for p in workers], [0, 0], results)
        assignments = [json.loads(out) for out, _ in results]
        self.assertEqual(assignments[0]["assignment"], assignments[1]["assignment"])
        card = self.await_assignment(ref)
        self.assertEqual(card["column"], "done", card)
        self.assertEqual(len((self.root/"sent").read_text().splitlines()), 1)
        self.assertEqual(self.run_git("rev-parse", "HEAD").strip(), base)
        self.assertEqual((self.repo/"value").read_text(), "base\n")


if __name__ == "__main__":
    unittest.main()
