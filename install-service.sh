#!/bin/bash
set -e

cat <<EOF | sudo tee /etc/systemd/system/issue-tracker-web.service
[Unit]
Description=Issue Tracker Web UI
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$1
ExecStart=$(pwd)/.venv/bin/uvicorn issue_tracker.web:create_app --factory --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

uv sync
sudo systemctl daemon-reload
sudo systemctl enable --now issue-tracker-web
