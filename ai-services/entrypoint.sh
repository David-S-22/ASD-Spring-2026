#!/bin/sh
#reference: https://stackoverflow.com/a/78501628

ollama serve &
PID=$!

echo "[START] Waiting for ollama"
secs_to_wait=5

while ! ollama list > /dev/null 2>&1; do
  if [ $secs_to_wait -le 0 ]; then
    echo "[ERROR] Ollama failed to start" >&2
    kill $PID 2>/dev/null
    exit 1
  fi

  secs_to_wait=$((secs_to_wait - 1))
  sleep 1
done

echo "[END]   Waiting for ollama"
echo "[START] Pulling models"

# Models to install are provided via the OLLAMA_PULL_MODELS environment
# variable as a space-separated list (see docker-compose.yml).
for model in $OLLAMA_PULL_MODELS; do
  echo "[PULL]  $model"
  ollama pull "$model"
done

echo "[END]   Pulling models"
wait $PID
