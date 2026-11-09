# Known time limit on all 89 tasks (`full-timelimit-v1`)

Victus, Nov 8-9 2026, branch `feat/review-and-time-limit`, all defaults plus `AGENT_KNOWN_TIME_LIMIT=on`. The A
side is `full-all-v1` / `full-all-v2` (56 each, Nov 4).

## Result: worse, but check the baseline first

| | A: v1 | A: v2 | B: known limit |
|---|---:|---:|---:|
| Passed | 56 | 56 | **49** |
| Leaderboard score | 0.62907 | 0.62907 | 0.55040 |
| Timeouts | 17 | 14 | 14 |
| Wrong submissions | 14 | 17 | 22 |
| Tokens | 126.9M | 131.5M | 142.1M |

- **The limit was found on all 89 tasks:** 49 have 15 min, 16 have 30, 12 have 60, and a few have 10-200 min.
- **Grading broke on 3 more tasks** (download errors in the test script): compile-compcert,
  openssl-selfsigned-cert and dna-assembly, besides the two qemu tasks that break in every run. The first two
  pass in both A runs, so the corrected estimate is **about 51**.
- **Timeouts didn't drop** (14 against 15.5).
- **The 30-minute tasks did worst** (5 passes against 9.0 in A). The 15-minute tasks: 30 against 32.0. The
  60-minute tasks: 8 against 8.0.
- **Lost** (passed in both A runs): cobol-modernization, compile-compcert*, extract-elf,
  feal-linear-cryptanalysis, financial-document-processor, mailman, openssl-selfsigned-cert*, protein-assembly,
  sqlite-with-gcov. (* grading broke.)
- **Gained** (failed in both A runs): chess-best-move, polyglot-rust-c, regex-chess.

## Caveat: three experiments in a row came in at 49-51

`full-effort-medium-v1` (49), `full-review-v1` (about 55 corrected, 50 graded) and this run (about 51) all have
more wrong submissions than A (19-23 against 14-17). They tested unrelated changes. The model id
(`qwen3.8-27b`) and the server speed (97-104 tok/s) are unchanged. But the gateway could have changed the model
behind the same id, the network got flakier (more grading failures), or 56 was a lucky high twice.

**Before more experiments, rerun the A configuration (`full-all-v3`, defaults, no flags).** About 56 means
these experiments were really worse. About 50 means something drifted since Nov 4, and the three comparisons
need to be read again against the new baseline.
