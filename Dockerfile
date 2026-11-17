FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY content-schema ./content-schema
COPY frontend ./frontend
COPY docs/examples ./docs/examples
COPY fixtures ./fixtures
# Pre-create the storage mountpoint so an empty named volume inherits leetmath ownership
# (otherwise Docker creates /app/var/objects as root and store_bytes() fails at seed time).
RUN useradd -m -u 10001 leetmath && mkdir -p /app/var/objects && chown -R leetmath /app/var
USER leetmath
EXPOSE 8000
# migrate → idempotent demo seed → serve
CMD ["sh", "-c", "python -m leetmath.cli migrate && python -m leetmath.cli seed && uvicorn leetmath.app:create_app --factory --host 0.0.0.0 --port 8000"]
