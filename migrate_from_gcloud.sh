#!/bin/bash
set -e

echo "=========================================================="
echo "☁️ GOOGLE CLOUD SQL -> YENİ SUNUCUYA TAM VERİ AKTARIMI"
echo "=========================================================="

CLOUD_IP="34.159.93.133"
DB_PASS="Zeynep6658."

echo "▶ [1/4] Google Cloud SQL bağlantısı test ediliyor ($CLOUD_IP)..."

export PGPASSWORD="$DB_PASS"

# Test connection
if pg_isready -h "$CLOUD_IP" -p 5432 -U postgres; then
    echo "✅ Google Cloud SQL bağlantısı başarılı!"
    
    echo "▶ [2/4] omg_smile_erp veritabanı Google Cloud'dan çekilip yerel veritabanına aktarılıyor..."
    pg_dump -h "$CLOUD_IP" -U postgres -d omg_smile_erp --clean --if-exists | sudo -u postgres psql -d omg_smile_erp
    
    echo "▶ [3/4] dentflow veritabanı Google Cloud'dan çekilip yerel veritabanına aktarılıyor..."
    pg_dump -h "$CLOUD_IP" -U postgres -d dentflow --clean --if-exists | sudo -u postgres psql -d dentflow
    
    echo "▶ [4/4] Uygulama servisi yeniden başlatılıyor..."
    systemctl restart omgsmile
    
    echo ""
    echo "=========================================================="
    echo "🎉 GOOGLE CLOUD'DAKİ TÜM CANLI VERİLER YENİ SUNUCUYA AKTARILDI!"
    echo "=========================================================="
else
    echo ""
    echo "⚠️ Google Cloud SQL ($CLOUD_IP) bağlantıyı reddetti / zaman aşımına uğradı."
    echo "👉 Google Cloud Console > SQL > Bağlantılar (Connections) > Yetkili Ağlar (Authorized Networks) bölümüne"
    echo "   Yeni sunucunuzun IP adresi olan '213.159.7.216' adresini eklemeniz gerekmektedir."
fi
