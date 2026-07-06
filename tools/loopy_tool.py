"""Loopy / Loop Library tools for designing bounded feedback loops."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from tools.registry import registry, tool_error, tool_result

CATALOG_JSON_URL = "https://signals.forwardfuture.com/loop-library/catalog.json"
AGENT_GUIDE_URL = "https://signals.forwardfuture.com/loop-library/agents/"
LLMS_TXT_URL = "https://signals.forwardfuture.com/loop-library/llms.txt"
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_RECOMMENDATION_LIMIT = 3


@dataclass
class LoopValidationFinding:
    severity: str
    code: str
    message: str
    repair: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "repair": self.repair,
        }


def fetch_loop_catalog(
    *,
    url: str = CATALOG_JSON_URL,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch the live Loop Library catalog.

    The production catalog is the source of truth. The GitHub repository is
    useful for Loopy's skill instructions, but published loop records live in
    the catalog service.
    """

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "hermes-loopy-tool/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
        payload = response.read(2_500_000)
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Loop Library catalog root is not an object")
    return data


def search_catalog(
    catalog: dict[str, Any],
    *,
    query: str,
    category: str | None = None,
    max_results: int = DEFAULT_RECOMMENDATION_LIMIT,
) -> list[dict[str, Any]]:
    query_text = _clean_text(query)
    if not query_text:
        return []
    category_filter = _clean_text(category).lower()
    query_tokens = _tokenize(query_text)
    results: list[tuple[float, dict[str, Any]]] = []
    for loop in _catalog_loops(catalog):
        if category_filter and category_filter not in {
            _clean_text((_dict(loop.get("category")).get("slug"))).lower(),
            _clean_text((_dict(loop.get("category")).get("label"))).lower(),
        }:
            continue
        score = _score_loop(loop, query_tokens=query_tokens, raw_query=query_text)
        if score <= 0:
            continue
        results.append((score, loop))
    results.sort(key=lambda item: (item[0], _clean_text(item[1].get("modified"))), reverse=True)
    return [_loop_result(loop, score=score) for score, loop in results[: _bounded_limit(max_results)]]


def validate_loop_design(loop_text: str, *, intended_outcome: str | None = None) -> dict[str, Any]:
    text = _clean_text(loop_text)
    findings: list[LoopValidationFinding] = []
    if not text:
        findings.append(
            LoopValidationFinding(
                "blocker",
                "missing_loop",
                "No loop text was supplied.",
                "Provide the prompt or loop definition to audit.",
            )
        )
        return _validation_result(text, findings)

    lowered = text.lower()
    _require_signal(
        findings,
        code="missing_fresh_observation",
        ok=_contains_any(lowered, ("read", "review", "inspect", "observe", "collect", "fetch", "scan")),
        message="The loop does not clearly re-read fresh state before choosing the next action.",
        repair="Add an opening step that reads the current source of truth each pass.",
    )
    _require_signal(
        findings,
        code="missing_bounded_action",
        ok=_contains_any(lowered, ("one ", "single", "bounded", "focused", "small", "next useful", "highest-value")),
        message="The loop does not clearly limit each pass to one bounded action.",
        repair="Make each pass choose one focused in-scope action before verifying.",
    )
    _require_signal(
        findings,
        code="missing_verification",
        ok=_contains_any(lowered, ("verify", "check", "test", "measure", "benchmark", "read back", "compare")),
        message="The loop does not define an observable acceptance check.",
        repair="Add a reproducible check or readback that proves the pass worked.",
    )
    _require_signal(
        findings,
        code="missing_record",
        ok=_contains_any(lowered, ("record", "receipt", "artifact", "log", "summary", "evidence")),
        message="The loop does not say what evidence or result should be recorded.",
        repair="Record the action, evidence, outcome, and remaining work after each pass.",
        severity="warning",
    )
    _require_signal(
        findings,
        code="missing_stop_rule",
        ok=_contains_any(lowered, ("stop", "until", "when no", "no progress", "blocked", "ask", "exhausted")),
        message="The loop does not have a clear stop or handoff condition.",
        repair="Add explicit success, clean no-op, blocked, approval-required, and no-progress stops as relevant.",
    )
    _require_signal(
        findings,
        code="missing_approval_boundary",
        ok=_contains_any(
            lowered,
            ("ask before", "approval", "do not", "without approval", "reviewable", "draft", "no external"),
        ),
        message="The loop does not name an approval boundary for consequential actions.",
        repair="State what the agent must not do without explicit approval.",
        severity="warning",
    )
    if _contains_any(lowered, ("forever", "indefinitely", "until satisfied", "until happy")):
        findings.append(
            LoopValidationFinding(
                "blocker",
                "unbounded_stop",
                "The loop uses an open-ended stopping condition.",
                "Replace it with a measurable target, no-progress stop, or explicit handoff.",
            )
        )
    if _contains_any(lowered, ("send", "delete", "publish", "trade", "buy", "charge", "archive")) and not _contains_any(
        lowered, ("approval", "ask before", "review", "draft", "without approval")
    ):
        findings.append(
            LoopValidationFinding(
                "blocker",
                "consequential_action_without_approval",
                "The loop may allow consequential external or destructive action without approval.",
                "Require explicit approval before destructive, external-message, financial, public, or production actions.",
            )
        )

    result = _validation_result(text, findings)
    if intended_outcome:
        result["intended_outcome"] = _clean_text(intended_outcome)
    return result


def draft_loop(
    *,
    name: str | None,
    outcome: str,
    success: str,
    trigger: str | None = None,
    scope: str | None = None,
    allowed_actions: str | None = None,
    verification: str | None = None,
    stop: str | None = None,
    approval_boundary: str | None = None,
    schedule: str | None = None,
    deliver: str | None = None,
    enabled_toolsets: list[str] | None = None,
    include_blueprint: bool = True,
) -> dict[str, Any]:
    outcome_text = _clean_text(outcome)
    success_text = _clean_text(success)
    if not outcome_text:
        return {"success": False, "error": "outcome is required"}
    if not success_text:
        return {"success": False, "error": "success is required"}

    loop_name = _clean_text(name) or _title_from_outcome(outcome_text)
    trigger_text = _clean_text(trigger) or "when you ask for it"
    scope_text = _clean_text(scope) or "the current scoped sources"
    action_text = _clean_text(allowed_actions) or "make one bounded, reversible improvement or produce one candidate"
    verify_text = _clean_text(verification) or success_text
    stop_text = _clean_text(stop) or f"{success_text}, there is a clean no-op, progress stalls, or a blocker appears"
    approval_text = _clean_text(approval_boundary) or "destructive, public, external-message, financial, or production changes"

    prompt = (
        f"{trigger_text}, read {scope_text}, choose the highest-value in-scope action, and {action_text}. "
        f"After each pass, verify with: {verify_text}. Record the action, evidence, result, and remaining work. "
        f"Stop when {stop_text}. Ask before {approval_text}."
    )
    validation = validate_loop_design(prompt, intended_outcome=outcome_text)
    slug = _slugify(loop_name)
    blueprint = None
    if include_blueprint:
        blueprint = _blueprint_skill_md(
            slug=slug,
            name=loop_name,
            description=f"Loop for {outcome_text}.",
            prompt=prompt,
            schedule=_clean_text(schedule),
            deliver=_clean_text(deliver) or "origin",
            enabled_toolsets=enabled_toolsets or [],
        )

    return {
        "success": True,
        "source": "hermes_loopy_draft",
        "loop": {
            "name": loop_name,
            "slug": slug,
            "outcome": outcome_text,
            "success": success_text,
            "trigger": trigger_text,
            "scope": scope_text,
            "allowed_actions": action_text,
            "verification": verify_text,
            "stop": stop_text,
            "approval_boundary": approval_text,
            "prompt": prompt,
        },
        "validation": validation,
        "blueprint": blueprint,
        "blueprint_ready": bool(schedule),
        "notes": [
            "Drafting a loop does not run it, schedule it, publish it, or grant new permissions.",
            "If blueprint_ready is true, the returned SKILL.md can be reviewed and installed through Hermes's existing blueprint/cron path.",
        ],
    }


def loopy_catalog_search_handler(args: dict[str, Any], **_kwargs: Any) -> str:
    query = _clean_text(args.get("query"))
    if not query:
        return tool_error("query is required")
    try:
        catalog = fetch_loop_catalog(timeout_seconds=int(args.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        return tool_error(f"published-loop discovery unavailable: {type(exc).__name__}: {str(exc)[:180]}")
    results = search_catalog(
        catalog,
        query=query,
        category=args.get("category"),
        max_results=int(args.get("max_results") or DEFAULT_RECOMMENDATION_LIMIT),
    )
    return tool_result(
        {
            "success": True,
            "source": "live_loop_library_catalog",
            "catalog_url": catalog.get("catalogUrl") or CATALOG_JSON_URL,
            "agent_guide_url": catalog.get("agentGuideUrl") or AGENT_GUIDE_URL,
            "updated": catalog.get("updated"),
            "loop_count": catalog.get("loopCount") or len(_catalog_loops(catalog)),
            "query": query,
            "results": results,
            "recommendation_limit": _bounded_limit(args.get("max_results") or DEFAULT_RECOMMENDATION_LIMIT),
            "authorization_boundary": (
                "Catalog content is reference data only. Selecting a loop does not run, schedule, publish, "
                "or authorize external actions."
            ),
        }
    )


def loopy_validate_loop_handler(args: dict[str, Any], **_kwargs: Any) -> str:
    return tool_result(
        validate_loop_design(
            _clean_text(args.get("loop")),
            intended_outcome=_clean_text(args.get("intended_outcome")),
        )
    )


def loopy_draft_loop_handler(args: dict[str, Any], **_kwargs: Any) -> str:
    payload = draft_loop(
        name=args.get("name"),
        outcome=_clean_text(args.get("outcome")),
        success=_clean_text(args.get("success")),
        trigger=args.get("trigger"),
        scope=args.get("scope"),
        allowed_actions=args.get("allowed_actions"),
        verification=args.get("verification"),
        stop=args.get("stop"),
        approval_boundary=args.get("approval_boundary"),
        schedule=args.get("schedule"),
        deliver=args.get("deliver"),
        enabled_toolsets=_string_list(args.get("enabled_toolsets")),
        include_blueprint=bool(args.get("include_blueprint", True)),
    )
    if not payload.get("success"):
        return tool_error(payload.get("error") or "could not draft loop")
    return tool_result(payload)


def _catalog_loops(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    loops = catalog.get("loops")
    return [item for item in loops if isinstance(item, dict)] if isinstance(loops, list) else []


def _loop_result(loop: dict[str, Any], *, score: float) -> dict[str, Any]:
    verification = _dict(loop.get("verification"))
    category = _dict(loop.get("category"))
    return {
        "number": loop.get("number"),
        "slug": loop.get("slug"),
        "title": loop.get("title"),
        "url": loop.get("url"),
        "category": category.get("label") or category.get("slug"),
        "description": loop.get("description"),
        "use_when": loop.get("useWhen"),
        "prompt": loop.get("prompt"),
        "verification": {
            "title": verification.get("title"),
            "detail": verification.get("detail"),
        },
        "keywords": _string_list(loop.get("keywords")),
        "modified": loop.get("modified"),
        "fit_score": round(score, 3),
        "adaptation_note": "Adapt tools, authority, schedule, and verification to the current Hermes profile before running.",
    }


def _score_loop(loop: dict[str, Any], *, query_tokens: set[str], raw_query: str) -> float:
    if not query_tokens:
        return 0.0
    title_tokens = _tokenize(_clean_text(loop.get("title")))
    keyword_tokens = _tokenize(" ".join(_string_list(loop.get("keywords"))))
    use_tokens = _tokenize(_clean_text(loop.get("useWhen")))
    body_tokens = _tokenize(
        " ".join(
            [
                _clean_text(loop.get("description")),
                _clean_text(loop.get("prompt")),
                _clean_text(_dict(loop.get("verification")).get("title")),
                _clean_text(_dict(loop.get("verification")).get("detail")),
                " ".join(str(step) for step in loop.get("steps") or []),
            ]
        )
    )
    score = 0.0
    score += 4.0 * len(query_tokens & title_tokens)
    score += 3.0 * len(query_tokens & keyword_tokens)
    score += 2.5 * len(query_tokens & use_tokens)
    score += 1.0 * len(query_tokens & body_tokens)
    haystack = " ".join(
        [
            _clean_text(loop.get("title")),
            _clean_text(loop.get("description")),
            _clean_text(loop.get("useWhen")),
            _clean_text(loop.get("prompt")),
        ]
    ).lower()
    if raw_query.lower() in haystack:
        score += 8.0
    return score / max(1.0, len(query_tokens))


def _validation_result(loop_text: str, findings: list[LoopValidationFinding]) -> dict[str, Any]:
    blocker_count = sum(1 for finding in findings if finding.severity == "blocker")
    warning_count = sum(1 for finding in findings if finding.severity == "warning")
    criteria = {
        "fresh_observation": not any(f.code == "missing_fresh_observation" for f in findings),
        "bounded_action": not any(f.code == "missing_bounded_action" for f in findings),
        "observable_verification": not any(f.code == "missing_verification" for f in findings),
        "recorded_receipt": not any(f.code == "missing_record" for f in findings),
        "explicit_stop": not any(f.code in {"missing_stop_rule", "unbounded_stop"} for f in findings),
        "approval_boundary": not any(
            f.code in {"missing_approval_boundary", "consequential_action_without_approval"} for f in findings
        ),
    }
    passed = sum(1 for ok in criteria.values() if ok)
    return {
        "success": True,
        "status": "ready" if blocker_count == 0 and passed >= 5 else "needs_repair",
        "readiness_score": round(passed / len(criteria), 2),
        "criteria": criteria,
        "finding_count": len(findings),
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "findings": [finding.to_dict() for finding in findings],
        "loop_preview": loop_text[:600],
        "authority_boundary": (
            "Validation is design-only. It does not run the loop, schedule it, publish it, or approve consequential actions."
        ),
    }


def _require_signal(
    findings: list[LoopValidationFinding],
    *,
    code: str,
    ok: bool,
    message: str,
    repair: str,
    severity: str = "blocker",
) -> None:
    if not ok:
        findings.append(LoopValidationFinding(severity, code, message, repair))


def _blueprint_skill_md(
    *,
    slug: str,
    name: str,
    description: str,
    prompt: str,
    schedule: str,
    deliver: str,
    enabled_toolsets: list[str],
) -> dict[str, Any]:
    yaml_prompt = _indent_block(prompt, "      ")
    toolset_block = ""
    if enabled_toolsets:
        toolset_block = "      enabled_toolsets:\n" + "".join(f"        - {_yaml_scalar(item)}\n" for item in enabled_toolsets)
    blueprint_ready = bool(schedule)
    schedule_line = f'      schedule: "{_escape_double_quoted(schedule)}"\n' if schedule else "      # schedule: \"0 9 * * *\"\n"
    skill_md = (
        "---\n"
        f"name: {slug}\n"
        f"description: {_yaml_scalar(description)}\n"
        "metadata:\n"
        "  hermes:\n"
        "    blueprint:\n"
        f"{schedule_line}"
        f"      deliver: {_yaml_scalar(deliver or 'origin')}\n"
        "      no_agent: false\n"
        f"{toolset_block}"
        "      prompt: |\n"
        f"{yaml_prompt}\n"
        "---\n\n"
        f"# {name}\n\n"
        f"{description}\n\n"
        "Use this skill as a Hermes blueprint only after reviewing the schedule, delivery target, tools, and approval boundary.\n"
    )
    return {
        "ready_for_blueprint_install": blueprint_ready,
        "skill_name": slug,
        "skill_md": skill_md,
        "review_required": True,
    }


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text.lower())
        if token
        not in {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "into",
            "your",
            "our",
            "when",
            "what",
            "how",
            "use",
            "loop",
            "agent",
        }
    }


def _bounded_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_RECOMMENDATION_LIMIT
    return min(10, max(1, parsed))


def _title_from_outcome(outcome: str) -> str:
    words = [word for word in re.split(r"\s+", outcome.strip()) if word]
    title = " ".join(words[:8]).strip(" .")
    if not title:
        return "Hermes Loop"
    return title[:1].upper() + title[1:]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "hermes-loop"


def _yaml_scalar(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_.:/@ -]+", text) and not text.startswith(("-", "{", "[", "#")):
        return text
    return '"' + _escape_double_quoted(text) + '"'


def _escape_double_quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _indent_block(text: str, indent: str) -> str:
    return "\n".join(indent + line for line in text.splitlines())


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


registry.register(
    name="loopy_catalog_search",
    toolset="loopy",
    schema={
        "name": "loopy_catalog_search",
        "description": (
            "Search the live Loop Library catalog for published loops that fit an outcome. "
            "This is recommendation/reference only; it does not run, schedule, publish, or approve a loop."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Outcome, workflow, risk, artifact, or loop need to search for."},
                "category": {
                    "type": "string",
                    "description": "Optional category slug or label, such as engineering, operations, evaluation, content, or design.",
                },
                "max_results": {"type": "integer", "description": "Maximum recommendations to return, 1-10. Default 3."},
                "timeout_seconds": {"type": "integer", "description": "Network timeout for catalog fetch. Default 10."},
            },
            "required": ["query"],
        },
    },
    handler=loopy_catalog_search_handler,
    description="Search the live Loop Library catalog",
    emoji="loop",
    max_result_size_chars=18_000,
)

registry.register(
    name="loopy_validate_loop",
    toolset="loopy",
    schema={
        "name": "loopy_validate_loop",
        "description": (
            "Audit a proposed loop prompt or definition for fresh observation, bounded action, "
            "verification, recording, stop behavior, and approval boundaries. Design-only; no execution."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "loop": {"type": "string", "description": "The loop prompt or definition to audit."},
                "intended_outcome": {"type": "string", "description": "Optional intended outcome for the loop."},
            },
            "required": ["loop"],
        },
    },
    handler=loopy_validate_loop_handler,
    description="Validate a loop design",
    emoji="loop",
    max_result_size_chars=14_000,
)

registry.register(
    name="loopy_draft_loop",
    toolset="loopy",
    schema={
        "name": "loopy_draft_loop",
        "description": (
            "Draft a bounded loop prompt and optional Hermes blueprint SKILL.md from concrete loop requirements. "
            "Returns a reviewable draft only; it does not install, schedule, publish, or run it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Optional loop name."},
                "outcome": {"type": "string", "description": "What the loop should accomplish."},
                "success": {"type": "string", "description": "Observable result that proves success."},
                "trigger": {"type": "string", "description": "When it should run, e.g. on request, after deploy, or weekly."},
                "scope": {"type": "string", "description": "What it may inspect or use as source evidence."},
                "allowed_actions": {"type": "string", "description": "What one bounded action per pass may do."},
                "verification": {"type": "string", "description": "Exact check or readback to run after each pass."},
                "stop": {"type": "string", "description": "When to stop or hand off."},
                "approval_boundary": {"type": "string", "description": "Actions that require explicit approval."},
                "schedule": {
                    "type": "string",
                    "description": "Optional cron expression. If supplied, returned blueprint draft is marked ready for review.",
                },
                "deliver": {"type": "string", "description": "Optional Hermes delivery target for blueprint draft. Default origin."},
                "enabled_toolsets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional Hermes toolsets to include in the blueprint metadata.",
                },
                "include_blueprint": {"type": "boolean", "description": "Whether to include a Hermes blueprint SKILL.md draft. Default true."},
            },
            "required": ["outcome", "success"],
        },
    },
    handler=loopy_draft_loop_handler,
    description="Draft a bounded Hermes loop",
    emoji="loop",
    max_result_size_chars=24_000,
)
