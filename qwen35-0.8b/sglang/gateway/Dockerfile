FROM python:3.11-slim

# Install uv
RUN pip install uv

WORKDIR /app

# Copying only needed files first for better caching
COPY main.py .

# Install dependencies using uv
RUN uv pip install --system fastapi uvicorn httpx orjson

# Run server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
