#!/bin/bash
cd /home/ziv/team-content-engine
export PYTHONPATH=/home/ziv/team-content-engine/src
exec python3 -m uvicorn tce.main:app --host 0.0.0.0 --port 8200
