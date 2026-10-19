FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
RUN uv pip install --system "mcp==1.28.1" uvicorn==0.53.0 requests==2.34.2 starlette httpx
COPY mcp_server /app/mcp_server
EXPOSE 8003
CMD ["uvicorn", "mcp_server.server:app", "--host", "0.0.0.0", "--port", "8003"]
