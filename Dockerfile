FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system evalops \
    && useradd --system --gid evalops --home-dir /app evalops

COPY requirements.txt pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip install --no-cache-dir --no-deps .

USER evalops

ENTRYPOINT ["python", "-m", "evalops_agent"]
CMD ["chat"]
