#!/bin/bash
set -e

echo "=========================================================="
echo "🚀 OMG SMILE SİSTEM - OTOMATİK KURULUM VE AKTARIM SİSTEMİ"
echo "=========================================================="

# 1. SSH İzinlerini ve Servisini Düzeltme
echo "▶ [1/8] SSH ve Sistem Ayarları Yapılandırılıyor..."
mkdir -p /etc/ssh/sshd_config.d/
echo "PermitRootLogin yes" > /etc/ssh/sshd_config.d/root.conf
systemctl restart ssh || systemctl restart ssh.socket || true

# 2. Paketlerin Kurulumu
echo "▶ [2/8] Gerekli Sistem Paketleri Yükleniyor (Python, PostgreSQL, Nginx, vb.)..."
DEBIAN_FRONTEND=noninteractive apt update -y
DEBIAN_FRONTEND=noninteractive apt install -y python3 python3-pip python3-venv python3-dev postgresql postgresql-contrib nginx certbot python3-certbot-nginx git libpq-dev build-essential curl

# 3. PostgreSQL Yapılandırması
echo "▶ [3/8] PostgreSQL Veritabanı ve Kullanıcı Hazırlanıyor..."
systemctl start postgresql
systemctl enable postgresql

sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'Zeynep6658.';"

# Veritabanları yoksa oluştur
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = 'omg_smile_erp'" | grep -q 1 || sudo -u postgres psql -c "CREATE DATABASE omg_smile_erp;"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = 'dentflow'" | grep -q 1 || sudo -u postgres psql -c "CREATE DATABASE dentflow;"

sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE omg_smile_erp TO postgres;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE dentflow TO postgres;"

# 4. Projenin İndirilmesi
echo "▶ [4/8] Proje GitHub'dan İndiriliyor..."
mkdir -p /var/www
cd /var/www

if [ -d "/var/www/omg-smile-sistem/.git" ]; then
    cd /var/www/omg-smile-sistem
    git pull origin main
else
    rm -rf /var/www/omg-smile-sistem
    git clone https://github.com/omgsmilelab-58/omg-smile-sistem.git /var/www/omg-smile-sistem
    cd /var/www/omg-smile-sistem
fi

# 5. Python Sanal Ortam (venv) ve Bağımlılıklar
echo "▶ [5/8] Python Sanal Ortamı ve Kütüphaneler Kuruluyor..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 6. .env Dosyası ve Veri Aktarımı
echo "▶ [6/8] .env Dosyası Hazırlanıyor ve Mevcut Veriler Aktarılıyor..."
cat << 'EOF' > /var/www/omg-smile-sistem/.env
USE_POSTGRES=True
DB_HOST=localhost
DB_USER=postgres
DB_PASS=Zeynep6658.
DB_PORT=5432
USE_CLOUD_STORAGE=False
EOF

# Şemayı oluştur ve eski verileri aktar
./venv/bin/python veritabani_kur.py || true

if [ -f "omg_smile_erp_data.sql" ]; then
    sudo -u postgres psql -d omg_smile_erp -f omg_smile_erp_data.sql || true
fi

if [ -f "dentflow_data.sql" ]; then
    sudo -u postgres psql -d dentflow -f dentflow_data.sql || true
fi

# 7. Systemd Servisi
echo "▶ [7/8] Otomatik Çalışma Servisi (Systemd) Başlatılıyor..."
cat << 'EOF' > /etc/systemd/system/omgsmile.service
[Unit]
Description=OMG Smile Sistem Streamlit App
After=network.target postgresql.service

[Service]
User=root
WorkingDirectory=/var/www/omg-smile-sistem
ExecStart=/var/www/omg-smile-sistem/venv/bin/streamlit run ana_program.py --server.port 8501 --server.address 127.0.0.1
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable omgsmile
systemctl restart omgsmile

# 8. Nginx Yapılandırması
echo "▶ [8/8] Nginx Web Sunucusu Yapılandırılıyor..."
cat << 'EOF' > /etc/nginx/sites-available/dentmesherhub.com
server {
    listen 80;
    server_name dentmesherhub.com www.dentmesherhub.com 213.159.7.216;

    client_max_body_size 200M;

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

ln -sf /etc/nginx/sites-available/dentmesherhub.com /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo ""
echo "=========================================================="
echo "🎉 TEBRİKLER! TÜM SİSTEM VE VERİLER BAŞARIYLA KURULDU!"
echo "=========================================================="
echo "📍 IP Üzerinden Test: http://213.159.7.216"
echo "📍 Domain: http://dentmesherhub.com"
echo "=========================================================="
