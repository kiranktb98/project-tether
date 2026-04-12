"""Verbatim watcher prompt templates.

Each prompt is stored as a (SYSTEM, USER_TEMPLATE) pair.
USER_TEMPLATE strings use Python's str.format() for substitution.
Tool schemas are stored as JSON Schema dicts alongside each prompt.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# BOOTSTRAP_FEATURE_PROPOSAL
# ---------------------------------------------------------------------------

BOOTSTRAP_SYSTEM = """You are analyzing an existing Python codebase to identify
its features. You will be given a chunk of the codebase as a list of
files with their top-level functions, classes, and module docstrings.

Your job: propose a list of distinct features this code chunk implements.
A "feature" is a meaningful piece of user-facing or system functionality
that could be described in a single sentence (e.g. "user authentication
via JWT", "rate limiting per IP address", "background job queue").

For each proposed feature, provide:
- name: short descriptive name
- description: one sentence explaining what the feature does
- files: which files in this chunk implement it (a feature may span many files)
- guessed_edge_cases: 2-4 edge cases this feature should handle

Rules:
- Group by domain / capability, NOT by file. Ten small helper files that
  together implement one system (e.g. "feature ledger CRUD") are one feature,
  not ten features.
- Aim for 3–8 features per chunk. If a chunk has 20 files but 4 logical
  capabilities, return 4 features.
- Leave out scaffolding, boilerplate, and configuration files unless they
  implement genuine logic.
- Ignore tests, fixtures, sample projects, generated artifacts, and
  __pycache__ content even if they appear in the input.
- Avoid duplicate or near-duplicate features with slightly different names.
- If you're not sure something is a feature, omit it — the user reviews
  and can add missing features.

Return using the propose_features tool."""

BOOTSTRAP_USER_TEMPLATE = """Code chunk ({chunk_index} of {total_chunks}):

{static_scan_yaml}

Propose features."""

BOOTSTRAP_TOOL_NAME = "propose_features"
BOOTSTRAP_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "features": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "guessed_edge_cases": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["name", "description", "files"],
            },
        }
    },
    "required": ["features"],
}


# ---------------------------------------------------------------------------
# EDGE_CASE_ENUMERATION
# ---------------------------------------------------------------------------

EDGE_CASE_SYSTEM = """You are an experienced engineer enumerating edge cases for
a software feature. Given a feature description, list edge cases the
implementation must handle, and for each one estimate how often it will
occur in realistic production traffic.

Frequency labels:
- high: occurs in >1% of operations
- medium: 0.01%-1%
- low: <0.01% but a known real scenario
- negligible: theoretically possible but vanishingly rare

For each edge case, provide a one-sentence rationale. If the case is
rare but catastrophic (data loss, security breach, system crash), say
so explicitly in the rationale.

Return between 4 and {count} edge cases (fewer is fine for simple features).
Prefer realistic, well-grounded cases over exotic ones. Stop when you have
covered the genuine risk surface — do not pad to hit the maximum.

Return using the enumerate_edge_cases tool."""

EDGE_CASE_USER_TEMPLATE = """Feature: {feature_name}
Description: {feature_description}
Files: {feature_files}

Project: {project_name}

Enumerate the most important edge cases (up to {count})."""

EDGE_CASE_TOOL_NAME = "enumerate_edge_cases"
EDGE_CASE_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "edge_cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "frequency": {
                        "type": "string",
                        "enum": ["high", "medium", "low", "negligible"],
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["description", "frequency", "rationale"],
            },
        }
    },
    "required": ["edge_cases"],
}


# ---------------------------------------------------------------------------
# TEST_GENERATION
# ---------------------------------------------------------------------------

TEST_GEN_SYSTEM = """You are writing a single pytest test for one specific edge
case of a specific feature. The test must:

- Be a single function named test_<descriptive_snake_case>
- Be self-contained: no network, no database, no external services
- Run in under 1 second
- Test exactly one edge case
- Use only stdlib and pytest, unless the project clearly exposes a
  public API you can import
- Never invent classes, functions, methods, modules, or imports that are
  not clearly present in the provided feature files or project tree.
- Prefer narrow, import-light tests over ambitious integration tests.
- If there is any uncertainty about the callable name, import path, or
  public interface, emit a minimal skipped pytest stub instead of guessing.
- If the code being tested doesn't yet exist, mark with
  @pytest.mark.skip(reason="awaiting implementation") and write the
  test against the expected interface

Return only the Python source for the test (and any imports). No
explanations, no markdown fences."""

TEST_GEN_USER_TEMPLATE = """Feature: {feature_name}
Edge case: {edge_case_description}
Frequency rationale: {edge_case_rationale}
Files implementing this feature: {feature_files}

Project root structure:
{project_tree}

Write the pytest test."""

TEST_GEN_TOOL_NAME = "generate_test"
TEST_GEN_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "test_source": {
            "type": "string",
            "description": "Complete Python source for the pytest test function.",
        }
    },
    "required": ["test_source"],
}


# ---------------------------------------------------------------------------
# IMPACT_ANALYSIS
# ---------------------------------------------------------------------------

IMPACT_SYSTEM = """You are analyzing the potential impact of a planned code
change on existing features in a project. You will be given:

- The file that will be changed
- A description of the planned change
- A list of features whose code touches that file (the "affected set")

For each affected feature, decide a risk level:
- none: this feature is not meaningfully affected
- low: feature behavior could shift slightly but is unlikely to break
- medium: there's a real chance the change breaks an aspect of this feature
- high: the change is very likely to break this feature unless mitigated

For each risk level >= medium, also propose a mitigation: a specific,
concrete suggestion for how to make the change without breaking the
feature.

Return using the analyze_impact tool."""

IMPACT_USER_TEMPLATE = """File to be changed: {file_path}
Planned change: {intent}

Recent diff (if any):
{diff}

Affected features:
{affected_features_yaml}

Analyze the impact."""

IMPACT_TOOL_NAME = "analyze_impact"
IMPACT_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "feature_id": {"type": "string"},
                    "level": {
                        "type": "string",
                        "enum": ["none", "low", "medium", "high"],
                    },
                    "reason": {"type": "string"},
                    "mitigation": {"type": ["string", "null"]},
                },
                "required": ["feature_id", "level", "reason"],
            },
        },
        "overall_risk": {
            "type": "string",
            "enum": ["none", "low", "medium", "high"],
        },
    },
    "required": ["risks", "overall_risk"],
}


# ---------------------------------------------------------------------------
# INTENT_CHECK
# ---------------------------------------------------------------------------

INTENT_SYSTEM = """You are checking whether a single file change aligns with
the project's current feature ledger. You will be given:

- A unified diff of the change
- A list of features whose code touches the changed file
- Whether any of those features' tests are now failing

Decide one of:
- aligned: the change clearly improves or maintains an existing feature
- neutral: the change is cosmetic, refactoring, or unrelated to features
- drifted: the change appears to break or contradict a feature's intent
- looks_intentional: a feature's tests are now failing, BUT the change
  looks like a clean deliberate removal or replacement (e.g. function
  cleanly deleted with imports removed). Use this when the change feels
  purposeful rather than accidental, even though it broke something.
  This signals the user is changing direction and the ledger needs an
  update.

Be specific in your reason. Reference feature IDs (e.g. f3, f8) when
drift is detected. Be conservative on `drifted` — refactors are usually
neutral. Be generous on `looks_intentional` — if a test broke and the
change looks tidy and purposeful, it's much more likely deliberate
than accidental.

Return using the intent_verdict tool."""

INTENT_USER_TEMPLATE = """File: {file_path}

Diff:
```
{diff}
```

Features touching this file:
{features_yaml}

Failing tests (if any):
{failing_tests}

Verdict?"""

INTENT_TOOL_NAME = "intent_verdict"
INTENT_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["aligned", "neutral", "drifted", "looks_intentional"],
        },
        "reason": {"type": "string"},
        "affected_feature_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["verdict", "reason"],
}


# ---------------------------------------------------------------------------
# DRIFT_ATTRIBUTION
# ---------------------------------------------------------------------------

ATTRIBUTION_SYSTEM = """You are diagnosing why a coding agent made a change that
broke a previously-working test for a feature. You will be given:

- The breaking change (diff)
- The feature whose test broke
- Recent instructions the user gave
- Recent ledger amendments

Identify the single most likely source of this change. Confidence:
- high: a recent instruction directly asked for something that would
  cause this change
- medium: an instruction is consistent with this change
- low: no clear source; the agent appears to have drifted on its own

Return using the attribute_drift tool."""

ATTRIBUTION_USER_TEMPLATE = """Breaking change in {file_path}:
```
{diff}
```

Broken feature: {feature_id} - {feature_name}
Failing test: {test_name}

Recent user instructions:
{recent_instructions}

Recent ledger amendments:
{recent_amendments}

What is the most likely source?"""

ATTRIBUTION_TOOL_NAME = "attribute_drift"
ATTRIBUTION_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "source": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "explanation": {"type": "string"},
    },
    "required": ["source", "confidence", "explanation"],
}
