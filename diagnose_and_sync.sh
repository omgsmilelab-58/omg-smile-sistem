#!/bin/bash
set -e

echo "=========================================================="
echo "🔍 VERİTABANI KONTROL VE AKTARIM SİHİRBAZI"
echo "=========================================================="

echo ""
echo "▶ [1] Yerel PostgreSQL (localhost) Veri Durumu Kontrol Ediliyor:"
echo "----------------------------------------------------------"
sudo -u postgres psql -d omg_smile_erp -c "
SELECT 'isler' as tablo, count(*) as kayit_sayisi FROM isler
UNION ALL
SELECT 'cariler', count(*) FROM cariler
UNION ALL
SELECT 'stok', count(*) FROM stok
UNION ALL
SELECT 'fiyat_listesi', count(*) FROM fiyat_listesi
UNION ALL
SELECT 'kullanicilar', count(*) FROM kullanicilar;
" || echo "Tablolar henüz oluşturulmamış veya boş."

echo ""
echo "▶ [2] Google Cloud SQL (34.159.93.133) Bağlantısı Test Ediliyor:"
echo "----------------------------------------------------------"
export PGPASSWORD="Zeynep6658."

if pg_isready -h 34.159.93.133 -p 5432 -U postgres -t 5; then
    echo "✅ Google Cloud SQL'e BAŞARIYLA BAĞLANILDI!"
    
    echo ""
    echo "▶ [3] Google Cloud SQL'deki Gerçek Veri Sayıları:"
    psql -h 34.159.93.133 -U postgres -d omg_smile_erp -c "
    SELECT 'isler' as tablo, count(*) as kayit_sayisi FROM isler
    UNION ALL
    SELECT 'cariler', count(*) FROM cariler
    UNION ALL
    SELECT 'stok', count(*) FROM stok
    UNION ALL
    SELECT 'fiyat_listesi', count(*) FROM fiyat_listesi
    UNION ALL
    SELECT 'kullanicilar', count(*) FROM kullanicilar;
    " || true

    echo ""
    echo "▶ [4] Tüm Canlı Veriler Google Cloud'dan Yerel Veritabanına Çekiliyor..."
    pg_dump -h 34.159.93.133 -U postgres -d omg_smile_erp --clean --if-exists | sudo -u postgres psql -d omg_smile_erp
    pg_dump -h 34.159.93.133 -U postgres -d dentflow --clean --if-exists | sudo -u postgres psql -d dentflow
    
    # Yerel .env dosyasını doğrula
    cat << 'EOF' > /var/www/omg-smile-sistem/.env
USE_POSTGRES=True
DB_HOST=localhost
DB_USER=postgres
DB_PASS=Zeynep6658.
DB_PORT=5432
USE_CLOUD_STORAGE=False
EOF

    systemctl restart omgsmile
    echo ""
    echo "🎉 TÜM VERİLER BAŞARIYLA AKTARILDI VE SERVİS YENİDEN BAŞLATILDI!"
else
    echo "❌ Google Cloud SQL (34.159.93.133) bağlantısı ZAMAN AŞIMINA UĞRADI."
    echo "⚠️ Google Cloud Console > SQL > Bağlantılar > Yetkili Ağlar kısmına '213.159.7.216' eklenmemiş veya henüz kaydedilmemiş olabilir."
fi

echo "=========================================================="
