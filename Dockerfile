FROM python:3.11-slim

ARG TARGETARCH
WORKDIR /app

# Base CLI tools + Multi-Arch static Docker CLI (amd64 & arm64 / Apple Silicon)
# Debian 13 (trixie) ships no docker CLI binary in docker.io, so fetch static CLI for isolated sandboxes.
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates && \
    case "${TARGETARCH:-amd64}" in \
      arm64|aarch64) DOCKER_ARCH="aarch64" ;; \
      *) DOCKER_ARCH="x86_64" ;; \
    esac && \
    curl -fsSL "https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-27.3.1.tgz" \
      | tar -xz --strip-components=1 -C /usr/local/bin docker/docker && \
    chmod +x /usr/local/bin/docker && \
    rm -rf /var/lib/apt/lists/*

# Non-root runtime user & group
RUN groupadd -g 1000 streamlitgroup && \
    useradd -u 1000 -g streamlitgroup -m -s /bin/bash streamlituser

# Persistent runtime directories
RUN mkdir -p /app/data /app/data/inbox /app/agent_workspace /app/agent_workspace/builds /app/obsidian_vault /app/.hermes/profiles && \
    chown -R streamlituser:streamlitgroup /app

# Python dependencies
COPY --chown=streamlituser:streamlitgroup requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Complete application code & static assets (runs standalone even without bind-mount)
COPY --chown=streamlituser:streamlitgroup *.py ./
COPY --chown=streamlituser:streamlitgroup agent_profiles.json agents.json roles.json settings.json prompt_studio_catalog.json hermes_skills_index.json hermes_skills_cache.json ./
COPY --chown=streamlituser:streamlitgroup archon/ archon/
COPY --chown=streamlituser:streamlitgroup backend/ backend/
COPY --chown=streamlituser:streamlitgroup utils/ utils/
COPY --chown=streamlituser:streamlitgroup plugins/ plugins/
COPY --chown=streamlituser:streamlitgroup config/ config/
COPY --chown=streamlituser:streamlitgroup scripts/ scripts/
COPY --chown=streamlituser:streamlitgroup static/ static/
COPY --chown=streamlituser:streamlitgroup templates/ templates/
COPY --chown=streamlituser:streamlitgroup tools/ tools/
COPY --chown=streamlituser:streamlitgroup views/ views/
RUN cp /app/agents.json /app/agent_workspace/agents.json && \
    cp /app/agents.json /app/data/agents.json && \
    chown -R streamlituser:streamlitgroup /app/agent_workspace /app/data

ENV PYTHONUNBUFFERED=1

VOLUME ["/app/data", "/app/agent_workspace"]

USER streamlituser

EXPOSE 8501

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8501"]
