"""
POC: Feasibility demo for the A5 GL Governance agent flow.

Chain being proven:
  1. Dummy "SAP webhook" fires  ->  hits /sap/gl-created
  2. That calls the "Databricks agent" logic (run_agent)
  3. Agent calls dummy "Master Data" API  ->  /dummy/master-data/{gl_id}
  4. Agent applies business logic (dormancy / validity check)
  5. Agent calls dummy "UiPath/Power Automate" API -> /dummy/automation/trigger
  6. Response bubbles back up to whoever called step 1

Run:  uvicorn gl_agent_poc:app --port 8000
Then: curl -X POST http://127.0.0.1:8000/sap/gl-created -H "Content-Type: application/json" -d '{"gl_id": "GL-1001"}'
"""

from fastapi import FastAPI
from pydantic import BaseModel
import httpx
import datetime

app = FastAPI(title="GL Agent Feasibility POC")

BASE_URL = "http://127.0.0.1:8000"

# ---------------------------------------------------------------------------
# DUMMY 1: stands in for SAP MDG's "get master data" API
# ---------------------------------------------------------------------------
FAKE_GL_DB = {
    "GL-1001": {"gl_id": "GL-1001", "description": "Office Rent - HQ",
                "company_code": "1000", "last_posting_date": None,   # never posted -> dormant
                "amount": 0},
    "GL-1002": {"gl_id": "GL-1002", "description": "Travel Expenses",
                "company_code": "1000", "last_posting_date": "2026-07-15",
                "amount": 45000},
}

@app.get("/dummy/master-data/{gl_id}")
def get_master_data(gl_id: str):
    record = FAKE_GL_DB.get(gl_id, {
        "gl_id": gl_id, "description": "Unknown GL", "company_code": "1000",
        "last_posting_date": None, "amount": 0
    })
    return record


# ---------------------------------------------------------------------------
# DUMMY 2: stands in for the UiPath / Power Automate trigger API
# ---------------------------------------------------------------------------
class AutomationRequest(BaseModel):
    gl_id: str
    action: str
    reason: str

@app.post("/dummy/automation/trigger")
def trigger_automation(req: AutomationRequest):
    # In real life: this is UiPath Orchestrator's StartJobs API,
    # or a Power Automate HTTP-trigger flow posting a Teams Adaptive Card.
    return {
        "bot_run_id": "RUN-8842",
        "status": "queued",
        "action_received": req.action,
        "gl_id": req.gl_id,
        "message": f"Automation triggered for {req.gl_id}: {req.action}"
    }


# ---------------------------------------------------------------------------
# THE "DATABRICKS AGENT" — this function is what would live inside a
# Databricks notebook/job in the real architecture.
# ---------------------------------------------------------------------------
def run_agent(gl_id: str) -> dict:
    audit_trail = []

    # Step A: pull master data
    resp = httpx.get(f"{BASE_URL}/dummy/master-data/{gl_id}")
    record = resp.json()
    audit_trail.append({"step": "fetch_master_data", "result": record})

    # Step B: business logic (dormancy check - simplified A5 rule)
    if record["last_posting_date"] is None:
        decision = "flag_dormant"
        reason = "No posting history found - candidate for blocking"
    elif record["amount"] > 100000:
        decision = "flag_review"
        reason = "High-value account - needs manual review"
    else:
        decision = "no_action"
        reason = "Account active and within normal thresholds"

    audit_trail.append({"step": "business_logic", "decision": decision, "reason": reason})

    # Step C: call automation layer only if action needed
    automation_result = None
    if decision != "no_action":
        auto_resp = httpx.post(f"{BASE_URL}/dummy/automation/trigger", json={
            "gl_id": gl_id, "action": decision, "reason": reason
        })
        automation_result = auto_resp.json()
        audit_trail.append({"step": "trigger_automation", "result": automation_result})

    return {
        "gl_id": gl_id,
        "decision": decision,
        "reason": reason,
        "automation_result": automation_result,
        "audit_trail": audit_trail,
        "timestamp": datetime.datetime.utcnow().isoformat()
    }


# ---------------------------------------------------------------------------
# ENTRY POINT: stands in for the "SAP webhook -> triggers Databricks job" call
# ---------------------------------------------------------------------------
class SapEvent(BaseModel):
    gl_id: str

@app.post("/sap/gl-created")
def sap_gl_created(event: SapEvent):
    # In real life: this HTTP call would instead be a Databricks Jobs API
    # "run-now" call, and run_agent() would execute as a Databricks task.
    result = run_agent(event.gl_id)
    return result


@app.get("/")
def health():
    return {"status": "up", "try": "POST /sap/gl-created with {'gl_id': 'GL-1001'}"}