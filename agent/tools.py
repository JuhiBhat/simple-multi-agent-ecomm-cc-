"""Connects to the MCP server and decides which tools each agent may use.

Agents never call the microservices directly. Tools are discovered from the MCP server over SSE,
then filtered per agent (least privilege): an agent only sees the tools its job needs.
"""
import logging
import os

from crewai_tools import MCPServerAdapter

logger = logging.getLogger("agent_mcp_client")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://mcp_server:8003/sse")
MCP_SERVER_PARAMS = {"url": MCP_SERVER_URL, "transport": "sse"}

# Which MCP tools each agent is allowed to use
AGENT_TOOL_ACCESS = {
    "issue_identification": ["lookup_order"],
    "policy_interpretation": ["check_refund_policy"],
    "resolution_recommendation": [],                       # reasons only over what it is handed
    "escalation": ["run_escalation_rules"],               # decides only; actions run in code
}
# create_escalation_ticket and issue_refund are called only by execute_action() in crew.py,
# so no LLM can open a ticket or move money by itself.


def connect_mcp() -> MCPServerAdapter:
    """Open a connection to the MCP server. Use as a context manager:  with connect_mcp() as tools: ..."""
    logger.info(f"Connecting to MCP server at {MCP_SERVER_URL}")
    return MCPServerAdapter(MCP_SERVER_PARAMS, connect_timeout=30)


def tools_for(agent_key: str, all_tools) -> list:
    allowed = AGENT_TOOL_ACCESS[agent_key]
    return [t for t in all_tools if t.name in allowed]


def tool_by_name(name: str, all_tools):
    for t in all_tools:
        if t.name == name:
            return t
    raise KeyError(f"MCP tool '{name}' not found. Available: {[t.name for t in all_tools]}")
