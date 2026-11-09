"""Change report (AGENT_CHANGE_REPORT): at the first submit, list what changed in the task's directories.

The agent often spoils its own result: build/test files left next to the deliverable, git history rewritten,
setup reset after testing. The submit checklist asks it to look, and it looks at a long listing and misses the
problem. So the agent takes a snapshot of the task's directories at the start, and at the first submit the
checklist comes with a short, factual list: files created, changed, deleted; commits that are gone.
docs/plans/change-report.md
"""

import re
import shlex

# Directories never snapshotted as a whole: too big, or system-wide noise.
SKIP_DIRS = {"/", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/proc", "/sys", "/dev", "/tmp", "/var",
             "/opt", "/root", "/home", "/run", "/boot", "/mnt", "/media", "/srv", "/snap"}
ALWAYS_DIRS = ["/app"]
MAX_DIRS = 6
MAX_FILES = 20000      # more than this and the snapshot is skipped (a diff would be incomplete)
MAX_LISTED = 25        # per section in the report
MAX_COMMITS = 5000
SEP = "|"

_PATH = re.compile(r"(?<![\w.~$-])(/(?:[A-Za-z0-9_.+@-]+/)*[A-Za-z0-9_.+@-]+/?)")


def candidate_dirs(task: str) -> list[str]:
    """/app plus the directories of absolute paths named in the task (the path itself if it's a directory,
    else its parent is tried too). Existence is checked in the container; missing ones are ignored."""
    dirs: list[str] = list(ALWAYS_DIRS)
    for match in _PATH.findall(task or ""):
        path = match.rstrip("/")
        parts = path.split("/")
        options = [path] if "." not in parts[-1] else []
        if len(parts) > 2:
            options.append("/".join(parts[:-1]))  # parent, for file paths
        for option in options:
            if option and option not in SKIP_DIRS and not any(option == d or option.startswith(d + "/") for d in dirs):
                dirs = [d for d in dirs if not d.startswith(option + "/")] + [option]
    return dirs[:MAX_DIRS]


def snapshot_command(dirs: list[str]) -> str:
    """One line per file: path|size|mtime. Skips .git internals and node_modules. POSIX find + stat -c, so it
    works on GNU and busybox. Prints TOO_MANY if the cap is exceeded."""
    quoted = " ".join(shlex.quote(d) for d in dirs)
    return (
        f"for d in {quoted}; do [ -d \"$d\" ] && echo \"DIR{SEP}$d\"; done; "
        f"find {quoted} \\( -name .git -o -name node_modules \\) -prune -o -type f "
        f"-exec stat -c '%n{SEP}%s{SEP}%Y' {{}} + 2>/dev/null | head -n {MAX_FILES + 1}"
    )


def parse_snapshot(output: str) -> dict | None:
    """{"dirs": [...], "files": {path: (size, mtime)}}; None if there were too many files."""
    dirs, files = [], {}
    for line in (output or "").splitlines():
        if line.startswith("DIR" + SEP):
            dirs.append(line[len("DIR" + SEP):])
            continue
        parts = line.rsplit(SEP, 2)
        if len(parts) == 3 and parts[1].isdigit():
            files[parts[0]] = (int(parts[1]), parts[2])
    if len(files) > MAX_FILES:
        return None
    return {"dirs": dirs, "files": files}


def git_command(dirs: list[str]) -> str:
    """For each git repo under the dirs: REPO|path, then its commit hashes (all refs)."""
    quoted = " ".join(shlex.quote(d) for d in dirs)
    return (
        f"find {quoted} -maxdepth 3 -name .git 2>/dev/null | while read -r g; do r=$(dirname \"$g\"); "
        f"echo \"REPO{SEP}$r\"; git -c safe.directory='*' -C \"$r\" rev-list --all 2>/dev/null | head -n {MAX_COMMITS}; done"
    )


def parse_git(output: str) -> dict[str, set[str]]:
    repos: dict[str, set[str]] = {}
    current = None
    for line in (output or "").splitlines():
        if line.startswith("REPO" + SEP):
            current = line[len("REPO" + SEP):]
            repos[current] = set()
        elif current and re.fullmatch(r"[0-9a-f]{7,64}", line.strip()):
            repos[current].add(line.strip())
    return repos


def _size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def _section(title: str, items: list[str]) -> list[str]:
    if not items:
        return [f"{title}: (none)"]
    lines = [f"{title}:"] + [f"  {i}" for i in items[:MAX_LISTED]]
    if len(items) > MAX_LISTED:
        lines.append(f"  ... and {len(items) - MAX_LISTED} more")
    return lines


def counts(before: dict | None, after: dict | None, git_before: dict, git_after: dict) -> dict:
    if not before or not after:
        return {}
    b, a = before["files"], after["files"]
    return {
        "created": sum(p not in b for p in a),
        "changed": sum(p in b and a[p] != b[p] for p in a),
        "deleted": sum(p not in a for p in b),
        "commits_gone": sum(len(c - git_after.get(r, set())) for r, c in git_before.items()),
    }


def report(before: dict | None, after: dict | None, git_before: dict, git_after: dict) -> str:
    """The text appended to the submit checklist. Empty string if there's nothing reliable to say."""
    if not before or not after:
        return ""
    b, a = before["files"], after["files"]
    created = sorted(p for p in a if p not in b)
    deleted = sorted(p for p in b if p not in a)
    changed = sorted(p for p in a if p in b and a[p] != b[p])
    lines = ["", f"What changed in {', '.join(before['dirs']) or 'the task directories'} since you started:"]
    lines += _section("Created", [f"{p} ({_size(a[p][0])})" for p in created])
    lines += _section("Changed", changed)
    lines += _section("Deleted", deleted)
    for repo, commits in sorted(git_before.items()):
        gone = commits - git_after.get(repo, set())
        if gone:
            lines.append(
                f"Git: {len(gone)} of the {len(commits)} commits that existed in {repo} when you started are gone "
                "(history rewritten or deleted)."
            )
    lines.append(
        "For each created file, ask: does the task ask for it? If not, delete it. For each deleted file or lost "
        "commit: did the task ask for that? If not, restore it."
    )
    return "\n".join(lines)
