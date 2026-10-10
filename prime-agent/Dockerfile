# Prime Agent - Docker Image
# Self-improving RLM agent (https://github.com/PrimeIntellect-ai/prime-agent)
# Build:  docker build -f prime-agent/Dockerfile -t prime-agent:latest .
# Run:    siehe docker-compose.prime-agent.yml (Service: prime-agent)
#
# HINWEIS: Das Paket ist NICHT auf dem npm-Registry! Offizieller Weg ist der
# Installer, der ein versioniertes Tarball von Cloudflare R2 laedt. Wir machen
# genau das hier nach (mit fester Version fuer reproduzierbare Builds).

ARG PRIME_AGENT_VERSION=0.7.1

FROM node:22-bookworm-slim AS base

# Python fuer die IPython-Runtime des Agents + ttyd Web-Terminal Server
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        git \
        curl \
        ca-certificates \
    && curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64" -o /usr/local/bin/ttyd \
    && chmod +x /usr/local/bin/ttyd \
    && rm -rf /var/lib/apt/lists/* \
    && python3 --version \
    && ttyd --version

# uv fuer den IPython-Runtime-Bootstrap
RUN pip3 install --no-cache-dir uv --break-system-packages

# Prime Agent aus dem offiziellen Release-Tarball installieren
ARG PRIME_AGENT_VERSION
RUN curl -fsSL "https://pub-728493de92a943e2a9b2d17b4719f318.r2.dev/releases/v${PRIME_AGENT_VERSION}/prime-agent-${PRIME_AGENT_VERSION}.tgz" -o /tmp/prime-agent.tgz \
    && npm install -g --no-fund --no-audit --loglevel=error /tmp/prime-agent.tgz \
    && rm /tmp/prime-agent.tgz \
    && prime-agent --version

# Start-Skript mit automatischem Bereinigen verwaister Sockets
COPY prime-agent/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Arbeitsverzeichnis (wird per Volume gemountet)
WORKDIR /workspace

EXPOSE 7681

# Web-Terminal starten
ENTRYPOINT ["/entrypoint.sh"]
CMD []

