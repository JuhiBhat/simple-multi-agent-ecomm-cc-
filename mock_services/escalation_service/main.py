"""ShopKart Escalation Service (port 8004): deterministic escalation rules + the human review queue.

Escalation is a deliberate decision with explicit thresholds, not a vague "if needed":

| Rule                 | Trigger                                              | Priority -> Team               |
|----------------------|------------------------------------------------------|--------------------------------|
| ESC_SAFETY           | fire, smoke, burn, shock or injury mentioned         | P1 -> Trust & Safety / Legal   |
| ESC_LEGAL            | consumer court, lawyer, legal notice, police         | P1 -> Trust & Safety / Legal   |
| ESC_FRAUD_HISTORY    | 3 or more refund claims in the last 90 days          | P2 -> Fraud & Risk             |
| ESC_NOT_RECEIVED     | marked delivered but reported not received           | P2 -> Fraud & Risk             |
| ESC_HIGH_VALUE       | refund above Rs 10,000 (auto-approval limit)         | P3 -> Refund Approvals         |
| ESC_POLICY_EXCEPTION | Gold goodwill exception (policy R6)                  | P3 -> Refund Approvals         |
| ESC_LOW_CONFIDENCE   | issue classification confidence below 0.70           | P4 -> Senior Support           |
"""
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import List, Optional

import requests
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from mock_services.data.database import get_db, init_db
from mock_services.data.models import TicketDB

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("escalation_service")

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order_service:8001")
POLICY_SERVICE_URL = os.getenv("POLICY_SERVICE_URL", "http://policy_service:8002")

AUTO_APPROVAL_LIMIT_INR = 10000
LOW_CONFIDENCE_THRESHOLD = 0.70
SAFETY_WORDS = ["fire", "smoke", "smoking", "burn", "explode", "exploded", "shock", "injur", "hurt", "spark"]
LEGAL_WORDS = ["consumer court", "consumer forum", "lawyer", "legal action", "legal notice", "police", "sue you"]

PRIORITY_ROUTE = {
    "P1": "Trust & Safety / Legal team",
    "P2": "Fraud & Risk team",
    "P3": "Refund Approvals team",
    "P4": "Senior Support agent",
}
PRIORITY_SLA = {"P1": "4 hours", "P2": "24 hours", "P3": "24 hours", "P4": "48 hours"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ShopKart Escalation Service", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    logger.info(f"{request.method} {request.url.path} - Status: {response.status_code} - Latency: {(time.time() - start) * 1000:.2f}ms")
    return response


def _clean_order_id(order_id: Optional[str]) -> Optional[str]:
    if not order_id or order_id.strip().upper() in ("NONE", "NULL", "N/A", ""):
        return None
    return order_id.strip().upper()


@app.get("/health")
def health():
    return {"status": "healthy", "service": "escalation_service"}


class EvaluateRequest(BaseModel):
    order_id: Optional[str] = None
    issue_type: str
    refund_amount_inr: float = 0
    confidence: float = 1.0
    customer_message: str = ""


@app.post("/escalation/evaluate")
def evaluate(req: EvaluateRequest):
    order_id = _clean_order_id(req.order_id)
    order = None
    if order_id:
        r = requests.get(f"{ORDER_SERVICE_URL}/orders/{order_id}", timeout=10)
        order = r.json() if r.status_code == 200 else None
    eligibility = requests.post(f"{POLICY_SERVICE_URL}/policy/eligibility",
                                json={"order_id": order_id, "issue_type": req.issue_type}, timeout=10).json()

    text = (req.customer_message or "").lower()
    fired = []  # (rule_id, priority, reason)
    if any(w in text for w in SAFETY_WORDS):
        fired.append(("ESC_SAFETY", "P1", "Possible product safety hazard or injury mentioned"))
    if any(w in text for w in LEGAL_WORDS):
        fired.append(("ESC_LEGAL", "P1", "Customer mentions legal action"))
    if order and order["refund_claims_90d"] >= 3:
        fired.append(("ESC_FRAUD_HISTORY", "P2", f"{order['refund_claims_90d']} refund claims in the last 90 days"))
    if eligibility["investigation_required"]:
        fired.append(("ESC_NOT_RECEIVED", "P2", "Marked delivered but reported not received"))
    if req.refund_amount_inr > AUTO_APPROVAL_LIMIT_INR:
        fired.append(("ESC_HIGH_VALUE", "P3", f"Refund Rs {req.refund_amount_inr:,.0f} exceeds the Rs {AUTO_APPROVAL_LIMIT_INR:,} auto-approval limit"))
    if eligibility["exception_possible"]:
        fired.append(("ESC_POLICY_EXCEPTION", "P3", "Goodwill policy exception needs manual approval"))
    if req.confidence < LOW_CONFIDENCE_THRESHOLD and order is not None:
        fired.append(("ESC_LOW_CONFIDENCE", "P4", f"Classification confidence {req.confidence:.2f} is below {LOW_CONFIDENCE_THRESHOLD}"))

    if fired:
        priority = min(p for _, p, _ in fired)          # "P1" sorts before "P2", so min() = most urgent
        status, escalate = "ESCALATED", True
    elif order is None:
        priority, status, escalate = "NONE", "NEEDS_INFO", False
    elif not eligibility["eligible"]:
        priority, status, escalate = "NONE", "DENIED", False
    else:
        priority, status, escalate = "NONE", "AUTO_RESOLVED", False

    result = {
        "escalate": escalate,
        "priority": priority,
        "route_to": PRIORITY_ROUTE.get(priority, "None: handled automatically"),
        "sla": PRIORITY_SLA.get(priority),
        "final_status": status,
        "triggered_rules": [r for r, _, _ in fired],
        "reasons": [why for _, _, why in fired],
        "policy_rule_id": eligibility["rule_id"],
    }
    logger.info(f"Escalation decision for {order_id}: {status} {priority} {result['triggered_rules']}")
    return result


class TicketRequest(BaseModel):
    order_id: Optional[str] = None
    priority: str
    triggered_rules: List[str] = []
    summary: str
    customer_message: str = ""


@app.post("/tickets")
def create_ticket(req: TicketRequest, db: Session = Depends(get_db)):
    priority = req.priority.strip().upper()
    ticket = TicketDB(order_id=_clean_order_id(req.order_id), priority=priority,
                      team=PRIORITY_ROUTE.get(priority, "Senior Support agent"),
                      triggered_rules=",".join(req.triggered_rules), summary=req.summary,
                      customer_message=req.customer_message)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    ref = f"ESC-{ticket.id:04d}"
    logger.info(f"Created ticket {ref} ({priority}) for {ticket.order_id} -> {ticket.team}")
    return {"ticket_ref": ref, "priority": priority, "team": ticket.team,
            "sla": PRIORITY_SLA.get(priority, "48 hours"), "status": ticket.status}


@app.get("/tickets")
def list_tickets(db: Session = Depends(get_db)):
    tickets = db.query(TicketDB).order_by(TicketDB.id.desc()).all()
    return {"tickets": [{
        "ticket_ref": f"ESC-{t.id:04d}", "order_id": t.order_id, "priority": t.priority, "team": t.team,
        "triggered_rules": t.triggered_rules.split(",") if t.triggered_rules else [],
        "summary": t.summary, "status": t.status, "created_at": t.created_at.isoformat(timespec="seconds"),
    } for t in tickets]}
