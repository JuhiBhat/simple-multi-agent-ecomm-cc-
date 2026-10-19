FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
RUN uv pip install --system streamlit==1.66.0 requests==2.34.2 pandas==3.0.5
COPY frontend /app
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
