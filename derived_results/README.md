# Derived Results

This directory contains compact, plain-text outputs used to check the paper's
reported statistics without distributing multi-gigabyte raw model transcripts.

- `paired_intervention_analysis.txt` records the fixed-seed task-paired tests,
  source-task-clustered bootstrap intervals, task-order quartiles, and
  manipulation checks produced by `scripts/paired_intervention_analysis.py`.
- `content_volume_controls.txt` records the random-strip and high-load
  non-gating controls, including their corpus-construction checks, produced by
  `scripts/content_volume_control_analysis.py`.
- `cost/*/cost_resource_summary.md` records each model replicate's cost and
  robustness breakdown produced by `analysis/cost_resource_analysis.py`.

The main runner regenerates the raw JSONL inputs. No paths in these outputs are
required to identify a machine, account, institution, or author.
