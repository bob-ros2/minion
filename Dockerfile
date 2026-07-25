FROM python:3-slim

# Install cron, gosu and other useful tools
RUN apt-get update -qq && apt-get install -y -qq \
    cron \
    gosu \
    procps \
    curl \
    git \
    iputils-ping \
    iproute2 \
    dnsutils \
    nano \
    vim-tiny \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root user (default UID/GID 1000)
RUN groupadd -g 1000 minion && \
    useradd -u 1000 -g minion -m -s /bin/bash minion

WORKDIR /app

# Copy project files and install Python dependencies + minion package
COPY requirements.txt pyproject.toml README.md /app/
COPY minion.py prepare_chat_session.py evolve.sh entrypoint.sh chat_minion.sh /app/

RUN pip install --no-cache-dir -r /app/requirements.txt && \
    pip install --no-cache-dir . && \
    rm -rf /app/build /app/*.egg-info

RUN chmod +x /app/evolve.sh /app/entrypoint.sh /app/chat_minion.sh

# Ensure cron log file exists and is writable
RUN touch /var/log/evolve.log && chown minion:minion /var/log/evolve.log

# Default: start entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

