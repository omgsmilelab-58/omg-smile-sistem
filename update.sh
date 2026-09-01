#!/bin/bash
set -e
cd /var/www/omg-smile-sistem
git pull origin main
systemctl restart omgsmile
echo "✅ Sistem başarıyla güncellendi ve yeniden başlatıldı!"
