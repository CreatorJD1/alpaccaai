#!/bin/sh
set -eu

umask 077
export ALPECCA_LLM_BACKEND=hf
export ALPECCA_HF_MODEL=Qwen/Qwen3.5-9B
export ALPECCA_REFLECT_THINK=0
export ALPECCA_CONTINUITY_ROLE=cloud-standby
export ALPECCA_REMOTE=1
export ALPECCA_SERVER_PORT=7860

cd "${ALPECCA_SOURCE_ROOT:-/opt/alpecca}"
exec python /opt/hf-cloud-core/cloud_process_supervisor.py
