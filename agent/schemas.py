"""Handoff formats: the exact structured data each agent passes to the next.

Using typed Pydantic models (instead of free text) means the next agent never has to guess what
the previous one meant, and `Literal[...]` stops the LLM from inventing new categories.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

IssueType = Literal["DAMAGED_PRODUCT", "WRONG_ITEM", "RETURN_REQUEST", "DELAYED_DELIVERY",
                    "NOT_RECEIVED", "REFUND_STATUS", "OTHER"]


# Agent 1 (Order Issue Identification) -> Agent 2
class IssueReport(BaseModel):
    order_id: Optional[str] = Field(description="Order ID from the message, e.g. ORD1001, or null if none was given")
    order_found: bool = Field(description="True only if lookup_order found the order")
    customer_name: Optional[str] = Field(default=None, description="Customer's name from the order, if found")
    issue_type: IssueType
    customer_request: Literal["REFUND", "REPLACEMENT", "RETURN", "EXCHANGE", "CANCEL", "INFORMATION", "UNCLEAR"]
    sentiment: Literal["CALM", "FRUSTRATED", "ANGRY"]
    safety_or_legal_concern: bool = Field(description="True if the message mentions injury, fire, smoke, or legal action")
    confidence: float = Field(ge=0, le=1, description="How sure you are about issue_type (0 to 1)")
    summary: str = Field(description="One or two sentences: what happened and what the customer wants")


# Agent 2 (Policy Interpretation) -> Agent 3
class PolicyAssessment(BaseModel):
    eligible: bool
    rule_id: str = Field(description="Policy rule applied, e.g. R1")
    allowed_resolutions: List[str]
    max_refund_inr: float
    conditions: List[str]
    exception_possible: bool
    investigation_required: bool
    explanation: str = Field(description="Plain-English explanation of why the policy gives this result")


# Agent 3 (Resolution Recommendation) -> Agent 4
class ResolutionPlan(BaseModel):
    action: Literal["FULL_REFUND", "REPLACEMENT", "RETURN_AND_REFUND", "EXCHANGE", "COMPENSATION",
                    "CANCEL_AND_REFUND", "INVESTIGATE", "INFORM", "REQUEST_INFO", "DENY"]
    refund_amount_inr: float = Field(description="Refund being proposed, never above max_refund_inr; 0 if none")
    customer_reply_draft: str = Field(description="Polite reply to the customer, 60-120 words")
    internal_notes: str = Field(description="Short note for the support team")


# Agent 4 (Escalation) -> final output
class EscalationDecision(BaseModel):
    escalate: bool
    priority: Literal["P1", "P2", "P3", "P4", "NONE"]
    triggered_rules: List[str]
    route_to: str
    final_status: Literal["AUTO_RESOLVED", "ESCALATED", "DENIED", "NEEDS_INFO"]
    final_customer_message: str = Field(description="The message actually sent to the customer")
    justification: str = Field(description="One or two sentences explaining the decision")
