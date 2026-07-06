---
name: page-testing-memory
description: Apply a global page/UI QA process while keeping page-specific selectors, routes, accounts, seed data, and cleanup quirks in the repo testing runbook. Use for QA or verification of any web page or UI.
---

# Page Testing Memory

## Knowledge Split

Process lives in this skill. Project facts do not.

Keep these in the repo testing runbook, not here:

- selectors,
- routes,
- test accounts,
- seed data,
- cleanup quirks,
- feature-specific expected outputs,
- project-specific auth behavior.

If you want to add a project detail to this skill, that is the signal it belongs in the repo runbook.

## Partner Skill

Use `testing-runbook-creator` for the repo-local runbook. Before QA, read the repo runbook. During QA, write page-specific discoveries immediately.

## General Page QA Process

1. Identify page purpose and user workflow.
2. Identify states:
   - empty,
   - loading,
   - loaded,
   - error,
   - partial/degraded,
   - unauthorized/auth-expired.
3. Test forms with:
   - valid input,
   - invalid input,
   - empty input,
   - boundary length,
   - special characters,
   - duplicate submit,
   - slow network if relevant.
4. Verify auth boundaries:
   - logged out,
   - wrong role,
   - expired session,
   - direct URL access.
5. Check responsive behavior at standard breakpoints:
   - mobile 390px,
   - tablet 768px,
   - desktop 1440px.
6. Check console errors and failed network requests when browser tooling is available.
7. Capture screenshots or artifacts as evidence.
8. Update the repo runbook with page-specific facts.

## Output

Report:

- Page/workflow checked.
- States covered.
- Breakpoints covered.
- Findings with evidence.
- What was written to the repo runbook.

No unevidenced "looks fine" claims. If evidence is missing, say what was not verified.
