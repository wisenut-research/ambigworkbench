# AmbigWorkBench Data

This file describes the data and compact derived outputs in this repository,
which accompany *Cumulative Memory Changes Agent Behavior Under Ambiguity:
Repeated-Task Evidence on Performance and Cost*.

Checksums for every file, including the software, are listed in `SHA256SUMS`
at the repository root:

```bash
shasum -a 256 -c SHA256SUMS
```

## Contents

- `benchmark/tasks/`: 314 synthetic ambiguous task variants and answer keys.
- `benchmark/seed/`: deterministic initial state for the five task databases.
- `workspace/`: prompt-condition workspaces, tools, and initial databases.
- `derived_results/`: compact statistical and per-replicate outputs reported in
  the paper.

The data are synthetic fictional office-task materials. They contain no real
user data, personally identifying information, or sensitive records.

The task-seed and workspace files derived from WorkBench retain the WorkBench
MIT terms; see `THIRD_PARTY_LICENSES/WORKBENCH_LICENSE.txt`.
