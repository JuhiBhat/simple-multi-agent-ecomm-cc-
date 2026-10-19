"""ShopKart MCP Server (port 8003).

Exposes every capability the agents need as MCP tools over SSE. The agents never call the
microservices directly: this server is the single point of contact, and it logs every tool call.
"""
import json
import logging
import os
from typing import List

import requests
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("mcp_server")

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order_service:8001")
POLICY_SERVICE_URL = os.getenv("POLICY_SERVICE_URL", "http://policy_service:8002")
ESCALATION_SERVICE_URL = os.getenv("ESCALATION_SERVICE_URL", "http://escalation_service:8004")

mcp = FastMCP("shopkart_customer_care_mcp", host="0.0.0.0", port=int(os.getenv("PORT", "8003")))


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    return JSONResponse({"status": "healthy", "service": "shopkart_mcp_server"})


def _call(method: str, url: str, **kwargs) -> str:
    """Call a microservice and always return a JSON string (errors included) the agent can read."""
    try:
        r = requests.request(method, url, timeout=15, **kwargs)
        body = r.json()
        if r.status_code >= 400:
            return json.dumps({"error": True, "status_code": r.status_code, "detail": body.get("detail", body)})
        return json.dumps(body)
    except Exception as e:
        logger.error(f"Call to {url} failed: {e}")
        return json.dumps({"error": True, "detail": str(e)})


# --- Agent 1: Order Issue Identification ---

@mcp.tool()
def lookup_order(order_id: str) -> str:
    """Look up an order in ShopKart's order database by its order ID (format ORD followed by 4 digits,
    e.g. ORD1001). Returns order, item, delivery and customer details as JSON, or an error if not found."""
    logger.info(f"MCP executing lookup_order({order_id})")
    return _call("GET", f"{ORDER_SERVICE_URL}/orders/{order_id.strip()}")


# --- Agent 2: Policy Interpretation ---

@mcp.tool()
def get_refund_policy() -> str:
    """Returns the full text of ShopKart's refund, return and exception policy (rules R1-R9)."""
    logger.info("MCP executing get_refund_policy()")
    return _call("GET", f"{POLICY_SERVICE_URL}/policy")


@mcp.tool()
def check_refund_policy(order_id: str, issue_type: str) -> str:
    """Apply ShopKart's official refund/return policy to an order. issue_type must be one of:
    DAMAGED_PRODUCT, WRONG_ITEM, RETURN_REQUEST, DELAYED_DELIVERY, NOT_RECEIVED, REFUND_STATUS, OTHER.
    Use order_id 'NONE' if the customer gave no order ID. Returns eligibility, the rule applied,
    allowed resolutions, the maximum refund and conditions. This result is authoritative."""
    logger.info(f"MCP executing check_refund_policy({order_id}, {issue_type})")
    return _call("POST", f"{POLICY_SERVICE_URL}/policy/eligibility",
                 json={"order_id": order_id, "issue_type": issue_type})


# --- Agent 4: Escalation ---

@mcp.tool()
def run_escalation_rules(order_id: str, issue_type: str, refund_amount_inr: float,
                         confidence: float, customer_message: str) -> str:
    """Run ShopKart's mandatory escalation rules. Pass the order ID (or 'NONE'), the issue type, the
    proposed refund amount in rupees, the issue classification confidence (0-1) and the customer's
    original message word for word. Returns escalate (true/false), priority, the team to route to,
    the final status and which rules fired. This result is authoritative: never override it."""
    logger.info(f"MCP executing run_escalation_rules({order_id}, {issue_type}, {refund_amount_inr}, {confidence})")
    return _call("POST", f"{ESCALATION_SERVICE_URL}/escalation/evaluate", json={
        "order_id": order_id, "issue_type": issue_type, "refund_amount_inr": refund_amount_inr,
        "confidence": confidence, "customer_message": customer_message})


@mcp.tool()
def create_escalation_ticket(order_id: str, priority: str, triggered_rules: List[str],
                             summary: str, customer_message: str) -> str:
    """Create a ticket in the human review queue. Call this ONLY when run_escalation_rules returned
    escalate=true. priority is P1-P4 exactly as returned by run_escalation_rules. Returns the ticket
    reference (e.g. ESC-0001), the team and the response-time SLA."""
    logger.info(f"MCP executing create_escalation_ticket({order_id}, {priority}, {triggered_rules})")
    return _call("POST", f"{ESCALATION_SERVICE_URL}/tickets", json={
        "order_id": order_id, "priority": priority, "triggered_rules": triggered_rules,
        "summary": summary, "customer_message": customer_message})


@mcp.tool()
def issue_refund(order_id: str, amount_inr: float, reason: str) -> str:
    """Initiate a refund to the customer's original payment method. Call this ONLY when
    run_escalation_rules returned final_status AUTO_RESOLVED and the proposed refund is above 0.
    The order service refuses refunds above Rs 10,000 (those need manual approval)."""
    logger.info(f"MCP executing issue_refund({order_id}, {amount_inr})")
    return _call("POST", f"{ORDER_SERVICE_URL}/orders/{order_id.strip()}/refund",
                 json={"amount_inr": amount_inr, "reason": reason})


# --- For the dashboard (not given to any agent) ---

@mcp.tool()
def list_escalation_tickets() -> str:
    """List all tickets in the human review queue, newest first."""
    logger.info("MCP executing list_escalation_tickets()")
    return _call("GET", f"{ESCALATION_SERVICE_URL}/tickets")


@mcp.tool()
def list_orders() -> str:
    """List all orders in the mock database."""
    logger.info("MCP executing list_orders()")
    return _call("GET", f"{ORDER_SERVICE_URL}/orders")


# ASGI application for the SSE transport
app = mcp.sse_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("mcp_server.server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8003")), reload=False)
