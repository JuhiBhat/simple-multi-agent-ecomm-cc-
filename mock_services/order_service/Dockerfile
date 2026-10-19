FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
RUN uv pip install --system fastapi==0.143.3 uvicorn==0.53.0 pydantic==2.12.5 sqlalchemy==2.1.5
COPY mock_services /app/mock_services
EXPOSE 8001
CMD ["uvicorn", "mock_services.order_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
