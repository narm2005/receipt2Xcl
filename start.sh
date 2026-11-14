#!/bin/bash
# Render start command: bash start.sh
cd "$(dirname "$0")/backend" && exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-10000}"
