"""Offline tests for tool output offloading (#13, docs/plans/tool-output-offloading.md). No Docker, no model."""

import asyncio
import json
import shutil
import subprocess
import threading

import pytest
import yaml
from harbor.environments.base import ExecResult
from jinja2 import StrictUndefined, Template
from minisweagent.exceptions import Submitted

from badger_mini.harbor_agent import PACKAGE_DIR, SAVED_MARKER, SUBMIT_MARKER, HarborEnvironment, is_file_view


class FakeEnvironment:
    """Stands in for Harbor's environment: returns canned results, or runs the wrapper with local bash."""

    def __init__(self, results=None, run_locally=False):
        self.results = list(results or [])
        self.run_locally = run_locally
        self.commands = []

    async def exec(self, command, cwd=None, env=None, timeout_sec=None):
        self.commands.append(command)
        if self.run_locally:
            p = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=timeout_sec)
            return ExecResult(stdout=p.stdout, stderr=p.stderr, return_code=p.returncode)
        return self.results.pop(0)


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    t.join()


def make_env(loop, fake, **kwargs):
    return HarborEnvironment(fake, loop, threading.Event(), **kwargs)


def saved(text, rc=0):
    return ExecResult(stdout=f"{SAVED_MARKER}\n{text}", stderr="", return_code=rc)


OFFLOAD_KEYS = {"output_head", "output_tail", "total_chars", "full_output_path"}


# --- execute() logic, canned results ---------------------------------------------------------------


def test_short_output_unchanged(loop):
    env = make_env(loop, FakeEnvironment([saved("hello\n")]))
    out = env.execute({"command": "echo hello"})
    assert out["output"] == "hello\n"
    assert out["returncode"] == 0
    assert not OFFLOAD_KEYS & out.keys()


def test_long_output_offloaded(loop):
    text = "a" * 1000 + "m" * 3000 + "z" * 2000
    env = make_env(loop, FakeEnvironment([saved("x"), saved(text, rc=2)]))
    env.execute({"command": "true"})
    out = env.execute({"command": "make"})
    assert out["output"] == text  # full text kept for the submit check and the trajectory
    assert out["returncode"] == 2
    assert out["output_head"] == "a" * 300
    assert out["output_tail"] == "z" * 1000
    assert out["total_chars"] == 6000
    assert out["full_output_path"] == "/tmp/agent_out/cmd_2.log"  # counter counts every command


def test_long_output_without_marker_not_offloaded(loop):
    """The wrapper couldn't create the file, so there's nothing to point at."""
    env = make_env(loop, FakeEnvironment([ExecResult(stdout="x" * 5000, stderr="", return_code=0)]))
    out = env.execute({"command": "cat big"})
    assert out["output"] == "x" * 5000
    assert not OFFLOAD_KEYS & out.keys()


def test_limit_zero_sends_old_wrapper(loop):
    fake = FakeEnvironment([ExecResult(stdout="x" * 5000, stderr="", return_code=0)])
    env = make_env(loop, fake, output_limit=0)
    out = env.execute({"command": "cat big"})
    assert SAVED_MARKER not in fake.commands[0]
    assert "agent_out" not in fake.commands[0]
    assert fake.commands[0].startswith("if command -v timeout")
    assert not OFFLOAD_KEYS & out.keys()


def test_custom_sizes(loop):
    env = make_env(loop, FakeEnvironment([saved("0123456789" * 30)]), output_limit=100, output_head=10, output_tail=20)
    out = env.execute({"command": "x"})
    assert out["output_head"] == "0123456789"
    assert out["output_tail"] == "0123456789" * 2


def test_submit_marker_still_detected(loop):
    env = make_env(loop, FakeEnvironment([saved(f"{SUBMIT_MARKER}\n")]))
    with pytest.raises(Submitted):
        env.execute({"command": f"echo {SUBMIT_MARKER}"})


def test_exec_error_has_no_offload_keys(loop):
    class Boom(FakeEnvironment):
        async def exec(self, *a, **k):
            raise RuntimeError("container gone")

    out = make_env(loop, Boom()).execute({"command": "ls"})
    assert out["returncode"] == -1
    assert not OFFLOAD_KEYS & out.keys()


def test_file_view_gets_higher_limit(loop):
    text = "x" * 5000
    env = make_env(loop, FakeEnvironment([saved(text), saved(text)]))
    view = env.execute({"command": "cd /app && cat src/main.py"})
    program = env.execute({"command": "python3 run.py"})
    assert not OFFLOAD_KEYS & view.keys()  # shown in full: the model asked to read the file
    assert OFFLOAD_KEYS <= program.keys()


def test_huge_file_view_still_offloaded(loop):
    env = make_env(loop, FakeEnvironment([saved("x" * 12000)]))
    out = env.execute({"command": "cat big.log"})
    assert OFFLOAD_KEYS <= out.keys()


@pytest.mark.parametrize(
    "command",
    [
        "cat src/main.py",
        "cd /app && nl -ba input.tex",
        "cd /a && cd b && sed -n '1,80p' f.py",
        "head -50 log",
        "tail -n 100 x",
        "cat a.log | grep error",
        "cat a.red && echo ===== && cat b.red",
    ],
)
def test_is_file_view(command):
    assert is_file_view(command)


@pytest.mark.parametrize(
    "command",
    [
        "grep -rn foo .",
        "python3 run.py",
        "make",
        "catalog list",
        "sed -i 's/a/b/' f",
        "cd /app && ls",
        "cat <<'EOF' > f.py\nprint(1)\nEOF\npython3 f.py",
        "cat f.py && python3 f.py",
        "cat f; make",
        "cat f || true",
    ],
)
def test_is_not_file_view(command):
    assert not is_file_view(command)


# --- observation_template rendering ----------------------------------------------------------------


def render(output):
    config = yaml.safe_load((PACKAGE_DIR / "config" / "terminal_bench.yaml").read_text())
    template = config["model"]["observation_template"]
    # mini-swe-agent renders with StrictUndefined (models/utils/actions_toolcall.py)
    return json.loads(Template(template, undefined=StrictUndefined).render(output=output))


def test_template_short():
    assert render({"output": "hi", "returncode": 0, "exception_info": ""}) == {"returncode": 0, "output": "hi"}


def test_template_offloaded():
    msg = render(
        {
            "output": "x" * 6000,
            "returncode": 1,
            "exception_info": "killed after timeout",
            "output_head": 'he"ad',
            "output_tail": "ta\nil",
            "total_chars": 6000,
            "full_output_path": "/tmp/agent_out/cmd_3.log",
        }
    )
    assert set(msg) == {"returncode", "output_head", "output_tail", "total_chars", "full_output_path", "note", "exception_info"}
    assert msg["output_head"] == 'he"ad'
    assert msg["full_output_path"] == "/tmp/agent_out/cmd_3.log"
    assert "output" not in msg


def test_template_very_long_without_file_keeps_old_shape():
    msg = render({"output": "x" * 12000, "returncode": 0, "exception_info": ""})
    assert set(msg) == {"returncode", "output_head", "output_tail", "elided_chars", "warning"}


# --- the wrapper itself, run with local bash on throwaway commands -----------------------------------


@pytest.fixture
def local_env(loop, tmp_path):
    return make_env(loop, FakeEnvironment(run_locally=True), output_dir=str(tmp_path / "agent_out"), timeout=5)


def test_wrapper_saves_file_and_keeps_returncode(local_env, tmp_path):
    out = local_env.execute({"command": "echo out; echo err >&2; exit 3"})
    assert out["returncode"] == 3
    assert out["output"] == "out\nerr\n"  # marker stripped, stderr interleaved
    assert (tmp_path / "agent_out" / "cmd_1.log").read_text() == "out\nerr\n"


def test_wrapper_long_output_points_at_real_file(local_env, tmp_path):
    out = local_env.execute({"command": "for i in $(seq 1000); do echo line $i; done"})
    path = out["full_output_path"]
    assert path == str(tmp_path / "agent_out" / "cmd_1.log")
    with open(path) as f:
        assert f.read() == out["output"]
    assert out["output_tail"].endswith("line 1000\n")


def test_wrapper_falls_back_when_dir_unwritable(loop, tmp_path):
    blocker = tmp_path / "file_not_dir"
    blocker.write_text("")
    env = make_env(loop, FakeEnvironment(run_locally=True), output_dir=str(blocker / "sub"), timeout=5)
    out = env.execute({"command": "seq 2000; exit 4"})
    assert out["returncode"] == 4
    assert out["output"].endswith("2000\n")
    assert not OFFLOAD_KEYS & out.keys()


@pytest.mark.skipif(shutil.which("timeout") is None, reason="coreutils timeout not installed (macOS)")
def test_wrapper_timeout_keeps_partial_output(loop, tmp_path):
    env = make_env(loop, FakeEnvironment(run_locally=True), output_dir=str(tmp_path), timeout=1)
    out = env.execute({"command": "echo started; sleep 10"})
    assert out["returncode"] == 124
    assert out["output"] == "started\n"
