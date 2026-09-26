FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg

WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
RUN if [ -s /tmp/requirements.txt ]; then \
        pip install --no-cache-dir -r /tmp/requirements.txt; \
    fi

RUN groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid sandbox --create-home \
        --home-dir /tmp/sandbox-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /workspace /input /output \
    && chown -R sandbox:sandbox /workspace /input /output /tmp/sandbox-home

ENV HOME=/tmp

USER 10001:10001

CMD ["python"]
