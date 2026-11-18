# Where the time goes in the 17 timeouts of `full-all-v1`

Measured from the trajectories: each model call runs from its `created` stamp (request start, set by the server)
to its reply's timestamp, each command from the previous event to its result.

## Split

| | Share of the 415 timed-out minutes |
|---|---:|
| Model replies | 71% |
| of which cut-off replies (`finish_reason=length`) | 25% |
| Commands | 22% |

- **The server was steady:** a median of 105 output tok/s (p10 86, p90 124) over 1,813 calls. So the timeouts
  are not server stalls.
- **Long replies take the time.** In the timed-out tasks, 12% of normal replies are over 4,096 tokens, but
  they hold 54% of the output. In passed tasks it's 28%. The median reply is 533 tokens in timeouts and 350 in
  passes.
- **Commands matter for a few tasks only:** `caffe-cifar-10` (16 of 20 min), `extract-moves-from-video` (21 of
  30), `password-recovery` and `qemu-*` (5-8 min). These are heavy workloads (training, video, VMs); there's
  no generic fix.

## Repeated double cut-offs

- After a first cut-off, the retry with the full 16K budget finishes normally 76% of the time (66 of 87), so
  the boost mostly works.
- Some tasks fall into a loop: 8K cut, 16K cut, one thinking-off command, then deep thinking again.
  `polyglot-rust-c` did this 4 times in 15 minutes. Each loop costs about 24K tokens, about 4 minutes.
- In 4 tasks, the second and later loops wasted 147K tokens (about 23 min). Two of those tasks timed out
  (`polyglot-rust-c`, `regex-chess`); two passed anyway.

## Options

1. **Lower thinking cap (`AGENT_THINKING_CAP=4096`).** Config only. It targets the long replies that hold 54%
   of timeout output. Overrun recovery now keeps a cut reply's thinking as notes, so a cut costs less than it
   did when the 8192 cap was chosen. Risk: passes use long replies too (28% of their output).
2. **Skip the 16K retry after a task's first double cut-off:** a later cut-off goes straight to a thinking-off
   reply. A small code change, worth 0-1 task (`polyglot-rust-c`, `regex-chess`).
3. **Commands:** nothing generic.
