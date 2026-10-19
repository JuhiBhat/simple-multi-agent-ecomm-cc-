"""ShopKart Customer Care: Streamlit chat UI (port 8501). Talks only to the Agent Service."""
import os
import uuid

import pandas as pd
import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="ShopKart Customer Care", page_icon="🛒", layout="wide")

STATUS_STYLE = {
    "AUTO_RESOLVED": ("✅", "#1e7f4f", "Auto-resolved"),
    "ESCALATED": ("🚨", "#b42318", "Escalated to a human"),
    "DENIED": ("⛔", "#5f6b7a", "Not eligible under policy"),
    "NEEDS_INFO": ("❓", "#b54708", "Needs more information"),
}

SAMPLES = {
    "Faulty headphones (auto refund)": "Hi, my order ORD1001 arrived 3 days ago but the left earcup of the headphones doesn't work. I'd like a refund.",
    "Kurta too tight (return)": "The kurta from order ORD1002 is too tight. Can I return it?",
    "Late smart watch (delay)": "Where is my smart watch? Order ORD1003 was supposed to arrive on 12 October and it's still not here!",
    "Cracked laptop (high value)": "My new laptop (ORD1004) arrived with a cracked screen. I want my money back.",
    "Phone not received (fraud check)": "Order ORD1005 says delivered but I never got the phone. Refund me now.",
    "Power bank smoking (safety)": "The power bank from ORD1006 started smoking while charging and burned my hand. This is dangerous.",
    "Fruit basket, changed mind": "I ordered a fruit basket (ORD1007) but I've changed my mind. Please take it back and refund me.",
    "Gold member, late return": "I'm a Gold member. The running shoes from ORD1008 don't fit. I know it's been a month but can you still accept a return?",
    "Wrong book + legal threat": "You sent me the wrong book for ORD1009! This is the third time something's gone wrong. Fix it or I'm going to consumer court.",
    "Vague message (no order ID)": "my thing came and its not right, do something",
}

st.markdown("""
<style>
  .status-pill {display:inline-block; padding:3px 10px; border-radius:999px; color:#fff;
                font-size:0.8rem; font-weight:600; margin-bottom:6px;}
  .meta {color:#6b7280; font-size:0.8rem;}
</style>
""", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "queued" not in st.session_state:
    st.session_state.queued = None


def render_assistant(msg: dict):
    data = msg.get("data")
    if not data:
        st.markdown(msg["content"])
        return
    icon, colour, label = STATUS_STYLE.get(data["final_status"], ("ℹ️", "#444", data["final_status"]))
    extra = ""
    if data.get("escalate"):
        extra = f" · {data['priority']} → {data['route_to']}" + (f" · ticket {data['ticket_ref']}" if data.get("ticket_ref") else "")
    elif data.get("refund_issued_inr"):
        extra = f" · refund ₹{data['refund_issued_inr']:,.0f} issued"
    st.markdown(f'<span class="status-pill" style="background:{colour}">{icon} {label}</span>'
                f'<span class="meta">{extra}</span>', unsafe_allow_html=True)
    st.markdown(msg["content"])
    with st.expander("🧠 Agent handoffs (what each agent passed to the next)"):
        if data.get("route"):
            st.caption(f"Route taken: {data['route']}")
        for step in data["agent_trace"]:
            if step.get("skipped"):
                st.markdown(f"**{step['agent']}** · ⏭️ *skipped by routing rule*")
                st.caption(step["output"]["skipped"])
            else:
                st.markdown(f"**{step['agent']}**")
                st.json(step["output"], expanded=False)
    with st.expander(f"🛠️ Tool calls via MCP ({len(data['tool_calls'])})"):
        for call in data["tool_calls"]:
            st.markdown(f"*{call['agent']}*")
            st.code(f"{call['name']}({call['args']})", language="python")


# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("🧪 Try a sample")
    for label, text in SAMPLES.items():
        if st.button(label, width="stretch"):
            st.session_state.queued = text

    st.divider()
    if st.button("🗑️ Clear chat", width="stretch"):
        try:
            requests.post(f"{BACKEND_URL}/api/clear_chat", json={"session_id": st.session_state.session_id}, timeout=10)
        except Exception as e:
            st.error(f"Failed to clear backend session: {e}")
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()

    with st.expander("📦 Mock orders"):
        try:
            orders = requests.get(f"{BACKEND_URL}/api/orders", timeout=30).json()["orders"]
            st.dataframe(pd.DataFrame(orders)[["order_id", "customer_name", "item", "price_inr", "status", "refund_status"]],
                         hide_index=True)
        except Exception as e:
            st.caption(f"Could not load orders: {e}")

# ---------------- Main area ----------------
st.title("🛒 ShopKart Customer Care")
st.caption("A CrewAI crew of 4 agents: Issue Identification → Policy Interpretation → "
           "Resolution Recommendation → Escalation. Tools are served by an MCP server.")

chat_tab, queue_tab = st.tabs(["💬 Chat", "🚨 Escalation queue"])

with chat_tab:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                render_assistant(msg)
            else:
                st.markdown(msg["content"])

    prompt = st.chat_input("Describe your order issue (include your order ID, e.g. ORD1001)...")
    if st.session_state.queued:
        prompt, st.session_state.queued = st.session_state.queued, None

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("4 agents are working on it (this takes 20-60 seconds)..."):
                try:
                    r = requests.post(f"{BACKEND_URL}/api/chat",
                                      json={"session_id": st.session_state.session_id, "message": prompt},
                                      timeout=300)
                    if r.status_code == 200:
                        data = r.json()
                        msg = {"role": "assistant", "content": data["response"], "data": data}
                    else:
                        msg = {"role": "assistant", "content": f"⚠️ Backend error: {r.text}"}
                except Exception as e:
                    msg = {"role": "assistant", "content": f"⚠️ Failed to reach the agent service: {e}"}
            render_assistant(msg)
        st.session_state.messages.append(msg)

with queue_tab:
    st.caption("Cases the Escalation Agent sent for human review, stored by the escalation service.")
    if st.button("🔄 Refresh queue"):
        st.rerun()
    try:
        tickets = requests.get(f"{BACKEND_URL}/api/tickets", timeout=30).json()["tickets"]
        if tickets:
            df = pd.DataFrame(tickets)
            df["triggered_rules"] = df["triggered_rules"].apply(", ".join)
            st.dataframe(df[["ticket_ref", "priority", "team", "order_id", "triggered_rules", "summary", "status", "created_at"]],
                         hide_index=True, width="stretch")
        else:
            st.info("No escalations yet. Try the 'Cracked laptop' or 'Power bank smoking' samples.")
    except Exception as e:
        st.warning(f"Could not load the queue: {e}")
