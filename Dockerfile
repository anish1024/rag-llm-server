FROM python:3.12-slim
WORKDIR /app
COPY agent_api.py .
RUN pip install --no-cache-dir fastapi==0.115.0 uvicorn[standard]==0.32.0 requests==2.32.3 pydantic==2.9.2
EXPOSE 8000
CMD ["uvicorn", "agent_api:app", "--host", "0.0.0.0", "--port", "8000"]
