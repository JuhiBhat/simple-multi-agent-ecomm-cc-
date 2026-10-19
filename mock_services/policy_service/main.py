"""ShopKart Policy Service (port 8002): the refund/return policy as text and as executable rules.

This is the non-RAG "knowledge source". The rules are plain Python, so the same order and
issue always give the same answer, and every answer names the rule (R1-R9) it came from.
"""
import logging
import os
import time
from datetime import date
from typing import Optional

import requests
from fastapi import FastAPI, Request
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("policy_service")

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order_service:8001")
# "Today" is fixed so the sample cases always give the same results. Override with REFERENCE_DATE.
REFERENCE_DATE = date.fromisoformat(os.getenv("REFERENCE_DATE", "2026-10-17"))

app = FastAPI(title="ShopKart Policy Service")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    logger.info(f"{request.method} {request.url.path} - Status: {response.status_code} - Latency: {(time.time() - start) * 1000:.2f}ms")
    return response


REFUND_POLICY_TEXT = """SHOPKART REFUND, RETURN & EXCEPTION POLICY (v1.0)

R1  Damaged / defective item: full refund or free replacement if reported within 7 days of delivery
    (within 2 days for grocery). Photo evidence is required for items priced above Rs 5,000.
R2  Wrong item delivered: same as R1 (refund or replacement, same reporting windows).
R3  Change-of-mind returns (size, fit, no longer needed) are allowed within the category window:
    apparel 30 days, home 10 days, books 10 days, electronics 7 days. Refund after the item is picked up.
R4  Non-returnable categories: grocery and personalised items cannot be returned for change of mind.
R5  Delayed delivery (measured from the promised date):
    up to 3 days late -> apologise and share tracking, no compensation yet;
    4 to 7 days late  -> refund the shipping fee and give a Rs 100 coupon;
    more than 7 days  -> customer may cancel for a full refund.
R6  Goodwill exception: Gold-tier customers up to 3 days outside a return window may be granted an
    exception, but ONLY with manual approval.
R7  Item marked delivered but customer says not received -> courier investigation required before any refund.
R8  Refunds go to the original payment method in 5-7 business days. Cash-on-delivery orders are refunded
    by bank transfer or store credit.
R9  Auto-approval limit: refunds up to Rs 10,000 may be approved automatically. Anything larger needs manual approval.
"""

RETURN_WINDOW_DAYS = {"apparel": 30, "home": 10, "books": 10, "electronics": 7}
NON_RETURNABLE = {"grocery", "personalised"}
DAMAGE_WINDOW_DAYS = {"default": 7, "grocery": 2}
PHOTO_REQUIRED_ABOVE_INR = 5000
GOLD_GRACE_DAYS = 3
DELAY_COUPON_INR = 100


def fetch_order(order_id: Optional[str]) -> Optional[dict]:
    if not order_id or order_id.upper() in ("NONE", "NULL", "N/A"):
        return None
    r = requests.get(f"{ORDER_SERVICE_URL}/orders/{order_id}", timeout=10)
    return r.json() if r.status_code == 200 else None


def _days_since(iso_day: str) -> int:
    return (REFERENCE_DATE - date.fromisoformat(iso_day)).days


def check_eligibility(order: Optional[dict], order_id: Optional[str], issue_type: str) -> dict:
    """Apply the refund policy to one order + issue."""
    result = {
        "order_id": order_id, "eligible": False, "rule_id": "", "rule_summary": "",
        "allowed_resolutions": [], "max_refund_inr": 0, "conditions": [],
        "exception_possible": False, "investigation_required": False,
        "days_since_delivery": None, "days_late": None, "reference_date": REFERENCE_DATE.isoformat(),
    }
    if order is None:
        result.update(rule_id="R0", rule_summary="Order not found. Ask the customer for a valid order ID.",
                      allowed_resolutions=["REQUEST_INFO"])
        return result

    cat, price = order["category"], order["price_inr"]
    delivered = order["status"] == "DELIVERED"
    if delivered and order["delivered_on"]:
        result["days_since_delivery"] = _days_since(order["delivered_on"])
    days = result["days_since_delivery"]

    if issue_type == "NOT_RECEIVED" and not delivered:   # not delivered yet = it's a delay
        issue_type = "DELAYED_DELIVERY"

    if issue_type in ("DAMAGED_PRODUCT", "WRONG_ITEM"):
        window = DAMAGE_WINDOW_DAYS.get(cat, DAMAGE_WINDOW_DAYS["default"])
        rule = "R1" if issue_type == "DAMAGED_PRODUCT" else "R2"
        if days is not None and days <= window:
            result.update(eligible=True, rule_id=rule, max_refund_inr=price,
                          conditions=["Photo evidence of the item"] if price > PHOTO_REQUIRED_ABOVE_INR else [],
                          allowed_resolutions=["FULL_REFUND", "REPLACEMENT"],
                          rule_summary=f"Reported {days} day(s) after delivery, within the {window}-day window.")
        else:
            result.update(rule_id=rule, allowed_resolutions=["DENY"],
                          rule_summary=f"Reported {days} day(s) after delivery, outside the {window}-day window.")

    elif issue_type == "RETURN_REQUEST":
        if cat in NON_RETURNABLE:
            result.update(rule_id="R4", allowed_resolutions=["DENY"],
                          rule_summary=f"'{cat}' items cannot be returned for change of mind.")
        else:
            window = RETURN_WINDOW_DAYS.get(cat, 7)
            if days is not None and days <= window:
                result.update(eligible=True, rule_id="R3", max_refund_inr=price,
                              allowed_resolutions=["RETURN_AND_REFUND", "EXCHANGE"],
                              conditions=["Item unused, with original tags and packaging"],
                              rule_summary=f"{days} day(s) since delivery, within the {window}-day {cat} window.")
            elif days is not None and order["tier"] == "Gold" and days - window <= GOLD_GRACE_DAYS:
                result.update(rule_id="R6", exception_possible=True, max_refund_inr=price,
                              allowed_resolutions=["RETURN_AND_REFUND", "EXCHANGE"],
                              rule_summary=f"{days - window} day(s) outside the {window}-day window; Gold tier "
                                           f"qualifies for a goodwill exception with manual approval.")
            else:
                result.update(rule_id="R3", allowed_resolutions=["DENY"],
                              rule_summary=f"{days} day(s) since delivery, outside the {window}-day {cat} window.")

    elif issue_type == "DELAYED_DELIVERY":
        if delivered:
            result.update(rule_id="R5", allowed_resolutions=["INFORM"],
                          rule_summary="Order already shows as delivered; no delay compensation applies.")
        else:
            late = _days_since(order["expected_by"])
            result["days_late"] = late
            if late <= 3:
                result.update(eligible=True, rule_id="R5", allowed_resolutions=["INFORM"],
                              rule_summary=f"{max(late, 0)} day(s) late: apologise and share tracking.")
            elif late <= 7:
                result.update(eligible=True, rule_id="R5", allowed_resolutions=["COMPENSATION"],
                              max_refund_inr=order["shipping_fee_inr"],
                              conditions=[f"Also issue a Rs {DELAY_COUPON_INR} coupon"],
                              rule_summary=f"{late} days late: refund shipping fee and give a Rs {DELAY_COUPON_INR} coupon.")
            else:
                result.update(eligible=True, rule_id="R5", allowed_resolutions=["CANCEL_AND_REFUND", "INFORM"],
                              max_refund_inr=price,
                              rule_summary=f"{late} days late: customer may cancel for a full refund.")

    elif issue_type == "NOT_RECEIVED":
        result.update(rule_id="R7", investigation_required=True, max_refund_inr=price,
                      allowed_resolutions=["INVESTIGATE"],
                      rule_summary="Marked delivered but reported not received: courier investigation required first.")

    elif issue_type == "REFUND_STATUS":
        result.update(eligible=True, rule_id="R8", allowed_resolutions=["INFORM"],
                      rule_summary=f"Refund status: {order.get('refund_status') or 'no refund initiated'}. Refunds reach "
                                   "the original payment method in 5-7 business days (COD: bank transfer or store credit).")
    else:
        result.update(rule_id="NONE", allowed_resolutions=["REQUEST_INFO"],
                      rule_summary="No specific policy rule matches; ask the customer for details.")

    if order["payment_method"] == "COD" and result["max_refund_inr"] > 0:
        result["conditions"].append("COD order: refund by bank transfer or store credit")
    return result


@app.get("/health")
def health():
    return {"status": "healthy", "service": "policy_service"}


@app.get("/policy")
def get_policy():
    return {"policy_text": REFUND_POLICY_TEXT}


class EligibilityRequest(BaseModel):
    order_id: Optional[str] = None
    issue_type: str


@app.post("/policy/eligibility")
def eligibility(req: EligibilityRequest):
    order = fetch_order(req.order_id)
    result = check_eligibility(order, req.order_id, req.issue_type.strip().upper())
    logger.info(f"Eligibility {req.order_id}/{req.issue_type}: rule={result['rule_id']} eligible={result['eligible']}")
    return result
