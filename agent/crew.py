"""The 4-agent CrewAI workflow: agents, tasks, handoffs, routing and the action step.

    Agent 1  Order Issue Identification  --IssueReport-->        (guardrail: order ID must be in the message)
    Agent 2  Policy Interpretation       --PolicyAssessment-->
    Agent 3  Resolution Recommendation   --ResolutionPlan-->     (ConditionalTask: skipped if no valid order)
    Agent 4  Escalation                  --EscalationDecision-->
    Code     execute_action()            one deterministic action: open a ticket, issue a refund, or nothing

Each task lists the earlier tasks in `context=[...]`: that is the handoff. Every agent depends on
the structured output of the ones before it. The LLM interprets and writes; plain code makes the
decisions that move money or open tickets, so each case gets exactly one, correct action.
"""
import json
import logging
import re
import threading

from crewai import Agent, Crew, Process, Task
from crewai.tasks.conditional_task import ConditionalTask
from crewai.events import ToolUsageFinishedEvent, crewai_event_bus
from pydantic import ValidationError

from agent.llm import build_llm
from agent.schemas import EscalationDecision, IssueReport, PolicyAssessment, ResolutionPlan
from agent.tools import connect_mcp, tool_by_name, tools_for

logger = logging.getLogger("agent_crew")

llm = build_llm()

ORDER_ID_PATTERN = re.compile(r"ORD\d{4}", re.IGNORECASE)
REFUND_ACTIONS = {"FULL_REFUND", "COMPENSATION", "CANCEL_AND_REFUND"}   # actions that pay money now
SIGN_OFF = "ShopKart Customer Care"

# ---------------------------------------------------------------------------
# Tool-call capture for the UI: CrewAI emits an event every time an agent uses a tool
# ---------------------------------------------------------------------------
_run_lock = threading.Lock()      # one crew at a time keeps the tool-call log per request
_current_tool_calls = None


@crewai_event_bus.on(ToolUsageFinishedEvent)
def _record_tool_call(source, event):
    if _current_tool_calls is not None:
        _current_tool_calls.append({
            "agent": event.agent_role,
            "name": event.tool_name,
            "args": event.tool_args if isinstance(event.tool_args, dict) else str(event.tool_args),
            "output": str(event.output)[:600],
        })


# ---------------------------------------------------------------------------
# Agents: one tight responsibility each
# ---------------------------------------------------------------------------
def build_agents(all_tools, policy_text: str):
    issue_agent = Agent(
        role="Order Issue Identification Specialist",
        goal="Read the customer's message, find their order and classify the issue precisely, "
             "with an honest confidence score.",
        backstory="You are the first line of ShopKart support. You never guess order details: you only look "
                  "up an order ID the customer actually wrote. You only classify; you never promise refunds "
                  "or quote policy.",
        tools=tools_for("issue_identification", all_tools),
        llm=llm, allow_delegation=False, max_iter=5, verbose=False,
    )
    policy_agent = Agent(
        role="Refund & Returns Policy Analyst",
        goal="Determine exactly what ShopKart's policy allows for the classified issue.",
        backstory="You are ShopKart's policy expert. You always run check_refund_policy and treat its result "
                  "as the official answer. You explain it clearly but never bend it. Policy for reference:\n\n"
                  + policy_text,
        tools=tools_for("policy_interpretation", all_tools),
        llm=llm, allow_delegation=False, max_iter=5, verbose=False,
    )
    resolution_agent = Agent(
        role="Customer Resolution Specialist",
        goal="Choose the best resolution the policy allows and write a warm, clear reply to the customer.",
        backstory="You turn policy decisions into good customer outcomes. You only choose from the allowed "
                  "resolutions, never exceed the maximum refund and never invent compensation. "
                  "You write empathetically, in simple English.",
        tools=tools_for("resolution_recommendation", all_tools),
        llm=llm, allow_delegation=False, max_iter=3, verbose=False,
    )
    escalation_agent = Agent(
        role="Risk & Escalation Officer",
        goal="Decide whether the case can be closed automatically or needs human approval, using the "
             "mandatory escalation rules, and write the final message to the customer.",
        backstory="You are the final checkpoint before anything reaches the customer. You always run "
                  "run_escalation_rules and follow its result exactly. You never downgrade an escalation, and "
                  "you never promise customers an outcome that a human still has to approve. The support "
                  "system opens tickets and issues refunds automatically after your decision.",
        tools=tools_for("escalation", all_tools),
        llm=llm, allow_delegation=False, max_iter=4, verbose=False,
    )
    return issue_agent, policy_agent, resolution_agent, escalation_agent


# ---------------------------------------------------------------------------
# Tasks: the handoffs are the `context=[...]` lists
# ---------------------------------------------------------------------------
# Small models sometimes echo the JSON schema back instead of filling it in; this line prevents that
NOT_THE_SCHEMA = ("Fill in real values for this case. Do NOT return the JSON schema itself "
                  "(no 'properties', 'type', 'required' or 'description' keys).")
REPLY_STYLE = (f"Sign off as '{SIGN_OFF}'. Never use placeholders such as [Your Name] or [Company].")


def order_was_found(policy_output) -> bool:
    """Routing condition for Agent 3. CrewAI passes it Agent 2's output (the PolicyAssessment).
    Rule R0 means the policy service could not find the order, so there is nothing to resolve yet."""
    assessment = policy_output.pydantic
    return assessment is not None and assessment.rule_id != "R0"


def make_order_id_guardrail(customer_message: str):
    """Guardrail for Agent 1: the order ID must be one the customer actually wrote.

    If the LLM guessed or invented an order ID, the guardrail removes it (order not found, low
    confidence), so the case is routed to NEEDS_INFO instead of acting on someone else's order."""
    ids_in_message = {m.upper() for m in ORDER_ID_PATTERN.findall(customer_message)}

    def guardrail(output):
        # The guardrail can run before CrewAI converts the text to an IssueReport, so parse it here.
        report = output.pydantic
        if report is None:
            match = re.search(r"\{.*\}", output.raw or "", re.S)
            if not match:
                return False, "Return the IssueReport as a JSON object."
            try:
                report = IssueReport.model_validate_json(match.group(0))
            except ValidationError as e:
                return False, f"The IssueReport JSON is invalid: {e.errors()[:2]}"
        claimed = (report.order_id or "").strip().upper() or None
        if claimed and claimed not in ids_in_message:
            logger.warning(f"Guardrail: Agent 1 used order ID {claimed}, which is not in the message; removing it")
            report.order_id = None
            report.order_found = False
            report.customer_name = None
            report.confidence = min(report.confidence, 0.5)
            report.summary = "No valid order ID in the message. " + report.summary
        # Returning a JSON string makes CrewAI rebuild the IssueReport from the (possibly corrected) values
        return True, report.model_dump_json()

    return guardrail


def build_tasks(issue_agent, policy_agent, resolution_agent, escalation_agent, customer_message: str):
    identify_task = Task(
        description=(
            "A customer wrote to ShopKart support:\n\n"
            "\"\"\"{customer_message}\"\"\"\n\n"
            "1. Extract the order ID only if the customer wrote one (format ORD + 4 digits). Never guess or "
            "assume an order ID. If there is none, set order_id to null and do not call lookup_order.\n"
            "2. If there is an order ID, call lookup_order to fetch the real order details.\n"
            "3. Classify the issue as exactly one of: DAMAGED_PRODUCT, WRONG_ITEM, RETURN_REQUEST "
            "(change of mind, size or fit), DELAYED_DELIVERY, NOT_RECEIVED, REFUND_STATUS, OTHER.\n"
            "4. Flag safety_or_legal_concern if the customer mentions injury, fire, smoke, burning, "
            "electric shock or legal action.\n"
            "5. Give a confidence score. Use below 0.7 when the message is vague or could fit several issue types."
        ),
        expected_output="A JSON object with the actual values for order_id, order_found, customer_name, issue_type, "
                        "customer_request, sentiment, safety_or_legal_concern, confidence and summary. " + NOT_THE_SCHEMA,
        agent=issue_agent,
        output_pydantic=IssueReport,
        guardrail=make_order_id_guardrail(customer_message),
    )
    policy_task = Task(
        description=(
            "Using the IssueReport from the previous step, call check_refund_policy with its order_id and "
            "issue_type (use 'NONE' as the order_id if there is none). Report the result faithfully: "
            "eligibility, rule ID, allowed resolutions, maximum refund, conditions, whether an exception is "
            "possible and whether investigation is required. Then explain it in plain English."
        ),
        expected_output="A JSON object with the actual values for eligible, rule_id, allowed_resolutions, max_refund_inr, "
                        "conditions, exception_possible, investigation_required and explanation, copied from the "
                        "check_refund_policy result. " + NOT_THE_SCHEMA,
        agent=policy_agent,
        context=[identify_task],                                  # handoff: Agent 1 -> Agent 2
        output_pydantic=PolicyAssessment,
    )
    # Conditional routing: Agent 3 runs only when Agent 2 found a valid order.
    # If there is no order (policy rule R0), there is nothing to resolve yet, so the crew skips
    # straight to Agent 4, which asks the customer for their order ID (status NEEDS_INFO).
    resolution_task = ConditionalTask(
        condition=order_was_found,
        description=(
            "Customer message: \"\"\"{customer_message}\"\"\"\n\n"
            "Using the IssueReport and PolicyAssessment, choose ONE action from allowed_resolutions, "
            "preferring what the customer asked for when it is allowed. Rules:\n"
            "- refund_amount_inr must not exceed max_refund_inr (use 0 if no money is refunded now).\n"
            "- If not eligible, choose DENY and explain kindly why, mentioning any alternative.\n"
            "- If investigation_required is true, choose INVESTIGATE.\n"
            "- If exception_possible is true, propose the refund but say it is subject to approval.\n"
            "- For RETURN_AND_REFUND or EXCHANGE, explain that a pickup will be arranged and the refund or "
            "exchange follows pickup.\n"
            "- Mention any conditions (for example photo evidence).\n"
            "Address the customer by first name if known. " + REPLY_STYLE
        ),
        expected_output="A JSON object with the actual values for action, refund_amount_inr, customer_reply_draft "
                        "and internal_notes. " + NOT_THE_SCHEMA,
        agent=resolution_agent,
        context=[identify_task, policy_task],                     # handoff: Agents 1+2 -> Agent 3
        output_pydantic=ResolutionPlan,
    )
    escalation_task = Task(
        description=(
            "Customer message: \"\"\"{customer_message}\"\"\"\n\n"
            "Step 1. Call run_escalation_rules once with: the order_id and issue_type from the IssueReport "
            "('NONE' if there is no order ID), the refund_amount_inr from the ResolutionPlan (0 if there is no "
            "ResolutionPlan), the confidence from the IssueReport, and the customer's original message above, "
            "copied word for word.\n"
            "Step 2. Copy escalate, priority, triggered_rules, route_to and final_status from that result exactly.\n"
            "Step 3. Write final_customer_message:\n"
            "- If there is no ResolutionPlan (no valid order was found): apologise and ask for the order ID "
            "(format ORD followed by 4 digits) and a short description of the problem.\n"
            "- If NOT escalated: use the ResolutionPlan's customer_reply_draft (light edits only).\n"
            "- If escalated: do NOT promise the refund or outcome. Acknowledge the issue and say a specialist "
            "team will review it within the SLA from the escalation result. For safety issues, tell the "
            "customer to stop using the product immediately.\n"
            "Do not mention ticket numbers or say that a refund has already been processed: the system adds "
            "those details after your decision. " + REPLY_STYLE
        ),
        expected_output="A JSON object with the actual values for escalate, priority, triggered_rules, route_to, "
                        "final_status, final_customer_message and justification, matching the "
                        "run_escalation_rules result. " + NOT_THE_SCHEMA,
        agent=escalation_agent,
        context=[identify_task, policy_task, resolution_task],    # handoff: Agents 1-3 -> Agent 4
        output_pydantic=EscalationDecision,
    )
    return identify_task, policy_task, resolution_task, escalation_task


# ---------------------------------------------------------------------------
# The action step: plain code, so every case gets exactly one correct action
# ---------------------------------------------------------------------------
def _call(all_tools, name: str, **args) -> dict:
    result = json.loads(tool_by_name(name, all_tools).run(**args))
    _current_tool_calls.append({"agent": "Workflow (code)", "name": name, "args": args, "output": str(result)[:600]})
    return result


def execute_action(all_tools, customer_message, issue, policy, plan, decision) -> dict:
    """Re-check the escalation rules, correct Agent 4 if it miscopied them, then take ONE action."""
    order_id = issue.order_id or "NONE"
    proposed_refund = plan.refund_amount_inr if plan else 0
    rules = _call(all_tools, "run_escalation_rules", order_id=order_id, issue_type=issue.issue_type,
                  refund_amount_inr=proposed_refund, confidence=issue.confidence,
                  customer_message=customer_message)

    corrected = (rules["final_status"] != decision.final_status or rules["priority"] != decision.priority)
    if corrected:
        logger.warning(f"Agent 4 reported {decision.final_status}/{decision.priority}; "
                       f"rules say {rules['final_status']}/{rules['priority']}. Using the rules.")

    action = {"status": rules["final_status"], "priority": rules["priority"], "route_to": rules["route_to"],
              "escalate": rules["escalate"], "triggered_rules": rules["triggered_rules"],
              "ticket_ref": None, "refund_issued_inr": 0.0, "action_taken": "NONE",
              "corrected_agent_decision": corrected, "note": ""}

    if rules["escalate"]:
        ticket = _call(all_tools, "create_escalation_ticket", order_id=order_id, priority=rules["priority"],
                       triggered_rules=rules["triggered_rules"], summary=issue.summary,
                       customer_message=customer_message)
        action.update(action_taken="TICKET", ticket_ref=ticket.get("ticket_ref"))
        action["note"] = (f"Your reference number is {ticket.get('ticket_ref')}. Our {ticket.get('team')} "
                          f"will get back to you within {ticket.get('sla')}.")
    elif rules["final_status"] == "AUTO_RESOLVED" and plan and plan.action in REFUND_ACTIONS:
        amount = min(plan.refund_amount_inr, policy.max_refund_inr)     # never above the policy maximum
        if amount > 0:
            refund = _call(all_tools, "issue_refund", order_id=order_id, amount_inr=amount, reason=plan.action)
            if not refund.get("error"):
                action.update(action_taken="REFUND", refund_issued_inr=amount)
                action["note"] = (f"A refund of Rs {amount:,.0f} has been initiated to your original payment "
                                  f"method ({refund.get('refund_status', 'processing')}).")
            else:
                action.update(action_taken="REFUND_FAILED")
                logger.error(f"Refund failed for {order_id}: {refund}")
    return action


def _clean_reply(text: str) -> str:
    """Remove template placeholders such as [Your Name] that the LLM sometimes leaves in."""
    return re.sub(r"\[(your name|name|agent name|company|company name)\]", SIGN_OFF, text, flags=re.IGNORECASE)


# ---------------------------------------------------------------------------
# Run one customer message through the crew
# ---------------------------------------------------------------------------
AGENT_LABELS = ["1. Order Issue Identification", "2. Policy Interpretation",
                "3. Resolution Recommendation", "4. Escalation"]


MAX_ATTEMPTS = 2   # retry once if the LLM returns output that doesn't fit a handoff format


def _is_format_error(e: Exception) -> bool:
    """True if the error (or anything it wraps) is a Pydantic validation error."""
    while e is not None:
        if isinstance(e, ValidationError) or "validation error" in str(e):
            return True
        e = e.__cause__ or e.__context__
    return False


def _kickoff_once(customer_message: str, verbose: bool):
    with connect_mcp() as all_tools:
        policy_text = json.loads(tool_by_name("get_refund_policy", all_tools).run())["policy_text"]
        agents = build_agents(all_tools, policy_text)
        tasks = build_tasks(*agents, customer_message=customer_message)
        crew = Crew(agents=list(agents), tasks=list(tasks), process=Process.sequential, verbose=verbose)
        result = crew.kickoff(inputs={"customer_message": customer_message})
        crewai_event_bus.flush()
        outputs = [t.pydantic for t in result.tasks_output]
        action = execute_action(all_tools, customer_message, *outputs)
    return outputs, action


def run_crew(customer_message: str, verbose: bool = False) -> dict:
    global _current_tool_calls
    with _run_lock:
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                _current_tool_calls = []
                try:
                    outputs, action = _kickoff_once(customer_message, verbose)
                    break
                except Exception as e:
                    if not _is_format_error(e) or attempt == MAX_ATTEMPTS:
                        raise
                    logger.warning(f"Attempt {attempt}: an agent's output did not match its handoff format; retrying")
            tool_calls = list(_current_tool_calls)
        finally:
            _current_tool_calls = None

    issue, policy, plan, decision = outputs   # plan is None when Agent 3 was skipped by the routing rule
    agent_trace = []
    for label, out in zip(AGENT_LABELS, outputs):
        if out is None:
            agent_trace.append({"agent": label, "skipped": True,
                                "output": {"skipped": "No valid order found, so there was nothing to resolve; "
                                                      "routed straight to Escalation to ask for the order ID."}})
        else:
            agent_trace.append({"agent": label, "skipped": False, "output": out.model_dump()})
    agent_trace.append({"agent": "5. Action (code)", "skipped": False, "output": action})

    reply = _clean_reply(decision.final_customer_message)
    if action["note"]:
        reply = f"{reply}\n\n{action['note']}"
    return {
        "response": reply,
        "final_status": action["status"],
        "escalate": action["escalate"],
        "priority": action["priority"],
        "route_to": action["route_to"],
        "ticket_ref": action["ticket_ref"],
        "refund_issued_inr": action["refund_issued_inr"],
        "action_taken": action["action_taken"],
        "route": " → ".join(step["agent"].split(". ", 1)[1] for step in agent_trace[:4] if not step["skipped"]),
        "agent_trace": agent_trace,
        "tool_calls": tool_calls,
    }
