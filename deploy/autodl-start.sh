#!/usr/bin/env bash
set -euo pipefail
base=/root/autodl-tmp/unifiedspider
release=$(cd "$(dirname "$0")/.." && pwd)
case "$release" in "$base"/releases/*) ;; *) echo 'Refusing unexpected release directory' >&2; exit 1;; esac
export PYTHONDONTWRITEBYTECODE=1
export SPIDER_STATE_ROOT="$base/state"
export MINERU_HOME="$base/mineru-home"
export MINERU_SELF_HOSTED_URL=http://127.0.0.1:18768
export MINERU_SELF_HOSTED_TIER=standard
export MINERU_MODE=hybrid
export MINERU_API_TOKEN_FILE="$base/secrets/mineru-api-token"
export SPIDER_PORT=18765
mkdir -p "$base/logs" "$SPIDER_STATE_ROOT/data" "$base/rag" "$MINERU_HOME"
if [ ! -d "$base/venv" ]; then /root/miniconda3/bin/python -m venv "$base/venv"; fi
"$base/venv/bin/python" -m pip install -r "$release/requirements-cloud.txt"
if [ ! -e "$MINERU_HOME/models" ]; then
  ln -s /root/autodl-tmp/AIfinance/runtime/mineru4-home/models "$MINERU_HOME/models"
fi
if [ ! -f "$SPIDER_STATE_ROOT/data/download-settings.json" ]; then
  printf '{"mode":"folder","folder":"/root/autodl-tmp/unifiedspider/rag"}\n' > "$SPIDER_STATE_ROOT/data/download-settings.json"
fi
if ! tmux has-session -t unifiedspider-vlm 2>/dev/null; then
  tmux new-session -d -s unifiedspider-vlm "export PYTHONDONTWRITEBYTECODE=1 HF_HOME='$base/model-cache' VLLM_CACHE_ROOT='$base/vllm-cache' TORCHINDUCTOR_CACHE_DIR='$base/torch-cache' TRITON_CACHE_DIR='$base/triton-cache'; /root/autodl-tmp/envs/aifinance/bin/python -m vllm.entrypoints.openai.api_server --model /root/autodl-tmp/AIfinance/models/mineru/vlm --served-model-name mineru --host 127.0.0.1 --port 18769 --gpu-memory-utilization 0.3 --max-model-len 8192 --max-num-seqs 2 --enforce-eager >> '$base/logs/vlm.log' 2>&1"
fi
if ! tmux has-session -t unifiedspider-mineru 2>/dev/null; then
  tmux new-session -d -s unifiedspider-mineru "export PYTHONDONTWRITEBYTECODE=1 MINERU_HOME='$MINERU_HOME'; /root/autodl-tmp/AIfinance/runtime/mineru4/bin/mineru-api --host 127.0.0.1 --port 18768 --tier standard --concurrency 1 --vlm-server-url http://127.0.0.1:18769 --vlm-model mineru --vlm-max-concurrency 1 --upload-dir '$base/mineru-tasks' >> '$base/logs/mineru.log' 2>&1"
fi
if tmux has-session -t unifiedspider-web 2>/dev/null; then
  echo 'Web service already exists; not restarting an existing service.'; exit 1
fi
tmux new-session -d -s unifiedspider-web "cd '$release'; export PYTHONDONTWRITEBYTECODE=1 SPIDER_STATE_ROOT='$SPIDER_STATE_ROOT' MINERU_SELF_HOSTED_URL='$MINERU_SELF_HOSTED_URL' MINERU_SELF_HOSTED_TIER=standard MINERU_MODE=hybrid MINERU_API_TOKEN_FILE='$MINERU_API_TOKEN_FILE' SPIDER_PORT=18765; '$base/venv/bin/python' app.py --no-browser >> '$base/logs/web.log' 2>&1"
echo "Started committed release: $release"
