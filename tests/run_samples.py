"""Send the 10 sample customer messages to the running Agent API and score the escalation decisions.

Run (with the stack running):   python tests/run_samples.py
Writes outputs/results.csv and outputs/sample_outputs.md for your architecture write-up.

False positive = escalated when it should not have been (wastes human time)
False negative = not escalated when it should have been (risky: money, fraud or safety)
"""
import csv
import json
import os
import sys
import uuid

import requests

AGENT_URL = os.getenv("AGENT_URL", "http://localhost:8000")

SAMPLE_CASES = [
    ("C01", "Hi, my order ORD1001 arrived 3 days ago but the left earcup of the headphones doesn't work. I'd like a refund.", "AUTO_RESOLVED"),
    ("C02", "The kurta from order ORD1002 is too tight. Can I return it?", "AUTO_RESOLVED"),
    ("C03", "Where is my smart watch? Order ORD1003 was supposed to arrive on 12 October and it's still not here!", "AUTO_RESOLVED"),
    ("C04", "My new laptop (ORD1004) arrived with a cracked screen. I want my money back.", "ESCALATED"),
    ("C05", "Order ORD1005 says delivered but I never got the phone. Refund me now.", "ESCALATED"),
    ("C06", "The power bank from ORD1006 started smoking while charging and burned my hand. This is dangerous.", "ESCALATED"),
    ("C07", "I ordered a fruit basket (ORD1007) but I've changed my mind. Please take it back and refund me.", "DENIED"),
    ("C08", "I'm a Gold member. The running shoes from ORD1008 don't fit. I know it's been a month but can you still accept a return?", "ESCALATED"),
    ("C09", "You sent me the wrong book for ORD1009! This is the third time something's gone wrong. Fix it or I'm going to consumer court.", "ESCALATED"),
    ("C10", "my thing came and its not right, do something", "NEEDS_INFO"),
]


def main():
    try:
        requests.get(f"{AGENT_URL}/health", timeout=5).raise_for_status()
    except Exception:
        sys.exit(f"Agent API not reachable at {AGENT_URL}. Start the stack first (./deploy.sh or .\\deploy.ps1).")

    rows, details = [], []
    for case_id, message, expected in SAMPLE_CASES:
        print(f"{case_id} ... ", end="", flush=True)
        try:
            # a fresh session per case so cases don't influence each other
            r = requests.post(f"{AGENT_URL}/api/chat", json={"session_id": str(uuid.uuid4()), "message": message}, timeout=300)
            r.raise_for_status()
            d = r.json()
        except Exception as e:
            print(f"ERROR {e}")
            rows.append({"case": case_id, "expected": expected, "status": "ERROR", "correct": False, "notes": str(e)})
            continue
        trace = {step["agent"]: step["output"] for step in d["agent_trace"]}
        issue = trace["1. Order Issue Identification"]
        policy = trace["2. Policy Interpretation"]
        plan = trace["3. Resolution Recommendation"]
        row = {
            "case": case_id, "expected": expected, "status": d["final_status"], "correct": d["final_status"] == expected,
            "issue_type": issue["issue_type"], "confidence": issue["confidence"], "policy_rule": policy["rule_id"],
            "action": plan.get("action", "SKIPPED"), "refund_proposed_inr": plan.get("refund_amount_inr", 0),
            "route": d.get("route", ""),
            "refund_issued_inr": d["refund_issued_inr"], "priority": d["priority"], "ticket": d["ticket_ref"] or "",
            "rules_fired": ", ".join(d["agent_trace"][-1]["output"]["triggered_rules"]),
            "action_taken": d.get("action_taken", ""),
            "tools": " > ".join(t["name"] for t in d["tool_calls"]),
        }
        rows.append(row)
        details.append((case_id, message, d))
        print(f"{d['final_status']:13} {d['priority']:4} {'OK' if row['correct'] else 'MISMATCH (expected ' + expected + ')'}")

    should = [r["expected"] == "ESCALATED" for r in rows]
    did = [r["status"] == "ESCALATED" for r in rows]
    fp = [r["case"] for r, s, x in zip(rows, should, did) if x and not s]
    fn = [r["case"] for r, s, x in zip(rows, should, did) if s and not x]
    correct = sum(r["correct"] for r in rows)
    print("\n=== Escalation scorecard ===")
    print(f"Overall accuracy           : {correct}/{len(rows)}")
    print(f"Correct escalations        : {sum(s and x for s, x in zip(should, did))}/{sum(should)}")
    print(f"False positives (over-esc.): {len(fp)} {fp}")
    print(f"False negatives (missed)   : {len(fn)} {fn}")

    os.makedirs("outputs", exist_ok=True)
    fields = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0]).index(k) if k in rows[0] else 99)
    with open("outputs/results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with open("outputs/sample_outputs.md", "w", encoding="utf-8") as f:
        f.write(f"# Sample outputs\n\nAccuracy {correct}/{len(rows)} | false positives {fp} | false negatives {fn}\n\n")
        for case_id, message, d in details:
            f.write(f"## {case_id}: {d['final_status']} {d['priority']}\n\n**Customer:** {message}\n\n"
                    f"**Reply:** {d['response']}\n\n**Tool calls:** {' > '.join(t['name'] for t in d['tool_calls'])}\n\n"
                    f"<details><summary>Agent handoffs</summary>\n\n```json\n{json.dumps(d['agent_trace'], indent=2)}\n```\n</details>\n\n")
    print("\nSaved outputs/results.csv and outputs/sample_outputs.md")


if __name__ == "__main__":
    main()
