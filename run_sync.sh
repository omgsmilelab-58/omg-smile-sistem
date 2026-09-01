#!/bin/bash
set -e

cd /var/www/omg-smile-sistem
git pull origin main
./venv/bin/python sync_cloud_data.py
