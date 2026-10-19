FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
RUN uv pip install --system crewai==1.15.28 "crewai-tools[mcp]==1.15.28" "mcp==1.28.1" fastapi==0.143.3 uvicorn==0.53.0
# The agent never touches the database: it only talks to the MCP server
COPY agent /app/agent
ENV CREWAI_DISABLE_TELEMETRY=true OTEL_SDK_DISABLED=true
EXPOSE 8000
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
