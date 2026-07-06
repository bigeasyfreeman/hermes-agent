from __future__ import annotations
import base64, json, re, sys, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
sys.path.insert(0, "/Users/ericfreeman/.hermes/hermes-agent")
from hermes_cli.signal_coo.google_auth import load_google_accounts, check_account

HOME=Path("/Users/ericfreeman/.hermes/profiles/torben")
CONFIG=HOME/"config"/"google_accounts.yaml"
GMAIL="https://gmail.googleapis.com/gmail/v1/users/me"
ACCOUNT_ALIAS="personal_freeman"
CASE_HANDLE="FIN-20260701-001"
CASE_PATH=Path("/Users/ericfreeman/.hermes/profiles/torben/state/finance-cancellation-cases/FIN-20260701-001-dramashorts-cancellation.md")
MONITOR_AFTER="2026-07-01T12:33:51.922292Z"
IGNORED_MESSAGE_IDS={
    "19f1db1656329961",  # initial Torben reconciliation email
    "19f1db4cd6c09f10",  # Torben screenshot charge-evidence follow-up
    "19f1db2dad4362bb",  # vendor auto-ack: cancellation request received
    "19f1db2da82f3500",  # vendor auto-ack: refund request received
    "19f1db5844b30c3c",  # vendor human reply: partial June 22 refund only, challenged
    "19f1db7cfd7ce0da",  # Torben challenge requesting all post-cancellation charges
}

def utcnow(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def token_for_account():
    acc=load_google_accounts(CONFIG)[ACCOUNT_ALIAS]
    st=check_account(acc)
    if not st.status.startswith("authenticated"):
        raise RuntimeError(f"Google account {ACCOUNT_ALIAS} not authenticated: {st.status} {st.reason or ''}")
    return acc.email, json.loads(acc.token_path.read_text(encoding="utf-8"))["token"]

def gmail_get(url, token):
    req=urllib.request.Request(url,headers={"Authorization":f"Bearer {token}"})
    with urllib.request.urlopen(req,timeout=30) as resp:
        return json.loads(resp.read().decode() or "{}")

def headers(msg):
    return {h.get("name","").lower():h.get("value","") for h in ((msg.get("payload") or {}).get("headers") or [])}

def dec(data):
    if not data: return ""
    data += "="*((4-len(data)%4)%4)
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8","replace")

def extract(part):
    out=[]; mt=part.get("mimeType",""); data=(part.get("body") or {}).get("data")
    if data and mt in {"text/plain","text/html"}:
        s=dec(data)
        if mt=="text/html":
            s=re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
            s=re.sub(r"</p>", "\n", s, flags=re.I)
            s=re.sub(r"<[^>]+>", " ", s)
        out.append(re.sub(r"\s+"," ",s).strip())
    for child in part.get("parts") or []: out.extend(extract(child))
    return out

def main():
    email, token=token_for_account()
    queries=[
        'newer_than:45d (DramaShorts OR "Drama Shorts" OR dramashorts.io OR "Dramashorts")',
        'newer_than:45d from:(apple.com) (DramaShorts OR "Drama Shorts" OR subscription OR receipt OR invoice)',
        'newer_than:45d from:(robinhood.com) Dramashorts',
    ]
    ids={}
    for q in queries:
        try:
            listed=gmail_get(f"{GMAIL}/messages?"+urllib.parse.urlencode({"q":q,"maxResults":"20"}), token)
        except Exception:
            continue
        for it in listed.get("messages") or []:
            ids[it["id"]]=it.get("threadId")
    hits=[]
    cutoff=int(datetime.fromisoformat(MONITOR_AFTER.replace('Z','+00:00')).timestamp()*1000)
    for mid,tid in ids.items():
        params=urllib.parse.urlencode({"format":"full","metadataHeaders":["From","To","Subject","Date"]}, doseq=True)
        msg=gmail_get(f"{GMAIL}/messages/{mid}?{params}", token)
        internal=int(msg.get("internalDate") or 0)
        if internal <= cutoff:
            continue
        if mid in IGNORED_MESSAGE_IDS:
            continue
        h=headers(msg); body="\n".join(extract(msg.get("payload") or {}))[:2500]
        from_header=(h.get("from") or "").lower()
        if email.lower() in from_header:
            continue
        blob=(from_header+"\n"+(h.get("subject") or "")+"\n"+(msg.get("snippet") or "")+"\n"+body).lower()
        relevant=("dramashorts" in blob or "drama shorts" in blob or "dramashorts.io" in blob or "dramashorts" in (h.get("subject") or "").lower())
        apple_possible=("apple" in (h.get("from") or "").lower() and ("receipt" in blob or "invoice" in blob or "subscription" in blob))
        if relevant or apple_possible:
            hits.append({"id":mid,"thread_id":msg.get("threadId") or tid,"date":h.get("date"),"from":h.get("from"),"subject":h.get("subject"),"snippet":msg.get("snippet")})
    output={"case_handle":CASE_HANDLE,"checked_at":utcnow(),"account_email":email,"new_relevant_messages":hits,"new_relevant_count":len(hits),"case_path":str(CASE_PATH)}
    print(json.dumps(output, indent=2, sort_keys=True))
if __name__ == "__main__":
    from torben_job_contract import run_job

    raise SystemExit(run_job("fin_20260701_001_dramashorts_watch", main))
