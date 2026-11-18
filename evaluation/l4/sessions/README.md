# Cloud sessions of the reruns

The step files and loops exactly as they ran for the campaigns of release
[thesis-v2](https://github.com/Romercor/hiku-scheduler/releases/tag/thesis-v2). They ran from a work copy of this
repository at `/root/rt/pw` and kept their logs in `/root/rt/prework`; to run one again, replace these two paths with the
repository root and a folder of your own. A session is a step file run by `harness/chain.sh` (one step per line, the
session stops at the first failed step and destroys the cluster), started by its `run*.sh`, which retries a session
that fails before its first campaign starts. `tf_*.tfvars` are the cluster layouts, copied to
`terraform-upcloud/terraform.tfvars` by the first step.

| Session | Layout | Campaigns |
|---|---|---|
| `n1`, `n1c` (`run_all.sh`, `retry_n1.sh`) | `tf_ol` | `rl1`, `top1`; `bur3` |
| `n2` | `tf_sat` | `sat5_*` (`sat_loop.sh`) |
| `n3` (`wait_n3.sh`) | `tf_sat` | `sat6_*`, `gw_*` (`sat6_loop.sh`, `gw_loop.sh`) |
| `n7` (`run7.sh`) | `tf_sat` | `sat7_*`, `lim7_*`, round 1 of `cal7` (moved to `n7_cal7_round1`) |
| `n7b` (`run7b.sh`) | `tf_sat` | `cal7*`, `gw7*` (`cal7_loop.sh`, `gw7_loop.sh`; nginx configuration from `gen_gw.py`) |
| `n8` (`run8.sh`) | `tf_ol` | `pilot_s8`, `pilot_ibm8_*`, `final_paper8`, `final_ibm8`, `rq3_ibm8`, `ref_s8_*` |
| `n9` (`run9.sh`) | `tf_ol` | `pilot_s9`, `conn3_ibm9`, `loss4_ibm9`, `pad4_ibm9`, `agelimit_ibm9` (stopped), `ref_s9_1` |
| `n9b` (`run9b.sh`) | `tf_ol` | `pilot_s9b`, `final_ibm8_r2`, `agelimit_ibm9b`, `skew3_9b`, `top_9b`, `open3_9b`, `ref_s9b_*` |
| `n10`, `n10b` (`run10.sh`, `run10b.sh`) | `tf_multi` | `pilot_s10`, `multi3_ibm10`; `pilot_s10b`, `multi3_ibm10_r4` |
| `n12`, `n12c` (`run12.sh`) | `tf_sat` | `sat8_*`, `sat8_stolen` (`sat8_loop.sh`, then `sat8b_loop.sh`; arms in `sat8_arms/`) |

Gates before a session's campaigns: the scheduler's speed check in the second step (replace the scheduler machine while
a fixed CPU loop takes more than 0.40 s), `harness/gate.py` on the pilot run, `pilot_ladder.sh` with `gate_replay.py`
(the highest replay mean that the cluster serves) and, for `n12`, `gate12.sh` (scheduler speed and client CPU steal).
