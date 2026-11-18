"""Loop / verification measurement over mini_agent trajectories, split by outcome.

Usage: python3 -I loops.py <job_dir> [<job_dir> ...]
"""
import json, re, sys, statistics as st
from collections import Counter, defaultdict
from pathlib import Path

WRITE_RES = [
    re.compile(r"sed\s+-i\S*\s+(?:-e\s+)?(?:'[^']*'|\"[^\"]*\"|\S+)\s+(\S+)"),
    re.compile(r"(?:cat|tee)\s*(?:-a\s+)?>?\s*(\S+)\s*<<"),
    re.compile(r"cat\s*<<-?\s*'?\"?\w+'?\"?\s*>\s*(\S+)"),
    re.compile(r"tee\s+(?:-a\s+)?(\S+)\s*<<"),
    re.compile(r"open\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][wa]"),
]


def norm(cmd):
    return re.sub(r"\s+", " ", cmd.strip())


def files_written(cmd):
    out = set()
    for r in WRITE_RES:
        for m in r.finditer(cmd):
            f = m.group(1).strip("'\";")
            if f and not f.startswith("-") and f not in ("/dev/null",):
                out.add(f)
    return out


def outcome(trial):
    r = json.loads((trial / "result.json").read_text())
    vr = r.get("verifier_result") or {}
    reward = (vr.get("rewards") or {}).get("reward")
    exc = (r.get("exception_info") or {}) or {}
    etype = exc.get("exception_type", "") if isinstance(exc, dict) else ""
    if reward == 1:
        return "pass"
    if "Timeout" in etype:
        return "timeout"
    if reward is None:
        return "error"
    return "wrong"


def analyse(trial):
    p = trial / "agent" / "mini-swe-agent.trajectory.json"
    if not p.exists():
        return None
    msgs = json.loads(p.read_text())["messages"]
    cmds = []  # (cmd, returncode, after_check)
    after_check = False
    pending = {}
    for m in msgs:
        role = m.get("role")
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except Exception:
                    continue
                pending[tc.get("id")] = args.get("command", "")
        if role == "tool":
            cmd = pending.pop(m.get("tool_call_id"), None)
            if cmd is None:
                continue
            rc = (m.get("extra") or {}).get("returncode")
            cmds.append((cmd, rc, after_check))
            if "Not submitted yet" in str(m.get("content")):
                after_check = True
    if not cmds:
        return None
    n = len(cmds)
    # identical repeats
    c = Counter(norm(x[0]) for x in cmds if "COMPLETE_TASK" not in x[0])
    max_same = max(c.values()) if c else 0
    repeated = sum(v - 1 for v in c.values() if v > 1)
    # repeated failing command (same cmd failed before)
    failed_seen, rep_fail = set(), 0
    for cmd, rc, _ in cmds:
        k = norm(cmd)
        if rc not in (0, None):
            if k in failed_seen:
                rep_fail += 1
            failed_seen.add(k)
    # longest failure streak
    streak = best = 0
    for _, rc, _ in cmds:
        streak = streak + 1 if rc not in (0, None) else 0
        best = max(best, streak)
    # edits per file
    fc = Counter()
    for cmd, _, _ in cmds:
        for f in files_written(cmd):
            fc[f] += 1
    max_edits = max(fc.values()) if fc else 0
    # after check
    post = [x for x in cmds if x[2] and "COMPLETE_TASK" not in x[0]]
    reached_check = after_check
    submitted = any("COMPLETE_TASK_AND_SUBMIT" in x[0] for x in cmds)
    return dict(
        n=n, max_same=max_same, repeated=repeated, rep_fail=rep_fail,
        fail_frac=sum(rc not in (0, None) for _, rc, _ in cmds) / n,
        streak=best, max_edits=max_edits, reached_check=reached_check,
        post=len(post), post_fail=sum(rc not in (0, None) for _, rc, _ in post),
        submitted=submitted,
    )


def main():
    rows = defaultdict(list)
    per_task = defaultdict(list)
    for jd in sys.argv[1:]:
        for t in sorted(Path(jd).iterdir()):
            if not (t / "result.json").exists():
                continue
            o = outcome(t)
            a = analyse(t)
            if a is None:
                continue
            a["task"] = t.name.split("__")[0]
            a["job"] = Path(jd).name
            rows[o].append(a)
            per_task[a["task"]].append((o, a))

    def med(xs):
        return st.median(xs) if xs else float("nan")

    def frac(xs):
        return f"{100*sum(xs)/len(xs):4.0f}%" if xs else "  -"

    print(f"{'outcome':8} {'n':>4} {'cmds':>5} {'maxSame':>7} {'reps':>5} {'repFail':>7} "
          f"{'fail%':>6} {'streak':>6} {'maxEdit':>7} {'edit>=5':>7} {'same>=4':>7} {'chk':>5} {'post':>5} {'post0':>6}")
    for o in ("pass", "wrong", "timeout", "error"):
        R = rows[o]
        if not R:
            continue
        chk = [r for r in R if r["reached_check"]]
        print(f"{o:8} {len(R):4} {med([r['n'] for r in R]):5.0f} {med([r['max_same'] for r in R]):7.0f} "
              f"{med([r['repeated'] for r in R]):5.0f} {med([r['rep_fail'] for r in R]):7.0f} "
              f"{100*med([r['fail_frac'] for r in R]):5.0f}% {med([r['streak'] for r in R]):6.0f} "
              f"{med([r['max_edits'] for r in R]):7.0f} {frac([r['max_edits']>=5 for r in R]):>7} "
              f"{frac([r['max_same']>=4 for r in R]):>7} {frac([r['reached_check'] for r in R]):>5} "
              f"{med([r['post'] for r in chk]):5.0f} {frac([r['post']==0 for r in chk]):>6}")

    # same task, different outcome: does the failing run loop more?
    print("\nPaired (tasks with both pass and wrong): median per-task difference wrong - pass")
    diffs = defaultdict(list)
    for task, L in per_task.items():
        P = [a for o, a in L if o == "pass"]
        W = [a for o, a in L if o == "wrong"]
        if P and W:
            for k in ("n", "max_same", "rep_fail", "streak", "max_edits", "post"):
                diffs[k].append(med([a[k] for a in W]) - med([a[k] for a in P]))
    for k, v in diffs.items():
        print(f"  {k:10} n={len(v):2}  median diff {med(v):+.1f}  wrong-higher {sum(x>0 for x in v)}  "
              f"lower {sum(x<0 for x in v)}")

    print("\nWrong-answer trials, sorted by max_edits:")
    for a in sorted(rows["wrong"], key=lambda r: -r["max_edits"])[:15]:
        print(f"  {a['job']:13} {a['task']:38} cmds={a['n']:3} maxEdit={a['max_edits']:2} "
              f"maxSame={a['max_same']:2} repFail={a['rep_fail']:2} post={a['post']}")
    nev = [a for a in rows["wrong"] if not a["reached_check"]]
    print(f"\nWrong trials that never reached the submit check: {len(nev)}")
    for a in nev:
        print(f"  {a['job']} {a['task']} submitted={a['submitted']} cmds={a['n']}")


main()
