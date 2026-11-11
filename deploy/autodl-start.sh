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
export SPIDER_PORT=8889
mkdir -p "$base/logs" "$SPIDER_STATE_ROOT/data" "$base/rag" "$MINERU_HOME"
# Do not silently keep the old GPU-resident server or kill another running task.
# Migration requires an explicitly authorized stop of the legacy session first.
if tmux has-session -t unifiedspider-vlm 2>/dev/null; then
  echo 'Legacy always-on VLM still exists. Drain jobs and obtain authorization to stop it before migrating.' >&2
  exit 1
fi
if [ ! -f /root/autodl-tmp/AIfinance/code/packages/preprocess/mineru_service.py ]; then
  echo 'Deploy the committed AIfinance demand-VLM implementation before starting the collector.' >&2
  exit 1
fi
if [ ! -d "$base/venv" ]; then /root/miniconda3/bin/python -m venv "$base/venv"; fi
"$base/venv/bin/python" -m pip install -r "$release/config/requirements-cloud.txt"
if [ ! -e "$MINERU_HOME/models" ]; then
  ln -s /root/autodl-tmp/AIfinance/runtime/mineru4-home/models "$MINERU_HOME/models"
fi
if [ ! -f "$SPIDER_STATE_ROOT/data/download-settings.json" ]; then
  printf '{"mode":"folder","folder":"/root/autodl-tmp/unifiedspider/rag"}\n' > "$SPIDER_STATE_ROOT/data/download-settings.json"
fi
if ! tmux has-session -t aifinance-demand-vlm 2>/dev/null; then
  if (echo >/dev/tcp/127.0.0.1/18769) 2>/dev/null; then
    echo 'Port 18769 is occupied by an unmanaged service; refusing to replace it.' >&2; exit 1
  fi
  tmux new-session -d -s aifinance-demand-vlm "cd /root/autodl-tmp/AIfinance/code; export PYTHONDONTWRITEBYTECODE=1; /root/autodl-tmp/envs/aifinance/bin/python -m packages.preprocess.mineru_service --config /root/autodl-tmp/AIfinance/config.txt >> '$base/logs/vlm-gateway.log' 2>&1"
fi
# A health check does not wake the GPU engine. Core code must be deployed first.
gateway_ready=0
for attempt in {1..20}; do
  if curl -fsS --max-time 2 http://127.0.0.1:18769/health | grep -q 'aifinance-demand-vlm'; then gateway_ready=1; break; fi
  sleep 1
done
if [ "$gateway_ready" != 1 ]; then echo 'Demand VLM gateway did not become ready; check vlm-gateway.log.' >&2; exit 1; fi
if ! tmux has-session -t unifiedspider-mineru 2>/dev/null; then
  tmux new-session -d -s unifiedspider-mineru "export PYTHONDONTWRITEBYTECODE=1 MINERU_HOME='$MINERU_HOME'; /root/autodl-tmp/AIfinance/runtime/mineru4/bin/mineru-api --host 127.0.0.1 --port 18768 --tier standard --concurrency 1 --vlm-server-url http://127.0.0.1:18769 --vlm-model mineru --vlm-max-concurrency 1 --upload-dir '$base/mineru-tasks' >> '$base/logs/mineru.log' 2>&1"
fi
if tmux has-session -t unifiedspider-web 2>/dev/null; then
  echo 'Web service already exists; not restarting an existing service.'; exit 1
fi
tmux new-session -d -s unifiedspider-web "cd '$release'; export PYTHONDONTWRITEBYTECODE=1 SPIDER_STATE_ROOT='$SPIDER_STATE_ROOT' MINERU_SELF_HOSTED_URL='$MINERU_SELF_HOSTED_URL' MINERU_SELF_HOSTED_TIER=standard MINERU_MODE=hybrid MINERU_API_TOKEN_FILE='$MINERU_API_TOKEN_FILE' SPIDER_PORT=8889; '$base/venv/bin/python' app/app.py --no-browser >> '$base/logs/web.log' 2>&1"
echo "Started committed release: $release"
