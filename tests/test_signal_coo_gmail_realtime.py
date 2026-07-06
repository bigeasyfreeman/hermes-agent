from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
import yaml

from hermes_cli.signal_coo.google_auth import GoogleAccount
from hermes_cli.signal_coo import gmail_realtime


def _encoded_notification(email: str = "eric@example.com", history_id: str = "200") -> str:
    payload = json.dumps({"emailAddress": email, "historyId": history_id}).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _account(tmp_path: Path, *, alias: str = "personal", email: str = "eric@example.com") -> GoogleAccount:
    return GoogleAccount(
        alias=alias,
        email=email,
        role="personal",
        enabled=True,
        token_path=tmp_path / f"{alias}-token.json",
        client_secret_path=tmp_path / "client.json",
        scopes=("https://www.googleapis.com/auth/gmail.modify",),
    )


def _http_error(code: int, reason: str = "HTTP error") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://gmail.googleapis.com/gmail/v1/users/me/history",
        code,
        reason,
        {},
        BytesIO(b"{}"),
    )


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _service_account_info() -> dict[str, Any]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return {
        "type": "service_account",
        "client_email": "torben-pubsub@example.iam.gserviceaccount.com",
        "private_key": private_key,
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def _decode_jwt_payload(assertion: str) -> dict[str, Any]:
    payload = assertion.split(".")[1]
    padded = payload + ("=" * ((4 - len(payload) % 4) % 4))
    decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    return decoded if isinstance(decoded, dict) else {}


def _clear_pubsub_env(monkeypatch) -> None:
    monkeypatch.setattr(gmail_realtime, "_PUBSUB_TOKEN_CACHE", None)
    for env_name in (
        "TORBEN_GCP_SERVICE_ACCOUNT_JSON",
        "TORBEN_GCP_SERVICE_ACCOUNT_FILE",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        monkeypatch.delenv(env_name, raising=False)


def test_decode_pubsub_data_handles_urlsafe_padding() -> None:
    assert gmail_realtime.decode_pubsub_data(_encoded_notification()) == {
        "emailAddress": "eric@example.com",
        "historyId": "200",
    }


def test_history_message_ids_includes_inbox_label_added() -> None:
    assert gmail_realtime._history_message_ids(
        [
            {"messages": [{"id": "m-fallback", "threadId": "t1"}]},
            {"labelsAdded": [{"message": {"id": "m-label"}, "labelIds": ["INBOX"]}]},
            {"labelsAdded": [{"message": {"id": "m-skip"}, "labelIds": ["CATEGORY_PROMOTIONS"]}]},
            {"messagesAdded": [{"message": {"id": "m-message", "labelIds": ["INBOX"]}}]},
        ]
    ) == ["m-fallback", "m-label", "m-message"]


def test_list_history_retries_429_and_succeeds(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_get(url: str, token: str) -> dict[str, Any]:
        calls.append(url)
        if len(calls) == 1:
            raise _http_error(429, "Too Many Requests")
        return {"history": [{"id": "150", "messages": [{"id": "m1"}]}]}

    monkeypatch.setattr(gmail_realtime, "_google_get", fake_get)

    history, read_calls, warnings = gmail_realtime._list_history(
        account=account,
        token="access-token",
        start_history_id="100",
        max_pages=1,
        rate_limit_retries=2,
        rate_limit_backoff_seconds=0.25,
        rate_limit_max_sleep_seconds=5.0,
        rate_limit_jitter_seconds=0.0,
        sleep=sleeps.append,
    )

    assert history == [{"id": "150", "messages": [{"id": "m1"}]}]
    assert read_calls == 2
    assert warnings == []
    assert len(calls) == 2
    assert sleeps == [0.25]


def test_list_history_exhausts_bounded_429_retries(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_get(url: str, token: str) -> dict[str, Any]:
        calls.append(url)
        raise _http_error(429, "Too Many Requests")

    monkeypatch.setattr(gmail_realtime, "_google_get", fake_get)

    with pytest.raises(gmail_realtime.GmailHistoryRateLimitError) as raised:
        gmail_realtime._list_history(
            account=account,
            token="access-token",
            start_history_id="100",
            max_pages=1,
            rate_limit_retries=2,
            rate_limit_backoff_seconds=0.1,
            rate_limit_max_sleep_seconds=1.0,
            rate_limit_jitter_seconds=0.0,
            sleep=sleeps.append,
        )

    assert len(calls) == 3
    assert sleeps == [0.1, 0.2]
    assert raised.value.account_alias == "personal"
    assert raised.value.start_history_id == "100"
    assert raised.value.attempts == 3
    assert raised.value.retry_count == 2
    assert raised.value.read_calls == 3


def test_list_history_cursor_expired_404_still_returns_warning(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)

    def fake_get(url: str, token: str) -> dict[str, Any]:
        raise _http_error(404, "Not Found")

    monkeypatch.setattr(gmail_realtime, "_google_get", fake_get)

    history, read_calls, warnings = gmail_realtime._list_history(
        account=account,
        token="access-token",
        start_history_id="100",
        max_pages=1,
        rate_limit_retries=2,
        rate_limit_backoff_seconds=0.0,
        rate_limit_jitter_seconds=0.0,
    )

    assert history == []
    assert read_calls == 1
    assert warnings == ["personal: Gmail history cursor expired; watch cursor reset to latest notification"]


def test_pubsub_pull_and_ack_use_service_account_rest(monkeypatch) -> None:
    _clear_pubsub_env(monkeypatch)
    monkeypatch.setenv("TORBEN_GCP_SERVICE_ACCOUNT_JSON", json.dumps(_service_account_info()))
    calls: list[str] = []

    def fake_urlopen(request, timeout=30):
        calls.append(request.full_url)
        if request.full_url == "https://oauth2.googleapis.com/token":
            parsed = urllib.parse.parse_qs(request.data.decode("utf-8"))
            assert parsed["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
            assertion = parsed["assertion"][0]
            assert assertion.count(".") == 2
            claims = _decode_jwt_payload(assertion)
            assert claims["iss"] == "torben-pubsub@example.iam.gserviceaccount.com"
            assert claims["scope"] == gmail_realtime.PUBSUB_SCOPE
            assert claims["aud"] == "https://oauth2.googleapis.com/token"
            return _FakeHTTPResponse({"access_token": "pubsub-token", "expires_in": 3600})
        if request.full_url == "https://pubsub.googleapis.com/v1/projects/test/subscriptions/torben:pull":
            assert request.get_header("Authorization") == "Bearer pubsub-token"
            assert json.loads(request.data.decode("utf-8")) == {"maxMessages": 5}
            return _FakeHTTPResponse(
                {
                    "receivedMessages": [
                        {
                            "ackId": "ack-1",
                            "message": {"data": _encoded_notification()},
                        }
                    ]
                }
            )
        if request.full_url == "https://pubsub.googleapis.com/v1/projects/test/subscriptions/torben:acknowledge":
            assert request.get_header("Authorization") == "Bearer pubsub-token"
            assert json.loads(request.data.decode("utf-8")) == {"ackIds": ["ack-1", "ack-2"]}
            return _FakeHTTPResponse({})
        raise AssertionError(f"unexpected URL: {request.full_url}")

    monkeypatch.setattr(gmail_realtime.urllib.request, "urlopen", fake_urlopen)

    received = gmail_realtime.pull_pubsub_messages(
        subscription_name="projects/test/subscriptions/torben",
        limit=5,
    )
    gmail_realtime.ack_pubsub_messages(
        subscription_name="projects/test/subscriptions/torben",
        ack_ids=["ack-1", "ack-2"],
    )

    assert received[0]["ackId"] == "ack-1"
    assert calls == [
        "https://oauth2.googleapis.com/token",
        "https://pubsub.googleapis.com/v1/projects/test/subscriptions/torben:pull",
        "https://pubsub.googleapis.com/v1/projects/test/subscriptions/torben:acknowledge",
    ]


def test_pubsub_pull_requires_service_account_credentials(monkeypatch) -> None:
    _clear_pubsub_env(monkeypatch)

    with pytest.raises(RuntimeError, match="service-account credentials"):
        gmail_realtime.pull_pubsub_messages(
            subscription_name="projects/test/subscriptions/torben",
            limit=1,
        )


def test_pubsub_credentials_survive_cron_subprocess_env_sanitizer() -> None:
    from tools.environments.local import _sanitize_subprocess_env

    sanitized = _sanitize_subprocess_env(
        {
            "TORBEN_GCP_SERVICE_ACCOUNT_FILE": "/secure/torben-pubsub.json",
            "GOOGLE_APPLICATION_CREDENTIALS": "/secure/adc.json",
        }
    )

    assert sanitized["TORBEN_GCP_SERVICE_ACCOUNT_FILE"] == "/secure/torben-pubsub.json"
    assert sanitized["GOOGLE_APPLICATION_CREDENTIALS"] == "/secure/adc.json"


def test_process_pubsub_pull_uses_history_messages_fallback_and_filters_sent(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)
    state_path = tmp_path / "watch-state.json"
    gmail_realtime.write_json(
        state_path,
        {
            "version": 1,
            "accounts": {"personal": {"email": "eric@example.com", "history_id": "100"}},
            "processed_message_keys": [],
        },
    )
    received = [
        {
            "ackId": "ack-1",
            "message": {
                "messageId": "pubsub-1",
                "publishTime": "2026-06-25T10:00:00Z",
                "data": _encoded_notification(history_id="200"),
            },
        }
    ]
    inbox_record = {
        "account_alias": "personal",
        "message_id": "m-inbox",
        "thread_id": "t1",
        "sender": "Max Shapiro",
        "sender_email": "max@example.com",
        "sender_domain": "example.com",
        "subject": "Re: Max <> Eric",
        "date": "Thu, 25 Jun 2026 10:00:00 +0000",
        "category": "calendar_scheduling",
        "juno_bucket": "reply",
        "priority": "high",
        "snippet": "Can you send availability?",
        "body_excerpt": "",
        "labels": ["IMPORTANT", "INBOX"],
        "links": [],
        "evidence_ids": ["gmail:personal:m-inbox"],
    }
    sent_record = {
        **inbox_record,
        "message_id": "m-sent",
        "sender": "eric@example.com",
        "labels": ["SENT"],
        "evidence_ids": ["gmail:personal:m-sent"],
    }
    acked: list[str] = []

    monkeypatch.setattr(gmail_realtime, "_enabled_gmail_accounts", lambda config_path: [account])
    monkeypatch.setattr(gmail_realtime, "pull_pubsub_messages", lambda **kwargs: received)
    monkeypatch.setattr(gmail_realtime, "_read_token", lambda account: "access-token")
    monkeypatch.setattr(
        gmail_realtime,
        "_list_history",
        lambda **kwargs: ([{"messages": [{"id": "m-sent"}, {"id": "m-inbox"}]}], 1, []),
    )

    def fake_metadata(account, token, message_id):
        return (sent_record if message_id == "m-sent" else inbox_record), 1

    monkeypatch.setattr(gmail_realtime, "_gmail_message_metadata", fake_metadata)
    monkeypatch.setattr(gmail_realtime, "load_relationship_context", lambda path: {"people": [], "source_rules": {}, "principles": []})
    monkeypatch.setattr(
        gmail_realtime,
        "build_morning_briefing_candidates",
        lambda records, relationship_context=None: {"critical_emails": [], "learn_contact_candidates": [], "llm_decision_contract": {}},
    )
    monkeypatch.setattr(gmail_realtime, "ack_pubsub_messages", lambda subscription_name, ack_ids: acked.extend(ack_ids))

    result = gmail_realtime.process_pubsub_pull(
        config_path=tmp_path / "config.yaml",
        relationship_context_path=tmp_path / "relationship.yaml",
        state_path=state_path,
        subscription_name="projects/test/subscriptions/torben",
    )

    assert result["wakeAgent"] is True
    assert [candidate["message_key"] for candidate in result["candidates"]] == ["personal:m-inbox"]
    assert acked == ["ack-1"]


def test_process_pubsub_pull_exhausted_429_writes_degraded_health_and_preserves_cursor(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)
    state_path = tmp_path / "watch-state.json"
    gmail_realtime.write_json(
        state_path,
        {
            "version": 1,
            "accounts": {"personal": {"email": "eric@example.com", "history_id": "100"}},
            "processed_message_keys": [],
        },
    )
    received = [
        {
            "ackId": "ack-1",
            "message": {
                "messageId": "pubsub-1",
                "publishTime": "2026-06-25T10:00:00Z",
                "data": _encoded_notification(history_id="200"),
            },
        }
    ]
    acked: list[str] = []

    monkeypatch.setattr(gmail_realtime, "_enabled_gmail_accounts", lambda config_path: [account])
    monkeypatch.setattr(gmail_realtime, "pull_pubsub_messages", lambda **kwargs: received)
    monkeypatch.setattr(gmail_realtime, "_read_token", lambda account: "access-token")
    monkeypatch.setattr(gmail_realtime, "_google_get", lambda url, token: (_ for _ in ()).throw(_http_error(429, "Too Many Requests")))
    monkeypatch.setattr(gmail_realtime, "load_relationship_context", lambda path: {"people": [], "source_rules": {}, "principles": []})
    monkeypatch.setattr(
        gmail_realtime,
        "build_morning_briefing_candidates",
        lambda records, relationship_context=None: {"critical_emails": [], "learn_contact_candidates": [], "llm_decision_contract": {}},
    )
    monkeypatch.setattr(gmail_realtime, "ack_pubsub_messages", lambda subscription_name, ack_ids: acked.extend(ack_ids))

    result = gmail_realtime.process_pubsub_pull(
        config_path=tmp_path / "config.yaml",
        relationship_context_path=tmp_path / "relationship.yaml",
        state_path=state_path,
        subscription_name="projects/test/subscriptions/torben",
        history_rate_limit_retries=1,
        history_rate_limit_backoff_seconds=0.0,
        history_rate_limit_jitter_seconds=0.0,
        history_rate_limit_cooldown_seconds=600,
    )

    assert result["wakeAgent"] is False
    assert result["reason"] == "pubsub notifications processed with no realtime candidates"
    assert acked == []
    assert result["diagnostics"]["warnings"] == [
        "personal: Gmail history rate limited after 2 read attempt(s); cursor preserved and notification left unacked"
    ]
    health = result["diagnostics"]["pipeline_health"]
    assert health["status"] == "degraded"
    assert health["pubsub_messages_received"] == 1
    assert health["pubsub_messages_acked"] == 0
    assert health["degradations"][0]["reason"] == "rate_limited"
    assert health["degradations"][0]["cursor_preserved"] is True
    assert health["degradations"][0]["notification_left_unacked"] is True
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["accounts"]["personal"]["history_id"] == "100"
    assert state["accounts"]["personal"]["history_rate_limit_cooldown_until"]
    assert state["accounts"]["personal"]["history_rate_limit_notification_history_id"] == "200"
    assert state["last_pubsub_pull_status"] == "degraded_rate_limited"
    assert state["last_pubsub_pipeline_health"]["status"] == "degraded"
    assert state["last_pubsub_message_ids_by_account"] == {}


def test_process_pubsub_pull_defers_history_reads_during_rate_limit_cooldown(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)
    state_path = tmp_path / "watch-state.json"
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    gmail_realtime.write_json(
        state_path,
        {
            "version": 1,
            "accounts": {"personal": {"email": "eric@example.com", "history_id": "100"}},
            "processed_message_keys": [],
            "last_pubsub_pipeline_health": {
                "status": "degraded",
                "generated_at": generated_at,
                "degradations": [
                    {
                        "reason": "rate_limited",
                        "account": {"alias": "personal", "email": "eric@example.com"},
                    }
                ],
            },
        },
    )
    received = [
        {
            "ackId": "ack-1",
            "message": {
                "messageId": "pubsub-1",
                "publishTime": "2026-06-25T10:00:00Z",
                "data": _encoded_notification(history_id="200"),
            },
        }
    ]
    acked: list[str] = []

    monkeypatch.setattr(gmail_realtime, "_enabled_gmail_accounts", lambda config_path: [account])
    monkeypatch.setattr(gmail_realtime, "pull_pubsub_messages", lambda **kwargs: received)
    monkeypatch.setattr(gmail_realtime, "_read_token", lambda account: (_ for _ in ()).throw(AssertionError("cooldown should skip Gmail reads")))
    monkeypatch.setattr(gmail_realtime, "load_relationship_context", lambda path: {"people": [], "source_rules": {}, "principles": []})
    monkeypatch.setattr(
        gmail_realtime,
        "build_morning_briefing_candidates",
        lambda records, relationship_context=None: {"critical_emails": [], "learn_contact_candidates": [], "llm_decision_contract": {}},
    )
    monkeypatch.setattr(gmail_realtime, "ack_pubsub_messages", lambda subscription_name, ack_ids: acked.extend(ack_ids))

    result = gmail_realtime.process_pubsub_pull(
        config_path=tmp_path / "config.yaml",
        relationship_context_path=tmp_path / "relationship.yaml",
        state_path=state_path,
        subscription_name="projects/test/subscriptions/torben",
        history_rate_limit_cooldown_seconds=600,
    )

    assert result["wakeAgent"] is False
    assert result["reason"] == "pubsub notifications processed with no realtime candidates"
    assert acked == []
    assert result["diagnostics"]["gmail_reads"] == 0
    assert result["diagnostics"]["pubsub_messages_acked"] == 0
    assert result["diagnostics"]["pipeline_health"]["status"] == "degraded"
    assert result["diagnostics"]["pipeline_health"]["degradations"][0]["reason"] == "rate_limit_cooldown"
    assert "retry deferred until" in result["diagnostics"]["warnings"][0]


def test_process_pubsub_pull_acks_stale_notification_without_history_read(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)
    state_path = tmp_path / "watch-state.json"
    gmail_realtime.write_json(
        state_path,
        {
            "version": 1,
            "accounts": {"personal": {"email": "eric@example.com", "history_id": "300"}},
            "processed_message_keys": [],
        },
    )
    received = [
        {
            "ackId": "ack-stale",
            "message": {
                "messageId": "pubsub-stale",
                "publishTime": "2026-06-25T10:00:00Z",
                "data": _encoded_notification(history_id="200"),
            },
        }
    ]
    acked: list[str] = []

    monkeypatch.setattr(gmail_realtime, "_enabled_gmail_accounts", lambda config_path: [account])
    monkeypatch.setattr(gmail_realtime, "pull_pubsub_messages", lambda **kwargs: received)
    monkeypatch.setattr(gmail_realtime, "_read_token", lambda account: (_ for _ in ()).throw(AssertionError("no Gmail token needed")))
    monkeypatch.setattr(gmail_realtime, "load_relationship_context", lambda path: {"people": [], "source_rules": {}, "principles": []})
    monkeypatch.setattr(
        gmail_realtime,
        "build_morning_briefing_candidates",
        lambda records, relationship_context=None: {"critical_emails": [], "learn_contact_candidates": [], "llm_decision_contract": {}},
    )
    monkeypatch.setattr(gmail_realtime, "ack_pubsub_messages", lambda subscription_name, ack_ids: acked.extend(ack_ids))

    result = gmail_realtime.process_pubsub_pull(
        config_path=tmp_path / "config.yaml",
        relationship_context_path=tmp_path / "relationship.yaml",
        state_path=state_path,
        subscription_name="projects/test/subscriptions/torben",
    )

    assert result["wakeAgent"] is False
    assert acked == ["ack-stale"]
    assert result["diagnostics"]["gmail_reads"] == 0
    assert result["diagnostics"]["pubsub_messages_acked"] == 1
    assert result["diagnostics"]["warnings"] == [
        "personal: Pub/Sub history notification 200 is at or before stored cursor 300; acked without Gmail history read"
    ]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["accounts"]["personal"]["history_id"] == "300"
    assert state["accounts"]["personal"]["last_stale_notification_history_id"] == "200"


def test_process_pubsub_pull_does_not_regress_cursor_to_older_notification(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)
    state_path = tmp_path / "watch-state.json"
    gmail_realtime.write_json(
        state_path,
        {
            "version": 1,
            "accounts": {"personal": {"email": "eric@example.com", "history_id": "100"}},
            "processed_message_keys": [],
        },
    )
    received = [
        {
            "ackId": "ack-1",
            "message": {
                "messageId": "pubsub-1",
                "publishTime": "2026-06-25T10:00:00Z",
                "data": _encoded_notification(history_id="200"),
            },
        }
    ]
    acked: list[str] = []

    monkeypatch.setattr(gmail_realtime, "_enabled_gmail_accounts", lambda config_path: [account])
    monkeypatch.setattr(gmail_realtime, "pull_pubsub_messages", lambda **kwargs: received)
    monkeypatch.setattr(gmail_realtime, "_read_token", lambda account: "access-token")
    monkeypatch.setattr(
        gmail_realtime,
        "_list_history",
        lambda **kwargs: ([{"id": "250", "messages": []}], 1, []),
    )
    monkeypatch.setattr(gmail_realtime, "load_relationship_context", lambda path: {"people": [], "source_rules": {}, "principles": []})
    monkeypatch.setattr(
        gmail_realtime,
        "build_morning_briefing_candidates",
        lambda records, relationship_context=None: {"critical_emails": [], "learn_contact_candidates": [], "llm_decision_contract": {}},
    )
    monkeypatch.setattr(gmail_realtime, "ack_pubsub_messages", lambda subscription_name, ack_ids: acked.extend(ack_ids))

    result = gmail_realtime.process_pubsub_pull(
        config_path=tmp_path / "config.yaml",
        relationship_context_path=tmp_path / "relationship.yaml",
        state_path=state_path,
        subscription_name="projects/test/subscriptions/torben",
    )

    assert result["wakeAgent"] is False
    assert acked == ["ack-1"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["accounts"]["personal"]["history_id"] == "250"


def test_register_gmail_watches_writes_cursor_without_mailbox_mutation(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "google_accounts.yaml"
    token_path = tmp_path / "token.json"
    client_path = tmp_path / "client.json"
    token_path.write_text("{}", encoding="utf-8")
    client_path.write_text("{}", encoding="utf-8")
    config_path.write_text(
        yaml.safe_dump(
            {
                "accounts": {
                    "personal": {
                        "email": "eric@example.com",
                        "role": "personal",
                        "enabled": True,
                        "token_path": str(token_path),
                        "client_secret_path": str(client_path),
                        "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    posted: dict[str, Any] = {}

    monkeypatch.setattr(gmail_realtime, "_read_token", lambda account: "access-token")

    def fake_post(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        posted.update({"url": url, "token": token, "payload": payload})
        return {"historyId": "12345", "expiration": "1790000000000"}

    monkeypatch.setattr(gmail_realtime, "_google_post", fake_post)

    state_path = tmp_path / "watch-state.json"
    result = gmail_realtime.register_gmail_watches(
        config_path=config_path,
        state_path=state_path,
        topic_name="projects/test/topics/torben-gmail-watch",
    )

    assert result["wakeAgent"] is False
    assert result["status"] == "pass"
    assert result["diagnostics"]["gmail_mailbox_mutations"] == 0
    assert posted["payload"] == {
        "topicName": "projects/test/topics/torben-gmail-watch",
        "labelIds": ["INBOX"],
        "labelFilterBehavior": "INCLUDE",
    }
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["accounts"]["personal"]["history_id"] == "12345"


def test_process_pubsub_pull_no_messages_is_silent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(gmail_realtime, "pull_pubsub_messages", lambda **kwargs: [])

    result = gmail_realtime.process_pubsub_pull(
        config_path=tmp_path / "missing.yaml",
        relationship_context_path=tmp_path / "relationship.yaml",
        state_path=tmp_path / "watch-state.json",
        subscription_name="projects/test/subscriptions/torben",
    )

    assert result["wakeAgent"] is False
    assert result["reason"] == "no pubsub notifications"
    assert result["diagnostics"]["external_mutations"] == 0


def test_process_pubsub_pull_no_messages_runs_history_fallback(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)
    state_path = tmp_path / "watch-state.json"
    gmail_realtime.write_json(
        state_path,
        {
            "version": 1,
            "accounts": {"personal": {"email": "eric@example.com", "history_id": "100"}},
            "processed_message_keys": [],
        },
    )
    record = {
        "account_alias": "personal",
        "message_id": "m-inbox",
        "thread_id": "t1",
        "sender": "Max Shapiro",
        "sender_email": "max@example.com",
        "sender_domain": "example.com",
        "subject": "Re: Max <> Eric",
        "date": "Thu, 25 Jun 2026 10:00:00 +0000",
        "category": "calendar_scheduling",
        "juno_bucket": "reply",
        "priority": "high",
        "snippet": "Can you send availability?",
        "body_excerpt": "",
        "labels": ["IMPORTANT", "INBOX"],
        "links": [],
        "evidence_ids": ["gmail:personal:m-inbox"],
    }

    monkeypatch.setattr(gmail_realtime, "_enabled_gmail_accounts", lambda config_path: [account])
    monkeypatch.setattr(gmail_realtime, "pull_pubsub_messages", lambda **kwargs: [])
    monkeypatch.setattr(gmail_realtime, "_read_token", lambda account: "access-token")
    monkeypatch.setattr(
        gmail_realtime,
        "_list_history",
        lambda **kwargs: ([{"id": "150", "messages": [{"id": "m-inbox"}]}], 1, []),
    )
    monkeypatch.setattr(gmail_realtime, "_gmail_message_metadata", lambda account, token, message_id: (record, 1))
    monkeypatch.setattr(gmail_realtime, "load_relationship_context", lambda path: {"people": [], "source_rules": {}, "principles": []})
    monkeypatch.setattr(
        gmail_realtime,
        "build_morning_briefing_candidates",
        lambda records, relationship_context=None: {"critical_emails": [], "learn_contact_candidates": [], "llm_decision_contract": {}},
    )

    result = gmail_realtime.process_pubsub_pull(
        config_path=tmp_path / "config.yaml",
        relationship_context_path=tmp_path / "relationship.yaml",
        state_path=state_path,
        subscription_name="projects/test/subscriptions/torben",
    )

    assert result["wakeAgent"] is True
    assert result["diagnostics"]["history_fallback"] is True
    assert result["candidates"][0]["message_key"] == "personal:m-inbox"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["accounts"]["personal"]["history_id"] == "150"


def test_process_pubsub_pull_no_messages_defers_history_fallback_during_rate_limit_cooldown(
    tmp_path, monkeypatch
) -> None:
    account = _account(tmp_path)
    state_path = tmp_path / "watch-state.json"
    cooldown_until = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    gmail_realtime.write_json(
        state_path,
        {
            "version": 1,
            "accounts": {
                "personal": {
                    "email": "eric@example.com",
                    "history_id": "100",
                    "history_rate_limit_cooldown_until": cooldown_until,
                }
            },
            "processed_message_keys": [],
            "last_history_fallback_at": "2026-06-25T10:00:00Z",
        },
    )

    monkeypatch.setattr(gmail_realtime, "_enabled_gmail_accounts", lambda config_path: [account])
    monkeypatch.setattr(gmail_realtime, "pull_pubsub_messages", lambda **kwargs: [])
    monkeypatch.setattr(
        gmail_realtime,
        "_read_token",
        lambda account: (_ for _ in ()).throw(AssertionError("cooldown should skip Gmail reads")),
    )
    monkeypatch.setattr(gmail_realtime, "load_relationship_context", lambda path: {"people": [], "source_rules": {}, "principles": []})
    monkeypatch.setattr(
        gmail_realtime,
        "build_morning_briefing_candidates",
        lambda records, relationship_context=None: {"critical_emails": [], "learn_contact_candidates": [], "llm_decision_contract": {}},
    )

    result = gmail_realtime.process_pubsub_pull(
        config_path=tmp_path / "config.yaml",
        relationship_context_path=tmp_path / "relationship.yaml",
        state_path=state_path,
        subscription_name="projects/test/subscriptions/torben",
    )

    assert result["wakeAgent"] is False
    assert result["reason"] == "Gmail history fallback processed with no realtime candidates"
    assert result["diagnostics"]["history_fallback"] is True
    assert result["diagnostics"]["gmail_reads"] == 0
    health = result["diagnostics"]["pipeline_health"]
    assert health["status"] == "degraded"
    assert health["degradations"][0]["reason"] == "rate_limit_cooldown"
    assert health["degradations"][0]["history_fallback"] is True
    assert health["degradations"][0]["notification_left_unacked"] is False


def test_process_pubsub_pull_fetches_history_stages_candidate_and_acks(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)
    state_path = tmp_path / "watch-state.json"
    gmail_realtime.write_json(
        state_path,
        {
            "version": 1,
            "accounts": {"personal": {"email": "eric@example.com", "history_id": "100"}},
            "processed_message_keys": [],
        },
    )
    received = [
        {
            "ackId": "ack-1",
            "message": {
                "messageId": "pubsub-1",
                "publishTime": "2026-06-25T10:00:00Z",
                "data": _encoded_notification(history_id="200"),
            },
        }
    ]
    record = {
        "account_alias": "personal",
        "message_id": "m1",
        "thread_id": "t1",
        "sender": "Kim Moore",
        "sender_email": "kim@example.com",
        "sender_domain": "example.com",
        "subject": "Follow up on funding",
        "date": "Thu, 25 Jun 2026 10:00:00 +0000",
        "category": "founder_funding_customer",
        "juno_bucket": "reply",
        "priority": "high",
        "snippet": "Can you send availability for a follow-up?",
        "body_excerpt": "",
        "labels": ["INBOX"],
        "links": [],
        "evidence_ids": ["gmail:personal:m1"],
    }
    acked: list[str] = []

    monkeypatch.setattr(gmail_realtime, "_enabled_gmail_accounts", lambda config_path: [account])
    monkeypatch.setattr(gmail_realtime, "pull_pubsub_messages", lambda **kwargs: received)
    monkeypatch.setattr(gmail_realtime, "_read_token", lambda account: "access-token")
    monkeypatch.setattr(
        gmail_realtime,
        "_list_history",
        lambda **kwargs: ([{"messagesAdded": [{"message": {"id": "m1", "labelIds": ["INBOX"]}}]}], 1, []),
    )
    monkeypatch.setattr(gmail_realtime, "_fetch_records", lambda **kwargs: ([record], 1, []))
    monkeypatch.setattr(gmail_realtime, "load_relationship_context", lambda path: {"people": [], "source_rules": {}, "principles": []})
    monkeypatch.setattr(
        gmail_realtime,
        "build_morning_briefing_candidates",
        lambda records, relationship_context=None: {"critical_emails": [], "learn_contact_candidates": [], "llm_decision_contract": {}},
    )
    monkeypatch.setattr(gmail_realtime, "ack_pubsub_messages", lambda subscription_name, ack_ids: acked.extend(ack_ids))

    result = gmail_realtime.process_pubsub_pull(
        config_path=tmp_path / "config.yaml",
        relationship_context_path=tmp_path / "relationship.yaml",
        state_path=state_path,
        subscription_name="projects/test/subscriptions/torben",
    )

    assert result["wakeAgent"] is True
    assert result["candidates"][0]["message_key"] == "personal:m1"
    assert result["candidates"][0]["handle"].startswith("EA-")
    assert acked == ["ack-1"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["accounts"]["personal"]["history_id"] == "200"
    assert "personal:m1" in state["processed_message_keys"]


def test_process_pubsub_pull_suppresses_duplicate_message_keys(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)
    state_path = tmp_path / "watch-state.json"
    gmail_realtime.write_json(
        state_path,
        {
            "version": 1,
            "accounts": {"personal": {"email": "eric@example.com", "history_id": "100"}},
            "processed_message_keys": ["personal:m1"],
        },
    )
    received = [
        {
            "ackId": "ack-1",
            "message": {
                "messageId": "pubsub-1",
                "publishTime": "2026-06-25T10:00:00Z",
                "data": _encoded_notification(history_id="200"),
            },
        }
    ]
    record = {
        "account_alias": "personal",
        "message_id": "m1",
        "thread_id": "t1",
        "sender": "Kim Moore",
        "subject": "Follow up on funding",
        "category": "founder_funding_customer",
        "juno_bucket": "reply",
        "labels": ["INBOX"],
        "evidence_ids": ["gmail:personal:m1"],
    }
    acked: list[str] = []

    monkeypatch.setattr(gmail_realtime, "_enabled_gmail_accounts", lambda config_path: [account])
    monkeypatch.setattr(gmail_realtime, "pull_pubsub_messages", lambda **kwargs: received)
    monkeypatch.setattr(gmail_realtime, "_read_token", lambda account: "access-token")
    monkeypatch.setattr(
        gmail_realtime,
        "_list_history",
        lambda **kwargs: ([{"messagesAdded": [{"message": {"id": "m1", "labelIds": ["INBOX"]}}]}], 1, []),
    )
    monkeypatch.setattr(gmail_realtime, "_fetch_records", lambda **kwargs: ([record], 1, []))
    monkeypatch.setattr(gmail_realtime, "load_relationship_context", lambda path: {"people": [], "source_rules": {}, "principles": []})
    monkeypatch.setattr(
        gmail_realtime,
        "build_morning_briefing_candidates",
        lambda records, relationship_context=None: {"critical_emails": [], "learn_contact_candidates": [], "llm_decision_contract": {}},
    )
    monkeypatch.setattr(gmail_realtime, "ack_pubsub_messages", lambda subscription_name, ack_ids: acked.extend(ack_ids))

    result = gmail_realtime.process_pubsub_pull(
        config_path=tmp_path / "config.yaml",
        relationship_context_path=tmp_path / "relationship.yaml",
        state_path=state_path,
        subscription_name="projects/test/subscriptions/torben",
    )

    assert result["wakeAgent"] is False
    assert result["reason"] == "pubsub notifications processed with no realtime candidates"
    assert acked == ["ack-1"]


def test_fresh_realtime_records_suppresses_stale_history_messages() -> None:
    now = datetime.now(timezone.utc)
    old_record = {
        "message_id": "old-1",
        "internal_date_ms": str(int((now - timedelta(hours=3)).timestamp() * 1000)),
    }
    fresh_record = {
        "message_id": "fresh-1",
        "internal_date_ms": str(int((now - timedelta(minutes=5)).timestamp() * 1000)),
    }
    warnings: list[str] = []

    kept = gmail_realtime._fresh_realtime_records(
        [old_record, fresh_record],
        max_age_seconds=3600,
        warnings=warnings,
    )

    assert kept == [fresh_record]
    assert warnings == ["suppressed 1 stale Gmail history message(s) older than realtime max age"]


def test_run_gmail_realtime_canary_processes_and_cleans_up(tmp_path, monkeypatch) -> None:
    account = _account(tmp_path)
    state_path = tmp_path / "watch-state.json"
    gmail_realtime.write_json(
        state_path,
        {
            "version": 1,
            "accounts": {"personal": {"email": "eric@example.com", "history_id": "100"}},
            "processed_message_keys": [],
        },
    )
    cleanup: list[str] = []

    monkeypatch.setattr(gmail_realtime, "_enabled_gmail_accounts", lambda config_path: [account])
    monkeypatch.setattr(gmail_realtime, "_read_token", lambda account: "access-token")
    monkeypatch.setattr(
        gmail_realtime,
        "_gmail_import_message",
        lambda account, token, subject, body, label_ids=None: ("m-canary", 1),
    )
    monkeypatch.setattr(
        gmail_realtime,
        "_list_history",
        lambda account, token, start_history_id, max_pages=10: (
            [{"messagesAdded": [{"message": {"id": "m-canary", "labelIds": ["INBOX"]}}]}],
            1,
            [],
        ),
    )
    monkeypatch.setattr(gmail_realtime, "_google_get", lambda url, token: {"id": "m-canary"})

    def fake_process(**kwargs):
        state = gmail_realtime.load_json(state_path, {})
        state["last_pubsub_message_ids_by_account"] = {"personal": ["m-canary"]}
        gmail_realtime.write_json(state_path, state)
        return {
            "task": "torben_gmail_pubsub_pull",
            "wakeAgent": False,
            "reason": "pubsub notifications processed with no realtime candidates",
            "diagnostics": {"new_message_count": 1, "gmail_writes": 0, "external_mutations": 0},
        }

    monkeypatch.setattr(gmail_realtime, "process_pubsub_pull", fake_process)
    monkeypatch.setattr(gmail_realtime, "_gmail_trash_message", lambda token, message_id: cleanup.append(message_id) or 1)
    monkeypatch.setattr(gmail_realtime.time, "sleep", lambda seconds: None)

    result = gmail_realtime.run_gmail_realtime_canary(
        config_path=tmp_path / "config.yaml",
        relationship_context_path=tmp_path / "relationship.yaml",
        state_path=state_path,
        poll_interval_seconds=1,
        timeout_seconds=5,
    )

    assert result["status"] == "pass"
    assert result["wakeAgent"] is False
    assert result["canary_message"]["processed_by_pubsub_history"] is True
    assert result["canary_message"]["seen_by_gmail_history"] is True
    assert result["canary_message"]["visible_by_gmail_metadata"] is True
    assert result["canary_message"]["cleanup_status"] == "trashed_canary_message"
    assert result["diagnostics"]["gmail_mailbox_mutations"] == 2
    assert result["diagnostics"]["pubsub_poll_succeeded"] is True
    assert cleanup == ["m-canary"]
