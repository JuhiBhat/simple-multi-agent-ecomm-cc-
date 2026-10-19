# ShopKart AI Customer Care Crew

A goal-oriented, multi-agent e-commerce support system for **order, refund & exception handling**, built with
**CrewAI**, **FastAPI**, **FastMCP** and **Streamlit**. Four collaborating agents classify the customer's issue,
apply the refund policy, recommend a resolution and decide whether a human must approve it. The agents run
inside a microservices architecture and reach the business services only through an MCP server.

*Week 12 Graded Mini Project, Use Case 2: E-Commerce Order, Refund & Exception Handling.*

## Features
- **4-agent CrewAI workflow** with structured handoffs (Issue Identification → Policy Interpretation → Resolution Recommendation → Escalation)
- **Deterministic policy engine** (rules R1–R9: damage windows, return windows, non-returnable items, delay compensation, Gold goodwill exceptions)
- **Explicit escalation rules** with priorities P1–P4 (safety, legal, fraud, high value, policy exception, low confidence)
- **Human review queue**: escalated cases become tickets routed to the right team, with an SLA
- **Automatic refunds** for eligible low-value cases, with a hard ₹10,000 limit enforced by the order service
- **Follow-up handling**: a vague message gets *needs info*; the next message with the order ID completes the case
- **Transparent UI**: every reply shows what each agent handed to the next, and every MCP tool call

## Prerequisites
- Docker Desktop (running)
- An OpenAI API key (the course's Vocareum key works) or a local Ollama instance

## Setup & Deployment

1. **Environment variables:** copy `.env.example` to `.env` and add your key. (`deploy.sh` and `deploy.ps1` create `.env` from the example if it is missing.)
   ```env
   MODEL_TYPE=openai
   OPENAI_API_KEY=your-key-here
   OPENAI_MODEL=gpt-4o-mini
   OPENAI_BASE_URL=https://openai.vocareum.com/v1
   ```
   - **Vocareum course key:** keep `OPENAI_BASE_URL` as shown (this is what the class Zomato project uses).
   - **Personal key from platform.openai.com:** delete the `OPENAI_BASE_URL` line.

2. **Deploy the microservices.** The first build takes about 5 minutes.

   **Linux / macOS:**
   ```bash
   chmod +x deploy.sh
   ./deploy.sh
   ```
   **Windows (PowerShell):**
   ```powershell
   .\deploy.ps1
   ```
   Or manually: `docker compose up --build -d`

3. **Managing the deployment:**
   - View logs of all services: `docker compose logs -f`
   - View one service: `docker compose logs -f agent`
   - Stop everything: `docker compose down`

4. **Access the application:**
   - **Frontend (Chat UI):** http://localhost:8501
   - **Agent API (Swagger):** http://localhost:8000/docs
   - **MCP Server (health):** http://localhost:8003/health (SSE stream at `http://localhost:8003/sse`)
   - **Order Service API:** http://localhost:8001/docs
   - **Policy Service API:** http://localhost:8002/docs
   - **Escalation Service API:** http://localhost:8004/docs

## Seeded Mock Data

"Today" is fixed at **17 Oct 2026** (`REFERENCE_DATE`) so the date-based rules always give the same results.

| Order | Customer | Item | ₹ | Status | Designed to test |
|---|---|---|---|---|---|
| ORD1001 | Rahul (Silver) | Wireless Headphones | 2,499 | Delivered 3 days ago | Damaged → auto refund |
| ORD1002 | Anita | Cotton Kurta | 1,299 | Delivered 12 days ago | Return within 30-day window |
| ORD1003 | Vikram | Smart Watch | 3,999 | In transit, 5 days late | Delay compensation |
| ORD1004 | Sneha (Gold) | 14-inch Laptop | 62,000 | Delivered 2 days ago | High-value → escalate |
| ORD1005 | Arjun (3 claims) | Smartphone | 18,999 | Marked delivered | Not received + fraud history |
| ORD1006 | Meera | Power Bank | 1,499 | Delivered | Safety hazard → P1 |
| ORD1007 | Karan | Fruit Basket | 850 | Delivered yesterday | Non-returnable → deny |
| ORD1008 | Pooja (Gold) | Running Shoes | 4,599 | Delivered 32 days ago | Gold goodwill exception |
| ORD1009 | Imran | Data Science Handbook | 899 | Delivered | Wrong item + legal threat |

## Testing the Application

1. Open http://localhost:8501.
2. Click a sample in the sidebar, or type your own message with an order ID.
3. Each reply shows a status badge. Open **🧠 Agent handoffs** to see what each agent passed on, and
   **🛠️ Tool calls via MCP** to see which tools were used.
4. Open the **🚨 Escalation queue** tab to see the tickets created for human review.
5. Try a follow-up: send *"my thing came and its not right"* (needs info), then *"it's ORD1001, the headphones don't work"*.

**Automated test of all 10 sample cases** (with the stack running):
```bash
pip install requests
python tests/run_samples.py
```
This prints an escalation scorecard (accuracy, false positives, false negatives) and saves
`outputs/results.csv` and `outputs/sample_outputs.md` for your write-up.

## Project Structure
- `agent/`: The CrewAI orchestrator microservice (port 8000). Defines the 4 agents and their tasks (`crew.py`), the handoff formats (`schemas.py`), the LLM config (`llm.py`) and sessions (`session_manager.py`). Loads its tools from the MCP server (`tools.py`) and gives each agent only the tools it needs.
- `mcp_server/`: Model Context Protocol (FastMCP) microservice (port 8003). Hosts all agent tools and is the single point of contact with the downstream services.
- `mock_services/`
  - `data/`: SQLite schema (`models.py`) and seeding script (`database.py`).
  - `order_service/`: orders, customers and refund execution (port 8001).
  - `policy_service/`: the refund policy as text and as executable rules R1–R9 (port 8002).
  - `escalation_service/`: escalation rules and the human review ticket queue (port 8004).
- `frontend/`: Streamlit chat UI (port 8501).
- `tests/run_samples.py`: runs the 10 sample cases against the API and scores them.
- `notebook/ecommerce_crew.ipynb`: standalone, step-by-step version of the same crew (no Docker), for learning or for Vocareum.
- `docker-compose.yml`: binds the 6 services together over a shared Docker network.
- `deploy.sh` / `deploy.ps1`: build and deployment scripts.

## Troubleshooting

| Problem | Fix |
|---|---|
| Chat shows *Agent error ... AuthenticationError* | Wrong key, or a mismatch: Vocareum key needs `OPENAI_BASE_URL=https://openai.vocareum.com/v1`; a personal key needs that line removed. Then run `docker compose up -d --force-recreate agent` |
| *Failed to reach the agent service* | The agent container is still starting or crashed: `docker compose logs agent` |
| Changed `.env` but nothing changed | Containers read `.env` at start: `docker compose up -d --force-recreate agent` |
| Port already in use | Another app uses 8000–8004 or 8501. Stop it, or change the left-hand port in `docker-compose.yml` |
| Want to reset the data | `docker compose down` then `./deploy.sh` (each fresh container reseeds its database) |
| A case returns a wrong status | Look at the agent handoffs in the UI to see which agent went wrong, then refine that agent's task description in `agent/crew.py` |
