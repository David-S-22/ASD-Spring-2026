#!/bin/sh
#reference: https://stackoverflow.com/a/78501628

ollama serve &
PID=$!

echo "[START] waiting for ollama"
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

echo "[END]   waiting for ollama"
echo "[START] pulling models"

# If you want to use extra models, add them here
# to ensure they are installed in the container
ollama pull qwen2.5:0.5b
ollama pull llama3.1:8b

echo "[END]   pulling models"
wait $PID
