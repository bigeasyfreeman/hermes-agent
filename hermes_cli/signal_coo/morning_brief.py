"""Morning brief assembly for Torben's EA scope."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .action_ledger import parse_time

LOCAL_TZ = ZoneInfo("America/New_York")
BRIEF_RULES = [
    "Name actual times and actual meetings; never give generic advice.",
    "If a source is unavailable, flag it and keep going.",
    "Research instead of summarizing when the claim depends on outside context.",
    "If the brief does not know something, say so instead of guessing.",
]
GENERIC_ATTENDEE_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "icloud.com",
    "me.com",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
}


def _local(value: datetime) -> datetime:
    return value.astimezone(LOCAL_TZ)


def _format_window(start_at: str | None, end_at: str | None) -> str:
    start = parse_time(start_at)
    end = parse_time(end_at)
    if not start or not end:
        return "time unknown"
    start_local = _local(start)
    end_local = _local(end)
    if start_local.date() == end_local.date():
        return f"{start_local:%a %-m/%-d %-I:%M %p}-{end_local:%-I:%M %p}"
    return f"{start_local:%a %-m/%-d %-I:%M %p} to {end_local:%a %-m/%-d %-I:%M %p}"


def _events_for_today(events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    today = _local(now).date()
    todays_events: list[tuple[datetime, dict[str, Any]]] = []
    for event in events:
        start = parse_time(event.get("start_at"))
        if start and _local(start).date() == today:
            todays_events.append((start, event))
    todays_events.sort(key=lambda item: item[0])
    return [event for _, event in todays_events]


def _open_blocks(events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    local_now = _local(now)
    work_start = datetime.combine(local_now.date(), time(8, 0), tzinfo=LOCAL_TZ)
    work_end = datetime.combine(local_now.date(), time(18, 0), tzinfo=LOCAL_TZ)
    cursor = max(local_now, work_start)
    blocks: list[dict[str, Any]] = []
    for event in events:
        start = parse_time(event.get("start_at"))
        end = parse_time(event.get("end_at"))
        if not start or not end:
            continue
        start_local = _local(start)
        end_local = _local(end)
        if end_local <= cursor or start_local >= work_end:
            continue
        if start_local > cursor and (start_local - cursor) >= timedelta(minutes=30):
            blocks.append({"start_at": cursor.isoformat(), "end_at": start_local.isoformat()})
        cursor = max(cursor, end_local)
    if cursor < work_end and (work_end - cursor) >= timedelta(minutes=30):
        blocks.append({"start_at": cursor.isoformat(), "end_at": work_end.isoformat()})
    return blocks[:4]


def _clean_words(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _attendee_email(attendee: dict[str, Any]) -> str:
    return str(attendee.get("email") or "").strip().lower()


def _attendee_label(attendee: dict[str, Any]) -> str:
    email = _attendee_email(attendee)
    return _clean_words(attendee.get("display_name")) or email


def _event_attendees(event: dict[str, Any]) -> list[dict[str, Any]]:
    attendees = [item for item in (event.get("attendees") or []) if isinstance(item, dict)]
    account_email = str(event.get("account_email") or "").strip().lower()
    external: list[dict[str, Any]] = []
    for attendee in attendees:
        email = _attendee_email(attendee)
        if email and email == account_email:
            continue
        external.append(
            {
                "name": _attendee_label(attendee),
                "email": email,
                "domain": email.split("@", 1)[1] if "@" in email else "",
                "response_status": str(attendee.get("response_status") or ""),
                "organizer": bool(attendee.get("organizer")),
            }
        )
    return external[:8]


def _event_domains(attendees: list[dict[str, Any]]) -> list[str]:
    domains: list[str] = []
    for attendee in attendees:
        domain = str(attendee.get("domain") or "").strip().lower()
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def _relationship_context_matches(event: dict[str, Any], relationship_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not relationship_context:
        return []
    event_text = " ".join(
        [
            str(event.get("summary") or ""),
            str(event.get("title") or ""),
            str(event.get("description") or ""),
            " ".join(_attendee_label(item) for item in (event.get("attendees") or []) if isinstance(item, dict)),
            " ".join(_attendee_email(item) for item in (event.get("attendees") or []) if isinstance(item, dict)),
        ]
    ).lower()
    matches: list[dict[str, Any]] = []
    for person in relationship_context.get("people") or []:
        if not isinstance(person, dict):
            continue
        aliases = [person.get("name"), *(person.get("aliases") or []), *(person.get("emails") or [])]
        if not any(str(alias or "").strip().lower() and str(alias or "").strip().lower() in event_text for alias in aliases):
            continue
        matches.append(
            {
                "name": person.get("name"),
                "role": person.get("role"),
                "importance": person.get("importance") or "medium",
                "notes": person.get("notes"),
                "surface_when": list(person.get("surface_when") or []),
            }
        )
    return matches[:5]


def _company_context_hint(domains: list[str], relationship_context: dict[str, Any] | None) -> str:
    source_rules = (relationship_context or {}).get("source_rules") or {}
    hints: list[str] = []
    for domain in domains:
        if domain in GENERIC_ATTENDEE_DOMAINS:
            continue
        rule = source_rules.get(domain) if isinstance(source_rules, dict) else None
        if isinstance(rule, dict) and rule.get("description"):
            hints.append(f"{domain}: {rule.get('description')}")
        elif isinstance(rule, dict) and rule.get("reason"):
            hints.append(f"{domain}: {rule.get('reason')}")
        else:
            hints.append(f"{domain}: external attendee domain; company context not yet verified")
    return "; ".join(hints[:3])


def build_meeting_signal_packets(
    events: list[dict[str, Any]],
    *,
    relationship_context: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Package weak meeting evidence for LLM judgment without inventing agenda context."""

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    packets: list[dict[str, Any]] = []
    for event in _events_for_today(events, now)[:12]:
        attendees = _event_attendees(event)
        domains = _event_domains(attendees)
        relationship_matches = _relationship_context_matches(event, relationship_context)
        description = _clean_words(event.get("description"))
        goal = _clean_words(event.get("goal"))
        last_conversation = _clean_words(event.get("last_conversation"))
        recommended_line = _clean_words(event.get("recommended_line"))
        unknowns: list[str] = []
        if not description:
            unknowns.append("invite agenda")
        if not relationship_matches:
            unknowns.append("person/company context")
        if last_conversation.startswith("calendar context only"):
            unknowns.append("prior conversation summary")
        known_context: list[str] = []
        if goal and goal != "to protect the calendar commitment and arrive prepared":
            known_context.append(goal)
        if last_conversation and not last_conversation.startswith("calendar context only"):
            known_context.append(last_conversation)
        if description:
            known_context.append(description[:240])
        for match in relationship_matches:
            label = _clean_words(match.get("name"))
            role = _clean_words(match.get("role"))
            notes = _clean_words(match.get("notes"))
            if label and role:
                known_context.append(f"{label}: {role}")
            if notes:
                known_context.append(notes[:180])
        confidence = "high" if relationship_matches and known_context else "medium" if attendees or domains else "low"
        packets.append(
            {
                "summary": event.get("summary") or event.get("title") or "Busy",
                "time": _format_window(event.get("start_at"), event.get("end_at")),
                "attendees": attendees,
                "domains": domains,
                "known_context": known_context[:6],
                "company_context_hint": _company_context_hint(domains, relationship_context),
                "unknowns": unknowns[:5],
                "suggested_question": recommended_line
                or "What would make this worth continuing, and what would block it?",
                "confidence": confidence,
                "relationship_matches": relationship_matches,
                "evidence_ids": list(event.get("evidence_ids") or []),
            }
        )
    return packets


def build_morning_brief_scope(
    ea_evidence: dict[str, Any],
    *,
    now: datetime | None = None,
    north_star: str = "advance the highest-leverage founder work before the inbox takes over",
    relationship_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    events = list(ea_evidence.get("calendar_events") or [])
    todays_events = _events_for_today(events, now)
    block_candidates = list(ea_evidence.get("calendar_block_candidates") or [])
    reply_candidates = list(ea_evidence.get("email_reply_candidates") or [])
    open_blocks = _open_blocks(todays_events, now)

    decisions: list[dict[str, Any]] = []
    for candidate in block_candidates[:5]:
        decisions.append(
            {
                "kind": "calendar_alignment",
                "summary": (
                    f"{candidate.get('summary') or 'Busy time'} is on "
                    f"{candidate.get('source_account') or 'one calendar'} but missing blocks on "
                    f"{', '.join(candidate.get('target_accounts') or []) or 'other calendars'}."
                ),
                "cost_of_delay": "calendar conflict risk increases if the account receives a competing invite",
                "time": _format_window(candidate.get("start_at"), candidate.get("end_at")),
                "evidence_ids": list(candidate.get("evidence_ids") or []),
            }
        )
    for candidate in reply_candidates[:3]:
        decisions.append(
            {
                "kind": "email_reply",
                "summary": candidate.get("context_line") or f"Reply candidate from {candidate.get('sender') or 'sender'}.",
                "cost_of_delay": "thread stays open and may require a colder restart later",
                "draft_detail": candidate.get("staged_response_detail"),
                "evidence_ids": list(candidate.get("evidence_ids") or []),
            }
        )

    meetings: list[dict[str, Any]] = []
    meeting_signal_packets = build_meeting_signal_packets(
        todays_events,
        relationship_context=relationship_context,
        now=now,
    )
    for event in todays_events[:12]:
        meetings.append(
            {
                "summary": event.get("summary") or "Busy",
                "time": _format_window(event.get("start_at"), event.get("end_at")),
                "why_it_exists": event.get("goal") or "calendar context only; agenda not captured",
                "desired_outcome": event.get("goal") or "make the meeting produce a decision or next step",
                "one_question": event.get("recommended_line") or "What decision or blocker needs to be resolved before we end?",
                "unknowns": ["invite agenda"] if str(event.get("last_conversation") or "").startswith("calendar context only") else [],
                "evidence_ids": list(event.get("evidence_ids") or []),
            }
        )

    if block_candidates:
        top = block_candidates[0]
        move = {
            "summary": (
                f"Align calendars for {top.get('summary') or 'busy time'} "
                f"before anything else lands on {', '.join(top.get('target_accounts') or [])}."
            ),
            "draft_message": "Approve the calendar block action and I will create busy holds only for the missing target calendars.",
            "evidence_ids": list(top.get("evidence_ids") or []),
        }
    elif open_blocks:
        first_block = open_blocks[0]
        move = {
            "summary": f"Protect the open block {_format_window(first_block.get('start_at'), first_block.get('end_at'))}.",
            "draft_message": "I would hold this block for founder work before opening the inbox.",
            "evidence_ids": [],
        }
    else:
        move = {
            "summary": "No clean 30-minute work block is visible today.",
            "draft_message": "I would shorten or move the lowest-value meeting before checking email.",
            "evidence_ids": [],
        }

    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "north_star": north_star,
        "rules": BRIEF_RULES,
        "day": {
            "summary": f"{len(todays_events)} event(s) today; {len(open_blocks)} open work block(s) of at least 30 minutes.",
            "events": [
                {
                    "summary": event.get("summary") or "Busy",
                    "time": _format_window(event.get("start_at"), event.get("end_at")),
                    "account": event.get("account_alias"),
                    "calendar": event.get("calendar_summary"),
                    "evidence_ids": list(event.get("evidence_ids") or []),
                }
                for event in todays_events[:12]
            ],
            "open_blocks": open_blocks,
        },
        "decisions": decisions,
        "people": {
            "summary": "People radar is not fully connected yet; 1:1 notes, chat, and commitment history are required before calling a person.",
            "status": "needs_connectors",
            "specific_90_second_move": "Use today's external meeting prep first; do not invent a people-risk signal.",
        },
        "meetings": meetings,
        "meeting_signal_packets": meeting_signal_packets,
        "world": {
            "summary": "World scan is delegated to GTM/Magnus research; no live research source is attached to this EA-only evidence run.",
            "status": "placeholder",
        },
        "move": move,
    }


def render_morning_brief_text(morning: dict[str, Any]) -> str:
    day = morning.get("day") or {}
    people = morning.get("people") or {}
    world = morning.get("world") or {}
    move = morning.get("move") or {}
    decisions = list(morning.get("decisions") or [])
    meetings = list(morning.get("meetings") or [])

    lines = [
        "Morning Brief",
        f"Day: {day.get('summary') or 'No day summary available.'}",
        f"Decisions: {len(decisions)} item(s) blocked on you or worth staging early.",
        f"People: {people.get('summary') or 'No people signal available.'}",
        f"Meetings: {len(meetings)} meeting(s) prepared with purpose/outcome/question lines.",
        f"World: {world.get('summary') or 'No world scan available.'}",
        f"Move: {move.get('summary') or 'No move selected.'}",
    ]
    if move.get("draft_message"):
        lines.append(f"Draft: {move['draft_message']}")
    if decisions:
        lines.append("Top decisions:")
        for decision in decisions[:3]:
            lines.append(f"- {decision.get('summary')} ({decision.get('time') or decision.get('cost_of_delay')})")
    if meetings:
        lines.append("Meeting prep:")
        for meeting in meetings[:4]:
            lines.append(f"- {meeting.get('time')}: {meeting.get('summary')} - ask: {meeting.get('one_question')}")
    return "\n".join(lines).strip() + "\n"
