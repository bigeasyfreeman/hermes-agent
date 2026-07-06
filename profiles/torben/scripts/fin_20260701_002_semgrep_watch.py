from __future__ import annotations
import base64,json,re,sys,urllib.parse,urllib.request
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,"/Users/ericfreeman/.hermes/hermes-agent")
from hermes_cli.signal_coo.google_auth import load_google_accounts, check_account
HOME=Path("/Users/ericfreeman/.hermes/profiles/torben"); CONFIG=HOME/"config"/"google_accounts.yaml"; GMAIL="https://gmail.googleapis.com/gmail/v1/users/me"
ACCOUNT_ALIAS="work_magellan"; CASE_HANDLE="FIN-20260701-002"; MONITOR_AFTER="2026-07-01T13:11:18.663205Z"; IGNORED_MESSAGE_IDS={"19f1dce2a9df0cc3","19e425c341f85815","19f11b3edf8e93ac","19f1dce3631405a9"}
def utcnow(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def token_for_account():
 acc=load_google_accounts(CONFIG)[ACCOUNT_ALIAS]; st=check_account(acc)
 if not st.status.startswith("authenticated"): raise RuntimeError(f"Google account {ACCOUNT_ALIAS} not authenticated: {st.status} {st.reason or ''}")
 return acc.email,json.loads(acc.token_path.read_text())["token"]
def gmail_get(url,token):
 req=urllib.request.Request(url,headers={"Authorization":f"Bearer {token}"})
 with urllib.request.urlopen(req,timeout=30) as resp: return json.loads(resp.read().decode() or "{}")
def headers(msg): return {h.get("name","").lower():h.get("value","") for h in ((msg.get("payload") or {}).get("headers") or [])}
def dec(data):
 if not data: return ""
 data += "="*((4-len(data)%4)%4)
 return base64.urlsafe_b64decode(data.encode()).decode("utf-8","replace")
def extract(part):
 out=[]; mt=part.get("mimeType",""); data=(part.get("body") or {}).get("data")
 if data and mt in {"text/plain","text/html"}:
  s=dec(data)
  if mt=="text/html": s=re.sub(r"<br\s*/?>","\n",s,flags=re.I); s=re.sub(r"</p>","\n",s,flags=re.I); s=re.sub(r"<[^>]+>"," ",s)
  out.append(re.sub(r"\s+"," ",s).strip())
 for child in part.get("parts") or []: out.extend(extract(child))
 return out
def main():
 email,token=token_for_account(); cutoff=int(datetime.fromisoformat(MONITOR_AFTER.replace('Z','+00:00')).timestamp()*1000)
 queries=['newer_than:45d (Semgrep OR semgrep.dev OR r2c OR returntocorp) (cancel OR cancellation OR refund OR billing OR charge OR invoice OR payment OR decline OR declined OR delete OR deletion)','newer_than:45d from:(semgrep.com OR semgrep.dev OR mercury.com) (Semgrep OR billing OR transaction OR refund OR cancel)']
 ids={}
 for q in queries:
  try: listed=gmail_get(f"{GMAIL}/messages?"+urllib.parse.urlencode({"q":q,"maxResults":"30"}),token)
  except Exception: continue
  for it in listed.get("messages") or []: ids[it["id"]]=it.get("threadId")
 hits=[]
 for mid,tid in ids.items():
  if mid in IGNORED_MESSAGE_IDS: continue
  params=urllib.parse.urlencode({"format":"full","metadataHeaders":["From","To","Subject","Date"]},doseq=True)
  msg=gmail_get(f"{GMAIL}/messages/{mid}?{params}",token)
  if int(msg.get("internalDate") or 0) <= cutoff: continue
  h=headers(msg); from_header=(h.get("from") or "").lower()
  if email.lower() in from_header: continue
  body="\n".join(extract(msg.get("payload") or {}))[:2500]
  blob=(from_header+"\n"+(h.get("subject") or "")+"\n"+(msg.get("snippet") or "")+"\n"+body).lower()
  if ("semgrep" in blob or "mercury" in from_header) and any(t in blob for t in ["cancel","delete","refund","billing","charge","declin","payment","invoice","subscription"]): hits.append({"id":mid,"thread_id":msg.get("threadId") or tid,"date":h.get("date"),"from":h.get("from"),"subject":h.get("subject"),"snippet":msg.get("snippet")})
 print(json.dumps({"case_handle":CASE_HANDLE,"checked_at":utcnow(),"account_email":email,"new_relevant_count":len(hits),"new_relevant_messages":hits},indent=2,sort_keys=True))
if __name__ == "__main__":
    from torben_job_contract import run_job

    raise SystemExit(run_job("fin_20260701_002_semgrep_watch", main))
