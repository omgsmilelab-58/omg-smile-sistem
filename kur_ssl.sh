#!/bin/bash
set -e

echo "=========================================================="
echo "🔒 DENTMESHER HUB - ÜCRETSİZ SSL (HTTPS) KURULUMU"
echo "=========================================================="

# 1. Gerekli paketlerin kontrolü
echo "▶ [1/4] Certbot paketleri kontrol ediliyor..."
which certbot >/dev/null 2>&1 || (apt-get update -y && apt-get install -y certbot python3-certbot-nginx)

# 2. Certbot ile SSL Sertifikası Al ve Nginx'e Otomatik Bağla
echo "▶ [2/4] Let's Encrypt SSL Sertifikası Talep Ediliyor..."
certbot --nginx -d dentmesherhub.com -d www.dentmesherhub.com --non-interactive --agree-tos --email info@dentmesherhub.com --redirect

# 3. Nginx Test ve Yeniden Başlatma
echo "▶ [3/4] Nginx Yapılandırması Test Ediliyor..."
nginx -t
systemctl reload nginx

# 4. Otomatik Yenileme (Cron) Kontrolü
echo "▶ [4/4] SSL Otomatik Yenileme Servisi Doğrulanıyor..."
systemctl enable certbot.timer 2>/dev/null || true
systemctl start certbot.timer 2>/dev/null || true

echo ""
echo "=========================================================="
echo "✅ SSL SERTİFİKASI BAŞARIYLA KURULDU VE AKTİF EDİLDİ!"
echo "🔒 Güvenli Adresiniz: https://dentmesherhub.com"
echo "=========================================================="
