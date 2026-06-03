FROM python:3.12-alpine

LABEL org.opencontainers.image.source="https://github.com/ncrosty58/mealie-planner"
LABEL org.opencontainers.image.description="An intelligent AI companion planner, shopping list syncer, and email notifier for Mealie"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9926

CMD ["python", "-u", "app.py"]
