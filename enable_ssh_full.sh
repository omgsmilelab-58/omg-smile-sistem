#!/bin/bash
set -e

echo "=========================================================="
echo "🔑 SSH BAĞLANTISINI DIŞARIYA VE ROOT KULLANICISINA AÇMA"
echo "=========================================================="

# 1. OpenSSH Server paketini doğrula
apt update -y
apt install -y openssh-server

# 2. SSH Ayarlarını yapılandır
sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

mkdir -p /etc/ssh/sshd_config.d/
cat << 'EOF' > /etc/ssh/sshd_config.d/01-custom.conf
PermitRootLogin yes
PasswordAuthentication yes
KbdInteractiveAuthentication yes
EOF

# 3. Ubuntu 24.04 socket aktivasyonunu kapatıp standart servisi başlat
systemctl stop ssh.socket 2>/dev/null || true
systemctl disable ssh.socket 2>/dev/null || true
systemctl enable ssh.service
systemctl restart ssh

# 4. En güncel kodları çek ve servisi yenile
cd /var/www/omg-smile-sistem
git pull origin main
systemctl restart omgsmile

echo ""
echo "=========================================================="
echo "✅ SSH BAŞARIYLA TAM MODDA DIŞ BAĞLANTIYA AÇILDI!"
echo "📍 Artık yapay zeka asistanı doğrudan SSH ile bağlanıp tüm işlemleri yapabilir."
echo "=========================================================="
