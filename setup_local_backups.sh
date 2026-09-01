#!/bin/bash
set -e

echo "=========================================================="
echo "🛡️ OTOMATİK GÜNLÜK YEREL YEDEKLEME SİSTEMİ KURULUMU"
echo "=========================================================="

# Yedekleme dizinini oluştur
mkdir -p /var/backups/omg_smile
mkdir -p /var/www/omg-smile-sistem/backups

# Yedekleme betiğini oluştur
cat << 'EOF' > /var/www/omg-smile-sistem/backup_daily.sh
#!/bin/bash
BACKUP_DIR="/var/backups/omg_smile"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"

# PostgreSQL Veritabanı Yedekleri
sudo -u postgres pg_dump omg_smile_erp > "$BACKUP_DIR/omg_smile_erp_$TIMESTAMP.sql"
sudo -u postgres pg_dump dentflow > "$BACKUP_DIR/dentflow_$TIMESTAMP.sql"

# Sıkıştır
gzip -f "$BACKUP_DIR/omg_smile_erp_$TIMESTAMP.sql"
gzip -f "$BACKUP_DIR/dentflow_$TIMESTAMP.sql"

# 30 günden eski yedekleri otomatik temizle
find "$BACKUP_DIR" -type f -name "*.sql.gz" -mtime +30 -delete

echo "[$(date)] Otomatik yedekleme başarıyla tamamlandı: $TIMESTAMP" >> /var/log/omg_backup.log
EOF

chmod +x /var/www/omg-smile-sistem/backup_daily.sh

# Cronjob ekle (Her gece saat 03:00'te otomatik yedek alsın)
CRON_CMD="0 3 * * * /var/www/omg-smile-sistem/backup_daily.sh >/dev/null 2>&1"
(crontab -l 2>/dev/null | grep -v "backup_daily.sh" ; echo "$CRON_CMD") | crontab -

# İlk testi hemen çalıştır
/var/www/omg-smile-sistem/backup_daily.sh

echo "✅ Otomatik günlük yerel yedekleme başarıyla kuruldu!"
echo "📍 Yedekler her gece 03:00'te /var/backups/omg_smile dizinine kaydedilecektir."
echo "=========================================================="
