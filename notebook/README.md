# Standalone notebook version (no Docker)

`ecommerce_crew.ipynb` contains the same 4 agents, policy rules and escalation rules as the Docker
microservices version, all in one notebook with explanations before each step. Use it to learn how the
crew works, or to submit in Vocareum.

## Run it in VS Code
1. You need Python 3.10–3.13, plus the VS Code **Python** and **Jupyter** extensions.
2. In a terminal in the project folder (the one containing `.env`):
   - Windows: `python -m venv .venv` then `.venv\Scripts\Activate.ps1`
   - Mac/Linux: `python3 -m venv .venv` then `source .venv/bin/activate`
   - then: `pip install crewai==1.15.28 python-dotenv pandas ipykernel`
3. Open the notebook, click **Select Kernel → Python Environments → .venv**.
4. Run Step 0 (it should print a path ending in `.venv`), then run the remaining cells in order.

The notebook reads the same `.env` as the Docker version (`OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`).
Steps 1–6 need no API key; Steps 7–9 call the LLM.
