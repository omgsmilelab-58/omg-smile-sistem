#!/bin/bash
set -e

echo "=========================================================="
echo "🤖 UZAKTAN YÖNETİM VE OTOMATİK GÜNCELLEME AJANI KURULUMU"
echo "=========================================================="

cd /var/www/omg-smile-sistem
git pull origin main

# 1. Systemd servisini kur
cat << 'EOF' > /etc/systemd/system/omg_deploy.service
[Unit]
Description=OMG Deploy Webhook Agent
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/omg-smile-sistem
ExecStart=/var/www/omg-smile-sistem/venv/bin/python deploy_server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable omg_deploy
systemctl restart omg_deploy

# 2. Nginx ayarına webhook yolunu ekle
cat << 'EOF' > /etc/nginx/sites-available/dentmesherhub.com
server {
    listen 80;
    server_name dentmesherhub.com www.dentmesherhub.com 213.159.7.216;

    client_max_body_size 200M;

    # Uzaktan Otomatik Güncelleme Uç Noktası
    location /api/auto-deploy {
        proxy_pass http://127.0.0.1:9090;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Ana Streamlit Uygulaması
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
EOF

nginx -t
systemctl reload nginx

# 3. Ana uygulamayı yeniden başlat
systemctl restart omgsmile

echo "✅ Uzaktan güncelleme ajanı başarıyla kuruldu ve aktif edildi!"
echo "=========================================================="
