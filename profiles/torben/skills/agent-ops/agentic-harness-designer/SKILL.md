---
name: agentic-harness-designer
description: Design, review, or debug agent-powered systems as full agent harnesses rather than model-choice problems. Use for AI-agent products, serious automations, tool-using systems, multi-agent workflows, approval-gated loops, or agent stack architecture reviews.
---

# Agentic Harness Designer

## Core Framing

Treat the problem as an agent system problem, not a model choice problem. The design is only credible when tools, permissions, state, memory, evals, observability, and failure modes are explicit.

## Design Walk

Proceed in this order:

1. Tools and contracts.
   - What tools does the agent get?
   - What are exact inputs, outputs, side effects, and failure modes?
2. Permission model.
   - What is autonomous?
   - What needs approval?
   - What is forbidden?
3. Workflow state and durability.
   - What survives crash, restart, retry, or handoff?
   - Where is state stored?
4. Context and memory.
   - What does the agent know?
   - Where does it come from?
   - What must it not accumulate?
5. Evaluation.
   - What concrete checks prove it works?
   - What fixtures, canaries, regression tests, and acceptance gates exist?
6. Observability.
   - What is logged?
   - What can the operator inspect mid-run?
   - How are actions, approvals, and failures audited?
7. Failure modes.
   - Missing approval gates.
   - Non-durable state.
   - Unbounded context growth.
   - No evals.
   - Invisible execution.
   - Tool contract ambiguity.
   - Retry loops with side effects.

## Output

Produce a design doc:

```markdown
# Agentic Harness Design: Name

## System Goal

## Tool Contracts

## Permission Model

## Durable State

## Context And Memory

## Evaluation Plan

## Observability

## Failure-Mode Review

## Decisions And Rationale

## Phased Implementation Plan
### Phase 1
- Scope:
- Why independently shippable:
- Verification:

### Phase 2
...
```

## Phasing Rule

Each phase must be independently shippable and testable. If a phase cannot be verified without future phases, split it smaller.

## Safety Defaults

- Discovery, validation, drafting, scheduling, and execution are separate actions.
- External mutations require explicit approval unless a narrow approved policy exists.
- Agent work should be visible or auditable.
- A model upgrade is not a system design.
