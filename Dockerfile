FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p static/uploads/evidences static/uploads/linked_docs

EXPOSE 8001

CMD ["sh", "-c", "python startup.py && uvicorn app:app --host 0.0.0.0 --port ${PORT:-8001}"]
