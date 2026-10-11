FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app
RUN mkdir -p /defaults /app

# Dependencies
COPY requirements.txt /defaults/requirements.txt
RUN pip install --no-cache-dir -r /defaults/requirements.txt

# Copy application files into defaults
COPY . /defaults/

RUN chmod +x /defaults/entrypoint.sh

ENTRYPOINT ["/defaults/entrypoint.sh"]