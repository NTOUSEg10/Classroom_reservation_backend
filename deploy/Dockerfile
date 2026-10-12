FROM python:3.12.10-slim
WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir pip==26.2.1 && python -m pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY notification_worker ./notification_worker
RUN useradd --create-home --uid 10001 classroom
USER classroom
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "172.28.0.2", "--no-access-log"]
