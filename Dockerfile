FROM python:3-slim

# Install cron
RUN apt-get update -qq && apt-get install -y -qq cron && rm -rf /var/lib/apt/lists/*

# Install the one Python dependency
RUN pip install --no-cache-dir openai

WORKDIR /app

# Ship a default minion.py in the image (will be overridden by
# the host mount at runtime, but serves as fallback)
COPY minion.py /app/minion.py
COPY evolve.sh /app/evolve.sh
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/evolve.sh /app/entrypoint.sh

# Ensure cron log file exists
RUN touch /var/log/evolve.log

# Default: start cron and keep container alive
ENTRYPOINT ["/app/entrypoint.sh"]
