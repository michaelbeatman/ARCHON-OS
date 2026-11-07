FROM python:3.11-slim

WORKDIR /app

# Basis-Tools installieren (Git für In-App Update-System, Curl)
# Docker CLI für isolierte Sandbox-Ausführung
RUN apt-get update && apt-get install -y --no-install-recommends git curl docker.io && \
    rm -rf /var/lib/apt/lists/*

# Non-Root-User und -Gruppe anlegen
RUN groupadd -g 1000 streamlitgroup && \
    useradd -u 1000 -g streamlitgroup -m -s /bin/bash streamlituser

# Datenverzeichnis für persistente Volumes anlegen und berechtigen
RUN mkdir -p /app/data /app/agent_workspace && \
    chown -R streamlituser:streamlitgroup /app

# Abhängigkeiten kopieren und installieren
COPY --chown=streamlituser:streamlitgroup requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Anwendungsdateien kopieren
COPY --chown=streamlituser:streamlitgroup main.py .
COPY --chown=streamlituser:streamlitgroup core_*.py .
COPY --chown=streamlituser:streamlitgroup views_core.py .
COPY --chown=streamlituser:streamlitgroup static/ static/
COPY --chown=streamlituser:streamlitgroup agents.json /app/agent_workspace/agents.json
COPY --chown=streamlituser:streamlitgroup agents.json /app/data/agents.json

# Umgebungsvariablen setzen
ENV PYTHONUNBUFFERED=1

# Persistente Datenverzeichnisse als Volumes deklarieren
VOLUME ["/app/data", "/app/agent_workspace"]

# Zu Non-Root-User wechseln
USER streamlituser

EXPOSE 8501

# Anwendung starten
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8501"]
