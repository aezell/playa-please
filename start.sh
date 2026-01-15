#!/bin/bash
cd /home/sprite/playa-please/backend
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
