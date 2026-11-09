"""Offline tests for the change report (AGENT_CHANGE_REPORT), docs/plans/change-report.md. No endpoint or Docker."""

import threading

from badger_mini import changes
from badger_mini.harbor_agent import SUBMIT_CHECK_MESSAGE, SUBMIT_MARKER, HarborEnvironment


def snap(files: dict, dirs=("/app",)) -> dict:
    return {"dirs": list(dirs), "files": {p: (size, "100") for p, size in files.items()}}


# --- candidate_dirs ---------------------------------------------------------------------------------------


def test_app_is_always_first():
    assert changes.candidate_dirs("") == ["/app"]


def test_file_path_adds_its_parent():
    assert changes.candidate_dirs("Write the result to /srv/data/out.json") == ["/app", "/srv/data"]


def test_paths_inside_app_add_nothing():
    assert changes.candidate_dirs("Fix /app/src/main.py and /app/tests/") == ["/app"]


def test_system_roots_are_skipped():
    assert changes.candidate_dirs("See /tmp/x.log and /var/log/") == ["/app", "/var/log"]


def test_pseudo_filesystems_are_skipped():
    assert changes.candidate_dirs("Read /proc/cpuinfo, /sys/class/net and /dev/shm/x") == ["/app"]


def test_a_named_file_in_etc_is_tracked():
    assert changes.candidate_dirs("Edit /etc/nginx/nginx.conf") == ["/app", "/etc/nginx"]


def test_parent_replaces_a_child_dir():
    assert changes.candidate_dirs("Use /data/repo/sub then /data/repo/file.txt") == ["/app", "/data/repo"]


def test_urls_are_not_paths():
    assert changes.candidate_dirs("Clone https://github.com/foo/bar and read docs at http://x.org/a/b") == ["/app"]


def test_dir_count_is_capped():
    task = " ".join(f"/d{i}/x" for i in range(20))
    assert len(changes.candidate_dirs(task)) == changes.MAX_DIRS


# --- parsing ----------------------------------------------------------------------------------------------


def test_parse_snapshot():
    out = "DIR|/app\n/app/a.c|12|1700000000\n/app/we|ird.txt|3|1700000001\nstat: noise\n"
    assert changes.parse_snapshot(out) == {
        "dirs": ["/app"],
        "files": {"/app/a.c": (12, "1700000000"), "/app/we|ird.txt": (3, "1700000001")},
    }


def test_too_many_files_gives_no_snapshot():
    out = "\n".join(f"/app/f{i}|1|1" for i in range(changes.MAX_FILES + 1))
    assert changes.parse_snapshot(out) is None


def test_parse_git():
    out = "REPO|/app\n" + "a" * 40 + "\n" + "b" * 40 + "\nREPO|/data\n"
    assert changes.parse_git(out) == {"/app": {"a" * 40, "b" * 40}, "/data": set()}


def test_cut_off_commit_list_is_dropped():
    out = "REPO|/app\n" + "\n".join(f"{i:040x}" for i in range(changes.MAX_COMMITS + 1))
    assert changes.parse_git(out) == {}


def test_git_command_does_not_use_all_refs():
    assert "--all" not in changes.git_command(["/app"])


# --- counts and report ------------------------------------------------------------------------------------


def test_created_changed_deleted():
    before = snap({"/app/main.c": 10, "/app/keep.txt": 5, "/app/old.txt": 7})
    after = snap({"/app/main.c": 20, "/app/keep.txt": 5, "/app/cmain": 9000})
    assert changes.counts(before, after, {}, {}) == {"created": 1, "changed": 1, "deleted": 1, "commits_gone": 0}
    text = changes.report(before, after, {}, {})
    assert "Created:\n  /app/cmain (9 KB)" in text
    assert "Changed:\n  /app/main.c" in text
    assert "Deleted:\n  /app/old.txt (7 B)" in text
    assert "keep.txt" not in text


def test_nothing_changed():
    before = snap({"/app/a": 1})
    text = changes.report(before, before, {}, {})
    assert "Created: (none)" in text and "Changed: (none)" in text and "Deleted: (none)" in text


def test_lost_commits():
    git_before = {"/app": {"a", "b", "c"}}
    git_after = {"/app": {"a", "d"}}
    s = snap({})
    assert changes.counts(s, s, git_before, git_after)["commits_gone"] == 2
    assert "2 of the 3 commits that existed in /app" in changes.report(s, s, git_before, git_after)


def test_deleted_repo_loses_all_commits():
    s = snap({})
    assert changes.counts(s, s, {"/app": {"a", "b"}}, {})["commits_gone"] == 2


def test_new_commits_are_not_reported():
    s = snap({})
    assert "Git:" not in changes.report(s, s, {"/app": {"a"}}, {"/app": {"a", "b"}})


def test_no_snapshot_no_report():
    assert changes.report(None, snap({}), {}, {}) == ""
    assert changes.counts(snap({}), None, {}, {}) == {}


def test_new_dir_is_one_line():
    before = snap({"/app/src/main.rs": 100})
    after = snap({"/app/src/main.rs": 100, "/app/cmain": 50,
                  **{f"/app/target/debug/f{i}": 1024 for i in range(40)}})
    text = changes.report(before, after, {}, {})
    assert "/app/target/ (40 files, 40 KB)" in text
    assert "/app/cmain (50 B)" in text
    assert "... and" not in text


def test_new_file_in_existing_dir_is_listed_alone():
    before = snap({"/app/src/main.rs": 100})
    after = snap({"/app/src/main.rs": 100, "/app/src/extra.rs": 3})
    assert "  /app/src/extra.rs (3 B)" in changes.report(before, after, {}, {})


def test_deleted_dir_is_one_line():
    before = snap({"/app/data/a": 1, "/app/data/b": 1, "/app/x": 1})
    after = snap({"/app/x": 1})
    assert "/app/data/ (2 files, 2 B)" in changes.report(before, after, {}, {})


def test_long_sections_are_cut():
    before = snap({})
    after = snap({f"/app/f{i:02}": 1 for i in range(30)})
    text = changes.report(before, after, {}, {})
    assert "  /app/f24 (1 B)" in text and "/app/f25" not in text
    assert "... and 5 more" in text


# --- wiring: the notes go after the checklist -------------------------------------------------------------


def test_notes_are_appended_to_the_checklist():
    env = HarborEnvironment(environment=None, loop=None, stop=threading.Event())
    env.submit_check = True
    env.submit_notes = lambda: "\nNOTES"
    output = {"output": f"{SUBMIT_MARKER}\n", "returncode": 0, "exception_info": ""}
    env._check_finished(output)
    assert output["output"] == SUBMIT_CHECK_MESSAGE + "\nNOTES"
