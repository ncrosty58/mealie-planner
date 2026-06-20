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

EXPOSE 9926

CMD ["python", "-u", "app.py"]
