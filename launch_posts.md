# Launch Posts

These drafts are written to stay strong without overstating what Tether does.

## r/ChatGPTCoding

Use the subreddit self-promotion thread rather than a standalone promo post.

**Suggested title line inside the thread**

Tether: a guardrail layer for AI coding sessions

**Draft**

I built a tool called **Tether** for a problem I kept hitting with AI coding sessions:
"fix A" quietly breaking B.

Tether builds a feature ledger for the repo, checks blast radius before edits,
watches for drift during the session, and runs `verify` at the end.

The part I care about most is this:
- it checks the main feature tests
- it also tracks important edge cases
- and it can block session completion when higher-confidence must-handle edge
  cases are still failing

So the goal is not "perfect understanding of the whole codebase."
The goal is a practical guardrail layer that catches regressions and forgotten
cases earlier.

Explainer: [landing page link]
Repo: [GitHub link]

Would love feedback from people actually using AI coding tools:
- does this solve a real pain point for you?
- what feels useful vs too heavy?
- would you want this as a CLI, MCP, or built into the agent workflow?

## r/ClaudeAI

Keep this one grounded and clearly Claude-related.

**Title**

I built Tether with Claude Code to reduce cross-feature regressions in AI coding sessions

**Draft**

I built **Tether**, a guardrail tool for AI coding workflows, and Claude Code was
a big part of building and dogfooding it.

What Tether does:
- builds a feature ledger for the repo
- checks blast radius before edits
- watches for drift during the session
- verifies both main tests and important edge cases at the end

The newest part I added is confidence-gated verification:
if Tether sees a must-handle edge case with high enough confidence, the session
does not count as done until that passes too.

This is not formal verification or deep semantic understanding of every repo.
It is a practical safety layer for the kind of "fix one thing, break another"
mistakes that happen in AI-assisted coding.

Free to try:
- landing page: [landing page link]
- GitHub: [GitHub link]

I’d love feedback from Claude Code users:
- is this a real problem in your workflow?
- which part matters most: plan, watch, or verify?
- what would make this worth adding to your stack?

## r/SideProject

This one should read more like a build story than a product pitch.

**Title**

Built a tool to stop AI coding sessions from quietly breaking unrelated features

**Draft**

I built a side project called **Tether** after running into a pattern I really
did not like in AI coding sessions:
the agent would solve the requested task, but quietly damage something else in
the repo.

The idea behind Tether is simple:
- make a map of what the codebase does
- check what a planned edit might affect
- watch for drift during the session
- verify the main tests and the important edge cases afterward

The part I’m most interested in right now is edge-case enforcement.
It’s easy for a session to "look done" because the happy path passed.
Tether can now keep the session open until higher-confidence must-handle edge
cases pass too.

Landing page: [landing page link]
GitHub: [GitHub link]

Would love honest feedback:
- does the problem feel real?
- does this workflow feel too heavy or about right?
- what would make it actually useful in a real repo?
