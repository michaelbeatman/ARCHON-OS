FROM python:3.11-slim

WORKDIR /app

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
COPY --chown=streamlituser:streamlitgroup GUARDRAIL.md .
COPY --chown=streamlituser:streamlitgroup manifests/ manifests/
COPY --chown=streamlituser:streamlitgroup static/ static/

# Umgebungsvariablen setzen
ENV PYTHONUNBUFFERED=1

# Persistente Datenverzeichnisse als Volumes deklarieren
VOLUME ["/app/data", "/app/agent_workspace"]

# Zu Non-Root-User wechseln
USER streamlituser

EXPOSE 8501

# Anwendung starten
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8501"]
