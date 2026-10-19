FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
RUN uv pip install --system fastapi==0.143.3 uvicorn==0.53.0 pydantic==2.12.5 requests==2.34.2
COPY mock_services /app/mock_services
EXPOSE 8002
CMD ["uvicorn", "mock_services.policy_service.main:app", "--host", "0.0.0.0", "--port", "8002"]
