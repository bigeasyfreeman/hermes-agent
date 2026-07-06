---
name: browser-qa
description: Use real browser automation for web change verification, responsive screenshots, console/network checks, and performance traces. Use when Eric asks to verify a web change, audit a live page, check performance, test responsive behavior, or produce browser QA evidence.
---

# Browser QA

## Tooling Preflight

Prefer a Chrome DevTools MCP server that can navigate, screenshot, inspect console and network activity, run performance traces, and emulate devices.

Known host preflight on the Torben machine:

- `npx chrome-devtools-mcp@latest --help` works.
- Google Chrome exists at `/Applications/Google Chrome.app`.
- `chrome-devtools` is configured in the Torben Hermes profile.
- `hermes -p torben mcp test chrome-devtools` connected and discovered 29 tools.

If the MCP is not connected, stop and set it up or ask Eric for the missing harness step. Do not pretend browser evidence exists.

Recommended MCP command:

```bash
npx -y chrome-devtools-mcp@latest --headless --isolated --no-usage-statistics
```

Use an existing debuggable browser with `--browserUrl http://127.0.0.1:9222` only when Eric wants to inspect a logged-in local session.

## Trigger Recipes

Layout changes:

- Screenshot desktop 1440px.
- Screenshot tablet 768px.
- Screenshot mobile 390px.
- Check text overflow, overlap, blank states, and responsive navigation.

Performance-relevant changes:

- Run a trace.
- Report LCP, INP, CLS, and relevant long tasks or network bottlenecks.
- Compare against stated thresholds. If no thresholds are stated, use reasonable defaults and label them as defaults.

New features:

- Script the core walkthrough.
- Check console errors.
- Check failed requests.
- Check loading, empty, success, error, and auth states where applicable.

Bug fixes:

- Reproduce old failure if possible.
- Verify the fixed path.
- Check adjacent regressions.

## Evidence Rule

Every finding needs evidence:

- screenshot path,
- metric,
- trace path,
- console excerpt,
- network failure excerpt,
- reproduction steps.

No unevidenced "looks fine" claims.

## Integration With Runbooks

Use `testing-runbook-creator` and `page-testing-memory`.

Write page-specific testing facts to the repo runbook:

- routes,
- selectors,
- auth setup,
- seed data,
- cleanup,
- exact expected states.

Do not store page-specific facts in this skill.

## Report Format

```markdown
# Browser QA Report

## Checked
- URL/page:
- Change type:
- Browser/tool:
- Viewports:

## Passed With Evidence
- Check:
- Evidence:

## Failed
### Finding
- Severity:
- Evidence:
- Reproduction:
- Expected:
- Actual:

## Not Verified
- ...

## Runbook Updates
- path#section:
```

## Safety

Do not submit forms that send email, post publicly, trade, delete, charge money, or mutate production data without explicit approval. Use staging, dry-run, fake accounts, or stop.
