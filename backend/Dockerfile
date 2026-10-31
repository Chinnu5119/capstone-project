FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-cloud.txt ./
# Cloud SDKs are installed so switching a provider to MODE=live needs no rebuild.
RUN pip install --no-cache-dir -r requirements.txt -r requirements-cloud.txt
COPY app ./app
RUN useradd -r -u 10001 appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status==200 else 1)"
# One worker on purpose: the scheduler runs inside the process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
