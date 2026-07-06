# Torben Workflow Operating System

Torben workflow lanes use one staged contract:

`input signal -> deterministic evidence packet -> LLM-trigger decision -> LLM judgment/draft when triggered -> deterministic verification/gate -> approval -> execute -> notify -> record`

Deterministic code owns fetching, fingerprints, state diffs, dedupe, hard
suppressions, counters, verifier commands, and audit trails. LLM calls own
judgment only when a trigger fires: meaningful delta, ambiguity, risk threshold,
user-visible artifact, failed verifier, stakeholder impact, or explicit request.

Quiet unchanged state is a valid short output. Do not pad it.

## Required Lane Fields

- `inputs`
- `normalize`
- `evidence_packet`
- `llm_trigger_policy`
- `llm_owned_outputs`
- `interpret`
- `stage`
- `verify`
- `approve`
- `execute`
- `notify`
- `record`

## Lane Inventory

| Lane | Stage | Deterministic evidence | LLM trigger | Mutation gate |
| --- | --- | --- | --- | --- |
| Finance radar | L1 scheduled scan | Portfolio/research/source packets, broad opportunity universe, scan window, mutation counters | Decision-grade opportunity delta, source conflict, risk threshold, explicit question | No broker order without separate live finance policy and explicit approval |
| EA email/calendar | L1/L2 | Gmail/calendar evidence, deadlines, thread state, mutation counters | Ambiguous priority, scheduling conflict, stakeholder-visible deadline | No send/archive/delete/calendar mutation without approval |
| GTM/content | L1/L2 | Sources, dates, drafts, image/page artifacts, public counters | Release/news delta, source conflict, public-facing draft request | No publish/post/send without approval and QA evidence |
| QA/debug | L0/L1 | Tests, browser traces, screenshots, logs, runbook entries | Failure interpretation, root-cause ambiguity, assumption stress test | No verified claim without concrete evidence |
| Delegation/flywheel | L0/L1 | Operating map, goal prompt, tmux/session ref, verifier gates | Scope split, delegate review, reusable pattern candidate | No merge/ship/closeout until supervisor reruns gates |
| Weekly behavior audit | L1 weekly | Redacted source manifest, behavior records, candidate/rejection ledger | Recurring, non-obvious, codifiable pattern with validation plan | No live skill installation without review |

## Promotion Model

- `L0 manual`: user asks for a run; Torben stages evidence and output.
- `L1 scheduled scan`: deterministic scan writes no-change or evidence packet;
  LLM judgment runs only when trigger rules fire.
- `L2 approval-gated action`: Torben prepares a mutation request for explicit
  approval after verified staged output.
- `L3 autonomous mutation`: out of scope unless a separate approved policy
  already allows it.

## Observability

Every lane artifact should expose:

- `last_run_at` or `generated_at`
- input fingerprints or source manifest
- evidence-packet path or source refs
- `llm_triggered`
- `llm_trigger_reason` or `no_llm_reason`
- staged artifact path or action handles
- verifier status
- approval status
- mutation counters
- degraded reason if applicable
- next recommended action

Finance artifacts additionally expose `scan_window`,
`opportunity_universe_version`, `candidate_class_counts`,
`underfollowed_signal_count`, and broker/order counters.

Weekly audit artifacts additionally expose `source_manifest`,
`recurring_patterns_count`, `rejected_patterns_count`,
`proposed_skill_count`, `proposed_runbook_update_count`, and `review_status`.
