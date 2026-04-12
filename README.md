# Tether

**An impact-analysis and edge-case engine for coding agents.**

Stops Claude Code from accidentally breaking feature B while fixing feature A.

---

Codacy catches insecure code. Linters catch broken code. **Tether catches off-task code and unintended regressions.**

## What it does

When you ask a coding agent to change something, two things go wrong:

1. **Cross-feature regressions** — the agent modifies a shared file and accidentally breaks an unrelated feature. You find out hours later.
2. **Missed edge cases** — the new feature handles the happy path but misses the five cases you'd have caught in a design review.

Tether intervenes in three places:

- **Before the change** — `tether plan src/ratelimiter.py --intent "add Redis caching"` predicts which features are at risk and at what severity. If the risk is medium or high, Claude Code stops and asks you before writing a line of code.
- **During the change** — `tether watch` monitors the file system, runs targeted tests for affected features, and writes a drift note to `.tether/DRIFT.md` the moment something breaks. Claude Code reads it on its next turn.
- **After the change** — `tether verify` re-runs everything, computes edge-case confidence stats per feature, and blocks session completion until main tests plus confident must-handle edge-case tests pass.

## Install

```bash
pip install tether-engine
```

Requires Python 3.11+ and an Anthropic API key (for the Haiku watcher model).
Tether reads `ANTHROPIC_API_KEY` from either your shell environment or a
project-local `.env` file.

## Launch Assets

- Simple explainer: [tether_easy_guide.html](./tether_easy_guide.html)
- Progress and roadmap: [progress_so_far.html](./progress_so_far.html)
- Reddit launch drafts: [launch_posts.md](./launch_posts.md)

## Quickstart

```bash
# Option A: project-local .env file
printf "ANTHROPIC_API_KEY=sk-...\n" > .env

# Option B: shell environment variable
export ANTHROPIC_API_KEY=sk-...

# In your project directory:
tether init          # create .tether/, write CLAUDE.md instructions
tether bootstrap     # scan codebase, propose features, generate tests

# In one terminal:
tether watch         # starts the file watcher

# In another terminal:
claude               # Claude Code reads .tether/CLAUDE.md automatically
```

That's it. Claude Code will now call `tether plan` before changes and `tether verify` after, driven by the instructions tether wrote into `CLAUDE.md`.

## Try the demo project

```bash
cd examples/ratelimiter
tether init
tether bootstrap --yes   # auto-accept the proposed ledger
python demo.py           # verify the project works
```

Then ask Claude Code to "add Redis caching to the rate limiter" and watch
tether flag the blast radius before a line of code is written.

## How it works

Tether has four phases:

### 1. Bootstrap (one-time)

`tether bootstrap` scans your Python codebase with tree-sitter, asks Haiku to propose a list of features, opens the draft in your `$EDITOR` for review, then generates edge cases and pytest stubs for every feature. The result is a **feature ledger** at `.tether/ledger.yaml`.

Use `--yes` to auto-accept the proposed features (useful in CI or when you just want to try it quickly).

### 2. Plan (per change)

`tether plan <file> --intent "..."` queries the ledger for features that touch the file, sends them to Haiku for risk assessment, and writes `.tether/PLAN.md`. Claude Code reads PLAN.md and — if the risk is medium or high — asks you before proceeding.

### 3. Watch (continuous)

`tether watch` runs a file watcher. On every change:
- Runs pytest for the affected features only (fast — usually < 10s)
- Asks Haiku whether the diff aligns with the feature ledger (intent check)
- Checks for changed function signatures or removed exports (static invariants)
- Writes severity-graded notes to `.tether/DRIFT.md`

### 4. Verify (post-change)

`tether verify` re-runs all affected tests, computes a per-feature edge-case confidence summary, snapshots the ledger, promotes `building` features to `active` when tests pass, and writes a session report. By default, it also fails the session if any high-confidence `must_handle` edge case is still skipped, failing, or missing a generated test.

You can tune that gate in `.tether/config.yaml`:

```yaml
verify:
  max_test_runtime_seconds: 30
  confidence_gate_threshold: 0.8
  require_confident_must_handle_tests: true
```

## Natural language Q&A

```bash
tether ask "which features would break if I change the rate limiter?"
tether ask "what are the must-handle edge cases for the auth feature?"
```

Uses the feature ledger as context — no full-codebase search, just the structured metadata.

## Cost

Tether uses **Claude Haiku 4.5** for all analysis. This is intentional — Haiku does structured pattern matching, not creative reasoning. The watcher model is never Sonnet or Opus.

Real numbers from dogfooding tether on its own codebase (63 files, 33 features):
- Bootstrap: **~$1.50** one-time (proposals + 396 edge cases + ~264 test stubs)
- Plan (single file): **~$0.01**
- Ask (single question): **~$0.005**

Expected overhead per Claude Code session: **15–25%** of your base session cost.

## Offline / zero-cost mode (Ollama)

Tether also works with a local [Ollama](https://ollama.com) server. Set `provider: ollama` in `.tether/config.yaml`:

```yaml
watcher:
  provider: ollama
  model: qwen2.5:7b          # or llama3.2:3b, mistral:7b, etc.
  ollama_base_url: http://localhost:11434
```

Quality is lower than Haiku but good enough for intent-checking. Start Ollama with `ollama serve` before running `tether watch`.

## CLI reference

| Command | Description |
|---|---|
| `tether init` | Interactive setup |
| `tether bootstrap [--yes]` | Scan codebase, build initial ledger |
| `tether plan <file> --intent "..."` | Impact analysis for a planned change |
| `tether watch` | Start the file watcher |
| `tether verify` | Post-change validation |
| `tether ask "<question>"` | Ask a natural-language question about your ledger |
| `tether ledger` | Show feature ledger as a table |
| `tether log [feature_id]` | Show feature history |
| `tether status` | Current session stats |
| `tether report` | Most recent session report |

Global flags: `--config PATH`, `--verbose`, `--quiet`.

## What it isn't

- Not a security tool — use Claude Code's built-in permissions or Rulebricks for that
- Not a linter — use ruff/pylint for style
- Not a CI replacement — tether watches your local session, not your pipeline
- Not an agent — it does not write code

## Known limitations

- Python projects only (v0.1). JS/TS/Go/Rust are on the roadmap.
- Single-repo only.
- Impact analysis is heuristic — Haiku pattern-matches, it doesn't do formal program analysis. Occasional false positives and misses are expected.
- Bootstrap quality depends on user review of the proposed ledger. Rubber-stamping gives you a weak ledger.
- Tether does not block writes during `watch`, but `verify` can block session completion when confident must-handle edge cases are still failing.
- Non-determinism: two runs on the same diff may return slightly different verdicts.

## Roadmap

- v0.8: Ollama backend ✓, example project ✓, polished README ✓
- v1.0: Public launch — Reddit/HN, real users, JS/TS or Codex support

## License

Apache-2.0
