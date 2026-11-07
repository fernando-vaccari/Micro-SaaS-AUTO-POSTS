FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/app/.data

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 autoposts \
    && useradd --uid 10001 --gid autoposts --no-create-home --shell /usr/sbin/nologin autoposts

WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=secret,id=build_ca,target=/run/secrets/build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then \
        PIP_CERT=/run/secrets/build_ca python -m pip install --no-cache-dir --requirement requirements.txt; \
    else \
        python -m pip install --no-cache-dir --requirement requirements.txt; \
    fi
COPY --chown=autoposts:autoposts autoposts ./autoposts
COPY --chown=autoposts:autoposts scripts ./scripts
RUN mkdir -p /app/.data && chown autoposts:autoposts /app/.data

USER autoposts
EXPOSE 8000
VOLUME ["/app/.data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import json, urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)); assert data.get('status') == 'ok' and data.get('database') == 'ok' and data.get('ffmpeg') is True"
CMD ["python", "-m", "uvicorn", "autoposts.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
