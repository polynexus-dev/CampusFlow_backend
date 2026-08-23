#!/bin/sh
set -e

echo "🚀 Starting Ollama server..."
ollama serve &
OLLAMA_PID=$!

echo "⏳ Waiting for Ollama to be ready..."
until ollama list > /dev/null 2>&1; do
    echo "   Ollama is not ready yet — retrying in 2s..."
    sleep 2
done
echo "✅ Ollama is ready!"

# Pulls are a no-op once a model is already present, so this is safe to run
# on every container start — it just confirms both models CampusFlow depends
# on (campusflow/settings.py: AI_GRADING_MODEL, AI_NARRATIVE_MODEL) are pulled,
# without blocking web/celery_worker's own boot on a multi-GB download.
echo "📦 Pulling AI_GRADING_MODEL (${AI_GRADING_MODEL:-qwen2.5vl:3b})..."
ollama pull "${AI_GRADING_MODEL:-qwen2.5vl:3b}"
echo "📦 Pulling AI_NARRATIVE_MODEL (${AI_NARRATIVE_MODEL:-llama3.2:3b})..."
ollama pull "${AI_NARRATIVE_MODEL:-llama3.2:3b}"
echo "✅ Models ready."

wait "$OLLAMA_PID"
