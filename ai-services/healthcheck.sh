#!/bin/sh
# Health check: succeed only once every required model is present on disk.
# This prevents dependent containers from starting before the (potentially
# multi-gigabyte) model downloads have completed. Relying on the server port
# alone reports ready instantly, long before the models finish downloading.

models_response=$(ollama list 2>/dev/null)

if [ $? -ne 0 ]; then
  echo "[FAIL]  Ollama API not reachable"
  exit 1
fi

for model in $OLLAMA_PULL_MODELS; do
  if ! echo "$models_response" | grep -q "$model"; then
    echo "[FAIL]  Missing required model: $model"
    exit 1
  fi
done

echo "[PASS]  All models present"
exit 0
