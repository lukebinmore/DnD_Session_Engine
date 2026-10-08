FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Install Google SDKs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Store fallback defaults inside the container image
RUN mkdir /defaults
COPY watcher.py doc_updater.py prompt.txt /defaults/

# Set up entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]