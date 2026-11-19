"""Offline tests for the command output cap (OUTPUT_CAP_CHARS). A command that printed a raw ISO
(~1 GB, qemu-alpine-ssh in probe-moretime-v1) was kept whole in memory and in the trajectory
(extra.raw_output), though the model only ever sees the first and last 5,000 characters.
No endpoint or Docker."""

import asyncio
import threading
from types import SimpleNamespace

from badger_mini.harbor_agent import OUTPUT_CAP_CHARS, HarborEnvironment


class FakeEnvironment:
    def __init__(self, stdout: str, stderr: str = "", return_code: int = 0):
        self.result = SimpleNamespace(stdout=stdout, stderr=stderr, return_code=return_code)

    async def exec(self, **kwargs):
        return self.result


def run(stdout: str, stderr: str = "") -> tuple[dict, HarborEnvironment]:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        env = HarborEnvironment(environment=FakeEnvironment(stdout, stderr), loop=loop, stop=threading.Event())
        return env.execute({"command": "true"}, check=False), env
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join()


def test_short_output_is_untouched():
    output, env = run("hello\n", "warn\n")
    assert output["output"] == "hello\nwarn\n"
    assert env.n_capped_outputs == 0


def test_output_at_the_cap_is_untouched():
    text = "x" * OUTPUT_CAP_CHARS
    output, env = run(text)
    assert output["output"] == text
    assert env.n_capped_outputs == 0


def test_long_output_keeps_head_and_tail():
    half = OUTPUT_CAP_CHARS // 2
    text = "H" * half + "M" * (3 * OUTPUT_CAP_CHARS) + "T" * half
    output, env = run(text)
    assert len(output["output"]) < OUTPUT_CAP_CHARS + 200
    assert output["output"].startswith("H" * half)
    assert output["output"].endswith("T" * half)
    assert "M" not in output["output"]
    assert f"{3 * OUTPUT_CAP_CHARS:,}" in output["output"]  # the marker says how much was dropped
    assert env.n_capped_outputs == 1


def test_what_the_model_sees_is_unchanged():
    # observation_template shows output[:5000] and output[-5000:]
    text = "".join(chr(65 + i % 26) for i in range(5 * OUTPUT_CAP_CHARS))
    output, _ = run(text)
    assert output["output"][:5000] == text[:5000]
    assert output["output"][-5000:] == text[-5000:]
