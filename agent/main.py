"""ShopKart Agent Service (port 8000): the REST gateway the frontend talks to."""
import json
import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from agent.crew import run_crew
from agent.session_manager import build_customer_message, clear_session, get_session, update_after_run
from agent.tools import connect_mcp, tool_by_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("agent_gateway")

app = FastAPI(title="ShopKart Agent Service (CrewAI)")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    logger.info(f"{request.method} {request.url.path} - Status: {response.status_code} - Latency: {(time.time() - start) * 1000:.2f}ms")
    return response


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ClearChatRequest(BaseModel):
    session_id: str


@app.get("/health")
def health():
    return {"status": "healthy", "service": "agent_service"}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    logger.info(f"Incoming message for session {request.session_id}")
    session = get_session(request.session_id)
    customer_message = build_customer_message(session, request.message)
    try:
        # CrewAI's kickoff() is synchronous, so run it in a worker thread
        result = await run_in_threadpool(run_crew, customer_message)
    except Exception as e:
        logger.error(f"Crew execution failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")
    update_after_run(session, customer_message, result["final_status"])
    logger.info(f"Session {request.session_id}: {result['final_status']} {result['priority']}")
    return result


@app.post("/api/clear_chat")
def clear_chat(request: ClearChatRequest):
    clear_session(request.session_id)
    return {"status": "success", "message": "Session cleared"}


def _call_mcp_tool(name: str) -> dict:
    with connect_mcp() as tools:
        return json.loads(tool_by_name(name, tools).run())


@app.get("/api/tickets")
async def tickets():
    """Human review queue, read through the MCP server."""
    return await run_in_threadpool(_call_mcp_tool, "list_escalation_tickets")


@app.get("/api/orders")
async def orders():
    """Mock orders, for the frontend's reference panel."""
    return await run_in_threadpool(_call_mcp_tool, "list_orders")
