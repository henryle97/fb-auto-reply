FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SQLITE_PATH=/app/data/data.db

WORKDIR /app

# Copies the source, examples and, when present, your rules.yaml / product_info.md
# (secrets and local data are excluded by .dockerignore).
COPY . .
RUN pip install .

# Hugging Face Spaces runs the container as a non-root user (uid 1000).
RUN useradd --uid 1000 --create-home app && mkdir -p /app/data && chown app /app/data
USER app

EXPOSE 7860
CMD ["uvicorn", "fb_auto_reply.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "7860"]
