FROM python:3.12-alpine

LABEL org.opencontainers.image.source="https://github.com/ncrosty58/mealie-planner"
LABEL org.opencontainers.image.description="An intelligent AI companion planner, shopping list syncer, and email notifier for Mealie"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# If the Mealie MCP submodule is not checked out (e.g. cloned without submodules or zip downloaded),
# automatically download the correct submodule commit from GitHub and extract it.
RUN if [ ! -f mealie-mcp-server/src/mealie/__init__.py ]; then \
      echo "Submodule missing. Downloading from GitHub..." && \
      apk add --no-cache wget unzip && \
      wget -O /tmp/submodule.zip https://github.com/rldiao/mealie-mcp-server/archive/f7a2a5e21e68e223629393a5ad16f55dca6ea577.zip && \
      unzip /tmp/submodule.zip -d /tmp && \
      mkdir -p mealie-mcp-server && \
      cp -r /tmp/mealie-mcp-server-f7a2a5e21e68e223629393a5ad16f55dca6ea577/* mealie-mcp-server/ && \
      apk del wget unzip && \
      rm -rf /tmp/submodule.zip /tmp/mealie-mcp-server-f7a2a5e21e68e223629393a5ad16f55dca6ea577; \
    fi

# Run as a non-root user; uid 1000 matches the typical host owner of the
# bind-mounted ./data volume.
RUN addgroup -g 1000 -S app && adduser -u 1000 -S app -G app && \
    mkdir -p /app/data && chown -R app:app /app
USER app

EXPOSE 9926

# manifest.json is served without touching Mealie/AI, so it is a cheap liveness probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD wget -qO /dev/null http://127.0.0.1:9926/manifest.json || exit 1

# Single worker (the APScheduler email jobs and in-process caches assume one
# process); gthread keeps SSE streams and concurrent requests responsive.
CMD ["gunicorn", "--bind", "0.0.0.0:9926", "--workers", "1", "--threads", "8", \
     "--timeout", "300", "--access-logfile", "-", "app:app"]
