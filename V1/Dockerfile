FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Force stdout/stderr flushing so logs appear immediately in Unraid
ENV PYTHONUNBUFFERED=1

CMD ["python", "watcher.py"]