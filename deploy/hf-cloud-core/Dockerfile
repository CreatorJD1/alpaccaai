FROM node:22-bookworm-slim AS source

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG ALPECCA_GIT_REF=main
ARG ALPECCA_GIT_SHA
RUN test -n "${ALPECCA_GIT_SHA}" \
    && git check-ref-format --branch "${ALPECCA_GIT_REF}" \
    && git clone --depth 1 --branch "${ALPECCA_GIT_REF}" \
        https://github.com/CreatorJD1/alpaccaai.git /opt/alpecca \
    && test "$(git -C /opt/alpecca rev-parse HEAD)" = "${ALPECCA_GIT_SHA}"
WORKDIR /opt/alpecca/apps/house-hq
RUN npm ci && npm run build
WORKDIR /opt/alpecca
RUN mkdir -p /opt/runtime \
    && tar \
        --exclude='./.git' \
        --exclude='./.claude' \
        --exclude='./deploy' \
        --exclude='./docs' \
        --exclude='./scripts' \
        --exclude='./tests' \
        --exclude='./notebooks' \
        --exclude='./workflows' \
        --exclude='./apps/launcher' \
        --exclude='./apps/android-launcher' \
        --exclude='./data/*.db*' \
        --exclude='./data/logs' \
        -cf - . \
    | tar -C /opt/runtime -xf -

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/alpecca \
    PORT=7860 \
    ALPECCA_SOURCE_ROOT=/opt/alpecca \
    ALPECCA_CLOUD_RUNTIME_ROOT=/tmp/alpecca-cloud-core \
    ALPECCA_LLM_BACKEND=hf \
    ALPECCA_HF_MODEL=Qwen/Qwen3.5-9B \
    ALPECCA_REFLECT_THINK=0 \
    ALPECCA_CONTINUITY_ROLE=cloud-standby \
    ALPECCA_CLOUD_VOICE_PORT=7861 \
    ALPECCA_REMOTE=1 \
    ALPECCA_SERVER_PORT=7860 \
    ALPECCA_TUNNEL=off

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates espeak-ng libsndfile1 tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 alpecca \
    && install -d -o 1000 -g 1000 /opt/hf-cloud-core /tmp/alpecca-cloud-core

COPY requirements.txt /tmp/cloud-core-requirements.txt
RUN pip install --no-cache-dir -r /tmp/cloud-core-requirements.txt
RUN pip install --no-cache-dir \
    https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
COPY --from=source /opt/runtime /opt/alpecca
COPY --chown=1000:1000 app.py cloud_entrypoint.py cloud_healthcheck.py \
    cloud_process_supervisor.py cloud_voice.py start.sh /opt/hf-cloud-core/
RUN sed -i 's/\r$//' /opt/hf-cloud-core/start.sh \
    && chmod 0555 /opt/hf-cloud-core/start.sh

WORKDIR /opt/alpecca
USER 1000
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=2 \
    CMD python /opt/hf-cloud-core/cloud_healthcheck.py

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/opt/hf-cloud-core/start.sh"]
