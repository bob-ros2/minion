FROM python:3-slim

# Install cron and other useful tools
RUN apt-get update -qq && apt-get install -y -qq \
    cron \
    procps \
    curl \
    git \
    iputils-ping \
    iproute2 \
    dnsutils \
    nano \
    vim-tiny \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

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

