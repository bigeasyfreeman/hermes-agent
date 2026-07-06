# Torben Monarch Savings Research Loop

Date: 2026-06-27

## Objective

Create a Torben finance research loop whose goal is to save money by finding:

- subscriptions, licenses, and recurring vendors that can be cancelled, downgraded, or renegotiated,
- anomalous spend that needs review,
- duplicate or unexpected charges,
- budget/cashflow drift that points to practical savings actions.

The first production version should be read-only and staged. It may surface recommendations and create FIN review handles. It must not mutate Monarch, move money, create/delete/update transactions, edit categories, edit rules, or modify goals.

## Current Repo And Live-State Findings

- The live Torben profile has Monarch configured and authenticated as an OAuth MCP server:
  - repo evidence: `profiles/torben/config/auth_cutover.snapshot.yaml:24-28`
  - live command: `HERMES_HOME=/Users/ericfreeman/.hermes/profiles/torben /Users/ericfreeman/.local/bin/hermes mcp list`
  - result: `monarch-money-mcp https://api.monarch.com/mcp all enabled`
- `torben auth-check --json` is green for finance MCP registration:
  - `valid=true`
  - `missing_mcp_connectors=[]`
  - `disabled_mcp_connectors=[]`
  - `mcp_native_connectors=["robinhood-agentic-mcp","monarch-money-mcp"]`
- `hermes mcp test monarch-money-mcp` connects and discovers 41 tools.
  - Useful read tools: `GetTransactions`, `GetRecurring`, `GetSpendingByCategory`, `GetBudget`, `GetCashFlow`, `GetAccounts`, `GetMerchants`, `ListRules`.
  - Write/mutation tools are also available and must be blocked by this loop: `CreateTransaction`, `UpdateTransaction`, `BulkUpdateTransactions`, `BulkRecategorizeTransactions`, `DeleteTransaction`, `CreateRule`, `DeleteRule`, category/tag/merchant/goal writes, and goal contribution/withdrawal tools.
- Hermes already has a `FinanceSlice` that can stage Monarch recommendations:
  - `hermes_cli/signal_coo/finance.py:124-150` routes `personal_finance_signals` / `monarch_signals`.
  - `hermes_cli/signal_coo/finance.py:205-231` stages a `monarch_review` action with `mutation_status=draft_only` and text saying nothing changed in Monarch.
- The live cron surface currently has `torben-finance-radar` every 30 minutes, but that loop is Ratatosk/equity focused:
  - `profiles/torben/cron/jobs.snapshot.json:89-95`
  - keep Monarch savings as a separate job family to avoid mixing personal spend review with trading/equity research.
- Current automation policy allows finance research/paper canaries but only explicitly models live orders:
  - `profiles/torben/config/torben-automation-policy.yaml:58-73`
  - implementation should add a separate `finance.monarch_mutations` block, disabled by default, so Monarch writes are explicitly fail-closed instead of only implicitly blocked.

## External Product Notes

- Official Monarch connector endpoint in the live profile and repo docs is `https://api.monarch.com/mcp`.
- Monarch's official MCP help page is `https://help.monarch.com/hc/en-us/articles/50207234679956-Monarch-MCP-Connector`.
- The live `hermes mcp test monarch-money-mcp` output is the most reliable current tool-surface proof on this host because it discovers the authenticated tools directly.

## Recommended Loop Design

### Daily Review

Job name: `torben-monarch-savings-daily`

Cadence: daily, morning, after transaction sync is likely complete.

Purpose: catch new anomalies and short-window money leaks.

Read-only inputs:

- `GetTransactions` for the last 2-7 days.
- `GetRecurring` for active and upcoming recurring activity.
- `GetBudget` for current month.
- `GetCashFlow` for current month and trailing 30/90 days.
- `GetSpendingByCategory` for current month and trailing baseline.

Candidate types:

- `new_recurring_candidate`: new merchant or amount pattern that looks recurring.
- `price_increase`: recurring merchant increased materially from prior charge.
- `duplicate_charge`: same merchant and similar amount charged twice inside a short window.
- `category_spike`: category materially above trailing baseline or budget.
- `unexpected_large_charge`: transaction above configured threshold with weak history.
- `trial_or_renewal_watch`: upcoming recurring charge that looks cancellable or negotiable.

Wake policy:

- Stay silent if there are no actionable candidates.
- Wake only when estimated savings, anomaly severity, or decision urgency crosses threshold.
- Never dump a full transaction report into Signal.

### Weekly Audit

Job name: `torben-monarch-savings-weekly`

Cadence: weekly, Monday morning by default.

Purpose: produce a focused savings review across subscriptions, licenses, recurring vendors, and categories.

Read-only inputs:

- `GetRecurring` for all recurring activity.
- `GetTransactions` for trailing 90-180 days.
- `GetMerchants` / merchant history.
- `GetSpendingByCategory` for trailing 3-6 month baseline.
- `GetBudget` and `GetCashFlow`.
- Optional later enrichment: Gmail receipts/renewal notices for cancellation URLs and license context.

Candidate types:

- `cancel_review`: recurring vendor with low-confidence value, duplicate tool overlap, or stale use evidence.
- `downgrade_review`: high-cost plan where lower tier likely exists.
- `renegotiate_review`: annualized vendor spend high enough to justify asking for discount.
- `duplicate_subscription`: multiple vendors/tools in same category, or same merchant across multiple plans.
- `budget_reallocation`: category overrun with specific merchants driving it.

Output:

- Top 5-10 opportunities max.
- Annualized spend and estimated savings.
- Evidence references, not raw account details.
- FIN handles for review actions.
- A running savings ledger: proposed, accepted, rejected, saved, snoozed.

## Candidate Scoring

Each candidate should include:

- `merchant`
- `category`
- `amount`
- `cadence`
- `annualized_cost`
- `estimated_monthly_savings`
- `estimated_annual_savings`
- `confidence`
- `urgency`
- `candidate_type`
- `why_it_matters`
- `recommended_action`
- `evidence_refs`
- `source_window`
- `mutation_status="review_only"`
- `monarch_write_allowed=false`

Suggested score:

```text
score = savings_weight + confidence_weight + urgency_weight + anomaly_weight - risk_penalty
```

Minimum wake thresholds:

- Daily anomaly: score >= 70 or estimated loss/savings >= configured threshold.
- Weekly audit: top candidates above score >= 55, capped at 10.

## Safety Policy

Allowed read-only Monarch tools:

- `GetTransactions`
- `GetRecurring`
- `GetSpendingByCategory`
- `GetBudget`
- `GetCashFlow`
- `GetAccounts`
- `GetMerchants`
- `GetCategories`
- `GetTags`
- `ListRules`

Blocked mutation tools:

- any tool starting with `Create`, `Update`, `Bulk`, `Delete`, `Merge`, `Contribute`, or `Withdraw`
- any transaction, category, merchant, tag, rule, account-balance, or goal write

Signal redaction:

- Show merchant, category, cadence, amount, and savings estimate.
- Do not show full account numbers, full transaction IDs, household member details, or long raw transaction lists.
- Evidence refs should be stable hashes or short IDs, not full sensitive payloads.

Policy gap to close:

Add this to `profiles/torben/config/torben-automation-policy.yaml`:

```yaml
finance:
  monarch_research:
    auto_invoke:
      daily_review: true
      weekly_audit: true
    allowed_read_tools:
      - GetTransactions
      - GetRecurring
      - GetSpendingByCategory
      - GetBudget
      - GetCashFlow
      - GetAccounts
      - GetMerchants
      - GetCategories
      - GetTags
      - ListRules
  monarch_mutations:
    enabled: false
    allowed_tools: []
    allowed_mutation_types: []
    max_per_run: 0
    approval_mode: explicit_signal_handle
    dry_run_required: true
    audit_log_path: state/torben-monarch-mutation-audit.jsonl
```

## Implementation Slice

### Slice 1: Fixture Analyzer

Add:

- `hermes_cli/signal_coo/monarch_savings.py`
- `tests/test_torben_monarch_savings.py`
- fixture data for transactions, recurring activity, category spend, budget, and cashflow

Behavior:

- analyze fixture packets only,
- detect recurring/license/subscription opportunities,
- detect anomalies,
- create a normalized candidate list,
- render JSON/TXT artifacts,
- prove no mutation counters.

### Slice 2: Read-Only MCP Wrapper

Add a tiny wrapper that can call only allowlisted Monarch read tools through the existing MCP client.

Why needed:

- Hermes has MCP discovery and agent-tool registration.
- There is no public `hermes mcp call` command.
- Scheduled `no_agent` scripts need a deterministic, testable way to call `GetRecurring` / `GetTransactions` without giving the loop write tools.

Acceptance:

- wrapper refuses every blocked tool name,
- wrapper records `read_tool_calls`,
- wrapper records `blocked_tool_calls`,
- wrapper redacts sensitive fields before artifacts/logs,
- live canary calls only `GetRecurring` or another low-risk read tool.

### Slice 3: Daily And Weekly Cron Scripts

Add:

- `profiles/torben/scripts/torben_monarch_savings.py`
- `torben-monarch-savings-daily`
- `torben-monarch-savings-weekly`

Artifacts:

- `state/torben-monarch-savings-daily-latest.json`
- `state/torben-monarch-savings-daily-latest.txt`
- `state/torben-monarch-savings-weekly-latest.json`
- `state/torben-monarch-savings-weekly-latest.txt`
- `state/torben-monarch-savings-state.json`
- `state/torben-monarch-savings-ledger.json`

Counters:

- `monarch_read_calls`
- `monarch_write_calls=0`
- `external_mutations=0`
- `recommendations_created`
- `estimated_monthly_savings`
- `estimated_annual_savings`

### Slice 4: Torben Integration

Wire candidates into existing FIN action style:

- daily anomaly handle examples:
  - `review spend 1`
  - `ignore spend 1`
  - `snooze merchant 1`
- weekly savings handle examples:
  - `review cancel 1`
  - `mark keep 1`
  - `ask source 1`

No approve path should perform a Monarch write in the first implementation.

## Acceptance Criteria

- `hermes -p torben torben auth-check --json` remains `valid=true`.
- `HERMES_HOME=~/.hermes/profiles/torben hermes mcp test monarch-money-mcp` connects and discovers required read tools.
- Fixture tests prove:
  - subscription/license candidate detection,
  - price increase detection,
  - duplicate charge detection,
  - category spike detection,
  - all write tools are rejected.
- Live daily canary writes artifact with:
  - `external_mutations=0`
  - `monarch_write_calls=0`
  - redaction status pass
  - policy decision present
- Live weekly canary writes artifact with:
  - ranked savings opportunities or `wakeAgent=false`
  - estimated monthly/annual savings totals
  - no raw transaction dump
- `torben-live-profile-verify` includes the two latest Monarch savings artifacts.
- `graphify update .` runs after implementation.

## Recommended First Build Brief

Build the fixture analyzer and policy extension first. Do not connect live Monarch transaction data until fixture tests prove scoring, redaction, and write-tool blocking. Then add one live read-only canary with `GetRecurring` before installing the daily/weekly cron jobs.

This should be a savings research loop, not a cleanup loop. It recommends how to save money; Eric decides what to cancel, downgrade, dispute, or ignore.
