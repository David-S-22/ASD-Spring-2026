#!/bin/sh
#reference: https://stackoverflow.com/a/78501628

/bin/ollama serve &
PID=$!

sleep 5

echo "pulling models"
ollama pull qwen2.5:0.5b
ollama pull llama3.1:8b
echo "finished pulling models"

wait $PID
