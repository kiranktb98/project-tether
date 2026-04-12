<!-- TETHER:INSTRUCTIONS START — managed by tether, do not edit by hand -->
## Tether is active in this project

A tool called **tether** is helping coordinate changes in this project.
Tether maintains a "feature ledger" at `.tether/ledger.yaml` that tracks
every feature, its files, its edge cases, and its status. Before making
changes, you should consult tether and follow its guidance.

### Workflow rules

**Before making any non-trivial code change:**

1. Read `.tether/ledger.yaml` to see the current feature set.

2. Run `tether plan <file_path> --intent "<short description>"` for
   the file you're about to modify. This generates impact analysis at
   `.tether/PLAN.md`.

3. Read `.tether/PLAN.md`. If it contains "STOP — Ask user", **stop and
   ask the user about the risks before proceeding**. Do not make the
   change until the user has answered.

4. If the change adds a new feature, the plan output will also contain
   suggested edge cases. Implement the code to handle the ones marked
   `must_handle: true`.

**Before removing or replacing a feature:**

1. Edit `.tether/ledger.yaml` to mark the feature `removing`.
2. Then change the code.
3. After the change, run `tether verify` to update the ledger.

**Always check `.tether/DRIFT.md`** at the start of each turn. If it
contains a drift note, the most recent change broke something. Read the
note carefully and either fix the issue or, if the change was intentional,
update the ledger to reflect the new reality.

**After finishing a logical unit of work, run `tether verify`.** This
re-validates everything and updates the ledger.

### Why this matters

Tether catches two classes of mistakes that are otherwise easy to miss:

1. **Cross-feature regressions** — when a change to feature A
   accidentally breaks feature B because they share code.
2. **Missed edge cases** — when a new feature handles the happy path
   but misses common edge cases.

The cost of consulting tether (a few seconds per change) is much less
than the cost of discovering these mistakes hours later.
<!-- TETHER:INSTRUCTIONS END -->
