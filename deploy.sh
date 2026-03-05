#!/bin/bash
# Deployment script for Retirement Income Planner
# Run on VPS as root

set -e

echo "=== Deploying Retirement Income Planner ==="

# Create app directory
mkdir -p /opt/pensionplanner/scenarios
mkdir -p /opt/pensionplanner/output
mkdir -p /opt/pensionplanner/static/css
mkdir -p /opt/pensionplanner/static/js
mkdir -p /opt/pensionplanner/templates

# Create virtual environment
if [ ! -d /opt/pensionplanner/venv ]; then
    python3 -m venv /opt/pensionplanner/venv
    echo "Virtual environment created"
fi

# Install dependencies
/opt/pensionplanner/venv/bin/pip install --upgrade pip
/opt/pensionplanner/venv/bin/pip install flask gunicorn
echo "Dependencies installed"

# Copy systemd service
cp /opt/pensionplanner/pensionplanner.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable pensionplanner
systemctl restart pensionplanner
echo "Service started"

# Copy nginx config
cp /opt/pensionplanner/pensionplanner_nginx.conf /etc/nginx/sites-available/pensionplanner
ln -sf /etc/nginx/sites-available/pensionplanner /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
echo "Nginx configured"

echo "=== Deployment complete ==="
echo "App running at https://planner.countdays.co.uk"
