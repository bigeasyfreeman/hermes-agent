# Torben Morning Brief Signal Rubric

This rubric is the forcing function for the daily email and calendar brief. The scripts gather bounded evidence, dedupe repeated findings, apply approved hard suppressions, and cap candidate volume. The LLM decides what is worth surfacing.

## Judgment Principles

- Surface fewer, sharper items. The brief should usually stay one screen and should not become a newsletter digest.
- Prefer evidence that Eric can act on, reuse, write about, ask about, or make a decision from today.
- Use article synopsis, source excerpt, named tools, key concepts, best link, attendee/domain context, relationship context, and explicit unknowns before deciding.
- Do not surface something only because it came from a priority source. Priority source status is evidence, not a final decision.
- Do not suppress something only because it lacks an existing deterministic keyword. If the evidence is concrete and relevant, judge it.
- When context is missing, say what is unknown and give the next decision-forcing question.

## Meetings

Surface a meeting when it has one of these signals:

- It has a concrete decision, blocker, customer, investor, partner, family, school, finance, legal, or scheduling implication.
- It is an intro call where the useful output is deciding whether to continue, what would make it worth continuing, or what would block it.
- The attendee or company context is known from relationship context or a verifiable domain hint.
- The agenda is weak but the person/company could matter and the brief can give Eric a practical question without inventing context.

For weak-context meetings:

- Do not invent the agenda.
- If person/company context is absent, say that it is absent.
- Use: "What would make this worth continuing, and what would block it?" as the default founder-chat question.
- Protected blocks need no prep unless they are likely hidden meetings.

## Security, AI, And Tooling

Surface a story/tool when it has at least one of these signals:

- Concrete security relevance: exploit, abuse pattern, cloud/security operations risk, identity/OAuth risk, agent/MCP risk, supply-chain risk, or a material vendor/security incident.
- Concrete builder relevance: repo, tool, framework, workflow, benchmark, engineering handbook, agentic loop, static analysis, or operational pattern Eric may inspect or adapt.
- Thought-leadership relevance: a timely concept Eric could write about or use to sharpen product/market thinking.
- Cross-source corroboration: the same story appears across multiple newsletters and the angle is not stale.

Examples that should be considered when the evidence supports them: Geiger, SAIST, agentic loops, L8s/principals engineering workflow, static analysis of agentic coding, and fintech engineering handbooks.

Do not surface:

- A headline with no synopsis, concept, tool, or next use.
- A generic "AI news" recap.
- A priority newsletter item that is only a link farm and has no clear reason Eric should care.
- Duplicate stories already seen recently unless the angle materially changed.

## Output Bar

Every surfaced item needs:

- What it is.
- Why Eric cares.
- The evidence used.
- The next question, action, or inspection path.
- A best link when available.

Every suppressed item should have a short reason if the output format asks for suppressed items.
