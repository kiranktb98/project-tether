# Tether Demo Script (asciinema)

This script shows the complete tether workflow on the ratelimiter sample project.
Recording target: 3–4 minutes at 80x24 terminal.

## Prerequisites

```bash
pip install tether-engine
export ANTHROPIC_API_KEY=sk-...
cd examples/ratelimiter
```

---

## Scene 1: Init (30s)

```bash
# Tether sets up .tether/ and writes CLAUDE.md
tether init
```

Expected output: config written, CLAUDE.md updated, .gitignore entry added.

---

## Scene 2: Bootstrap (60s — most time is API calls, skip ahead in recording)

```bash
# Scan the 3-file project, propose features, generate edge cases and test stubs
tether bootstrap --yes
```

Expected output:
- Found 3 Python files
- Haiku proposed 3 features: JWT Auth, Rate Limiting, Request Middleware
- ~24 edge cases, ~18 test stubs
- Cost ~$0.08

Pause here to show the generated ledger:

```bash
tether ledger
```

---

## Scene 3: Plan — the key selling point (45s)

Show what happens BEFORE making a risky change:

```bash
tether plan src/ratelimiter.py --intent "add Redis caching to speed up window lookups"
cat .tether/PLAN.md
```

Expected PLAN.md content:
- **STOP — medium/high risk detected**
- Feature "Request Middleware with Auth" is at medium risk (shares `_limiter`)
- Feature "Per-user Rate Limiting" is at high risk (directly modifies window logic)
- Mitigation: keep the `RateLimiter` interface identical, only swap storage backend

This is the key demo: tether caught that "adding Redis" touches the rate-limiter AND
the middleware (through the shared `_limiter` instance) before a line was changed.

---

## Scene 4: Ask — natural language Q&A (30s)

```bash
tether ask "which features would break if I change the RateLimiter constructor?"
tether ask "what are the must-handle edge cases for rate limiting?"
```

---

## Scene 5: Watch catching a regression (60s)

Open a second terminal, start the watcher:
```bash
tether watch
```

In the first terminal, make a breaking change:
```bash
# Simulate accidentally breaking the admin bypass
# Change: if is_admin(token): → if False:  (simulating an agent mistake)
sed -i 's/if is_admin(token):/if False:  # BUG/' src/middleware.py
```

Back in the watch terminal — within 1-2 seconds you should see:
```
[DRIFT] middleware.py — severity: hard
  Intent check: drifted (f3: Request Middleware)
  Tests: 1 failing (test_admin_bypass.py)
  See .tether/DRIFT.md
```

Show CLAUDE.md now has a drift pointer:
```bash
head -5 CLAUDE.md
```

Revert the bug:
```bash
git checkout src/middleware.py  # or sed to fix
```

Watcher clears the drift note automatically.

---

## Scene 6: Verify (30s)

After the session:
```bash
tether verify
```

Shows all tests pass, ledger versioned, session cost summary.

---

## Recording tips

- Use `asciinema rec demo.cast` to record
- Use `asciinema play demo.cast --speed 2` for the API call waits
- Convert to GIF: `agg demo.cast demo.gif` (requires `agg` tool)
- Target GIF size: < 5MB

## Editing the cast

To speed up API wait sections:
```python
import json, sys
with open('demo.cast') as f:
    lines = f.readlines()
header = json.loads(lines[0])
out = [lines[0]]
prev_ts = 0.0
for line in lines[1:]:
    ts, typ, data = json.loads(line)
    gap = ts - prev_ts
    if gap > 2.0:  # Compress waits > 2s to 0.5s
        ts = prev_ts + 0.5
    out.append(json.dumps([ts, typ, data]) + '\n')
    prev_ts = ts
sys.stdout.write(''.join(out))
```
