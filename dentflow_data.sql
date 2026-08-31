-- dentflow Veri Yedek / Aktarım Dosyası
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

-- Tablo: kullanicilar (1 satır)
INSERT INTO "kullanicilar" ("id", "kullanici_adi", "isim", "sifre", "rol", "klinik_id") VALUES (1, 'tamer', 'Tamer Köseoğlu', '123', 'lab', 1) ON CONFLICT DO NOTHING;
SELECT setval(pg_get_serial_sequence('"kullanicilar"', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM "kullanicilar";

-- Tablo: mesajlar (2 satır)
INSERT INTO "mesajlar" ("id", "gonderen_id", "alici_id", "grup_id", "icerik", "zaman", "okundu", "tip") VALUES (1, 1, NULL, NULL, '🚨 DİKKAT: Acil dönüş/iletişim bekleniyor!', '17:30 - 21.05.2026', 0, 'duyuru') ON CONFLICT DO NOTHING;
INSERT INTO "mesajlar" ("id", "gonderen_id", "alici_id", "grup_id", "icerik", "zaman", "okundu", "tip") VALUES (2, 1, NULL, NULL, '✅ Bekleyen son işlem için ONAY verildi.', '17:32 - 21.05.2026', 0, 'duyuru') ON CONFLICT DO NOTHING;
SELECT setval(pg_get_serial_sequence('"mesajlar"', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM "mesajlar";

-- Tablo: okunan_duyurular (1 satır)
INSERT INTO "okunan_duyurular" ("kullanici_id", "duyuru_id") VALUES ('1', 0) ON CONFLICT DO NOTHING;

