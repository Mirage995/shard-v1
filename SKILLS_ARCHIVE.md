# Superpowers Skills — Archive (disattivate)
#
# Queste skill NON sono caricate automaticamente.
# Per riattivarle: copia il contenuto in CLAUDE.md.
# Fonte originale: https://github.com/obra/superpowers

---

## SKILL: systematic-debugging

**Use when:** any bug, test failure, unexpected behavior, before proposing fixes.

### The Iron Law
```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```
If Phase 1 is not complete, fixes cannot be proposed.

### The Four Phases

**Phase 1 — Root Cause Investigation** (MUST complete before any fix)
1. Read error messages completely — stack traces, line numbers, file paths
2. Reproduce consistently — if not reproducible, gather more data, don't guess
3. Check recent changes — git diff, recent commits, env differences
4. In multi-component systems: add diagnostic instrumentation at each boundary, run once to gather evidence, THEN analyze
5. Trace data flow backward through call stack to find where bad value originates

**Phase 2 — Pattern Analysis**
- Find working examples in the same codebase
- Read reference implementations completely — no skimming
- List every difference between working and broken, however small

**Phase 3 — Hypothesis and Testing**
- Form ONE specific hypothesis: "I think X is the root cause because Y"
- Make the SMALLEST possible change to test it
- One variable at a time — never stack multiple fixes
- If wrong: form NEW hypothesis, don't add more fixes on top

**Phase 4 — Implementation**
1. Create a failing test case first
2. Implement ONE fix addressing the root cause
3. Verify: test passes, no regressions
4. If fix doesn't work: return to Phase 1 with new information
5. **If 3+ fixes have failed: STOP — question the architecture, discuss before continuing**

### Red Flags — STOP and return to Phase 1
- "Quick fix for now, investigate later"
- "Just try changing X and see"
- Proposing solutions before tracing data flow
- "One more fix attempt" after 2+ failures
- Each fix reveals a new problem in a different place

### User signals you're doing it wrong
- "Is that not happening?" → you assumed without verifying
- "Stop guessing" → proposing fixes without understanding
- "Ultrathink this" → question fundamentals, not symptoms

---

## SKILL: brainstorming

**Use when:** any new feature, component, behavior change, or non-trivial implementation.

### The Hard Gate
```
DO NOT write any code or invoke any implementation action
until you have presented a design and the user has approved it.
```

### Process
1. Explore project context (relevant files, recent commits, existing patterns)
2. Ask clarifying questions — ONE at a time, prefer multiple choice
3. Propose 2-3 approaches with explicit trade-offs
4. Present design in sections, get approval per section
5. Write a concise design document before coding
6. Self-review the spec for gaps and inconsistencies
7. Only after user approval: proceed to implementation

### Rules
- Never dismiss a task as "too simple for design" — unexamined assumptions cause the most waste
- Follow existing codebase patterns; don't restructure unilaterally
- YAGNI ruthlessly — only what's needed for the current goal
- If scope is large: split into sub-tasks, each with its own design gate

---

## SKILL: writing-plans

**Use when:** any multi-step implementation task before writing code.

### Core Requirement
Break work into **2-5 minute tasks**, each with:
- Exact file paths
- Complete code blocks (no placeholders like "TBD", "add validation", "similar to Task N")
- Verification step (test command + expected output)
- Commit point

### Task Structure (TDD pattern)
```
1. Write failing test
2. Verify test fails (run it)
3. Implement the fix/feature
4. Verify test passes
5. Commit
```

### Forbidden language in plans
- "TBD"
- "appropriate error handling"
- "similar to the previous task"
- "add validation"
- Any step without actual code

### Self-review before executing
- Every requirement has a corresponding task
- No placeholder language anywhere
- Type/method names are consistent across all tasks

---

## SKILL: verification-before-completion

**Use when:** about to claim work is complete, tests pass, bug is fixed, or feature is done.

### The Iron Law
```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```
If the verification command has not been run in THIS message, the claim cannot be made.

### The Five-Step Gate
1. **Identify** the exact command that proves the claim
2. **Run** it completely (fresh execution, not from memory)
3. **Read** the full output and exit code
4. **Verify** the output actually confirms the claim
5. **Only then** make the claim

### Red Flag Language — STOP before claiming success
- "should pass", "probably works", "seems correct"
- "Great!", "Perfect!", "Done!" before running verification
- Trusting previous run output
- Partial output ("first 10 tests pass" ≠ "all tests pass")

### What counts as verification
- Tests: must show full output with 0 failures
- Linter: must show complete clean output
- Bug fix: must demonstrate the original symptom is gone
- Delegated work: must independently verify, not trust agent report
