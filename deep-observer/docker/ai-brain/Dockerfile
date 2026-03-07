FROM python:3.12-slim
WORKDIR /app
COPY ai-brain/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY ai-brain /app
COPY .env /app/.env
CMD ["python", "-m", "app.main"]
