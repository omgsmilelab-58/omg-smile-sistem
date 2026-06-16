from dotenv import load_dotenv
load_dotenv()
"""
OMG Smile - Veritabanı Kurulum Scripti
Bulut ortamında (Streamlit Cloud) her başlamada çalışır.
VT dosyaları yoksa oluşturur ve örnek verilerle doldurur.
"""
import sqlite3
import db_baglanti
import storage_utils
import os
from datetime import datetime


def dentflow_db_kur():
    """DentFlow mesajlaşma ve kullanıcı veritabanını kur."""
    conn = db_baglanti.get_connection('dentflow.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS klinikler 
                 (id SERIAL PRIMARY KEY, isim TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS kullanicilar 
                 (id SERIAL PRIMARY KEY, kullanici_adi TEXT, isim TEXT, 
                  sifre TEXT, rol TEXT, klinik_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mesajlar 
                 (id SERIAL PRIMARY KEY, gonderen_id INTEGER, alici_id INTEGER, 
                  grup_id INTEGER, icerik TEXT, zaman TEXT, 
                  okundu INTEGER DEFAULT 0, tip TEXT DEFAULT 'sohbet')''')
    c.execute('''CREATE TABLE IF NOT EXISTS gruplar 
                 (id SERIAL PRIMARY KEY, 
                  grup_adi TEXT, kurucu_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS grup_uyeleri (id SERIAL PRIMARY KEY, grup_id INTEGER, kullanici_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS okunan_duyurular (id SERIAL PRIMARY KEY, kullanici_id TEXT, duyuru_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sistem_loglari (id SERIAL PRIMARY KEY, Tarih_Saat TEXT, Kullanici TEXT, Aksiyon TEXT, Goruldu INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS engellemeler (id SERIAL PRIMARY KEY, engelleyen_id TEXT, engellenen_id TEXT)''')
    
    # Boşsa örnek kullanıcı ekle
    if c.execute("SELECT COUNT(*) FROM kullanicilar").fetchone()[0] == 0:
        c.execute("INSERT INTO klinikler (isim) VALUES ('Omg Smile Lab'), ('Dent58'), ('Çınar Klinik')")
        c.execute("INSERT INTO kullanicilar (kullanici_adi, isim, sifre, rol, klinik_id) VALUES ('tamer', 'Tamer Köseoğlu', '123', 'lab', 1)")
        c.execute("INSERT INTO kullanicilar (kullanici_adi, isim, sifre, rol, klinik_id) VALUES ('ayse', 'Dt. Ayşe Yılmaz', '123', 'doktor', 2)")
        c.execute("INSERT INTO kullanicilar (kullanici_adi, isim, sifre, rol, klinik_id) VALUES ('ahmet', 'Ahmet', '123', 'asistan', 2)")
        print("[DentFlow] Örnek kullanıcılar oluşturuldu.")
    
    conn.commit()
    conn.close()
    print("[DentFlow] Veritabanı hazır.")


def omg_erp_db_kur():
    """Ana ERP veritabanını kur."""
    conn = db_baglanti.get_connection('omg_smile_erp.db', timeout=20)
    # conn.execute('PRAGMA journal_mode=WAL;')
    c = conn.cursor()
    
    tablolar = [
        '''CREATE TABLE IF NOT EXISTS cariler (id SERIAL PRIMARY KEY, Klinik_Unvani TEXT, Yetkili_Kisi TEXT, Telefon TEXT, Email TEXT, 
            Bakiye REAL, Risk_Limiti REAL, Indirim_Orani REAL DEFAULT 0.0, 
            Sifre TEXT DEFAULT '1234', Adres TEXT DEFAULT '-',
            Firma_Unvani TEXT DEFAULT '-', Vergi_Dairesi TEXT DEFAULT '-',
            Vergi_No TEXT DEFAULT '-', IBAN TEXT DEFAULT '-',
            VIP_Seviye TEXT DEFAULT 'Standart', Durum TEXT DEFAULT 'Aktif',
            Bildirim_Kurye TEXT DEFAULT 'WhatsApp',
            Bildirim_Fatura TEXT DEFAULT 'E-Posta',
            Bildirim_Asama TEXT DEFAULT 'Sessiz (İstemiyorum)',
            Otopilot_Kategori TEXT DEFAULT '-',
            Otopilot_Islem TEXT DEFAULT '-',
            Otopilot_Renk TEXT DEFAULT 'A2')''',
        
        '''CREATE TABLE IF NOT EXISTS isler (id SERIAL PRIMARY KEY, Tarih TEXT, Klinik_Unvani TEXT, Hasta_Adi TEXT, Is_Turu TEXT, 
            Renk TEXT, Asama TEXT, Tutar_TL REAL DEFAULT 0.0, 
            Sorumlu_Personel TEXT DEFAULT '-', Harcanan_Malzeme TEXT DEFAULT '-', 
            Teslim_Tarihi TEXT DEFAULT '2026-01-01', Barkod TEXT DEFAULT '-', 
            Lot_Numarasi TEXT DEFAULT '-', Sertifika_No TEXT DEFAULT '-',
            Aciklama TEXT DEFAULT '-')''',
        
        '''CREATE TABLE IF NOT EXISTS stok (id SERIAL PRIMARY KEY, Urun_Kodu TEXT, Urun_Adi TEXT, Kategori TEXT, Mevcut_Miktar REAL, 
            Birim TEXT, Kritik_Sinir REAL, Satis_Fiyati REAL, Durum TEXT DEFAULT 'Aktif', Renk TEXT DEFAULT '-', Guncelleme_Tarihi TEXT DEFAULT '-')''',
        
        '''CREATE TABLE IF NOT EXISTS fiyat_listesi (id SERIAL PRIMARY KEY, Hizmet_Adi TEXT, Kategori TEXT, Fiyat REAL, Para_Birimi TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS hizmet_maliyetleri (id SERIAL PRIMARY KEY, hizmet_id INTEGER, kalem_adi TEXT, tutar REAL)''',
        
        '''CREATE TABLE IF NOT EXISTS personeller (id SERIAL PRIMARY KEY, Ad_Soyad TEXT, Gorevi TEXT, Telefon TEXT, Maas REAL, 
            Baslama_Tarihi TEXT, Ayrilma_Tarihi TEXT, Durum TEXT,
            TC_No TEXT DEFAULT '-', Email TEXT DEFAULT '-',
            Adres TEXT DEFAULT '-', IBAN TEXT DEFAULT '-',
            Kalan_Izin INTEGER DEFAULT 14,
            Foto_Yolu TEXT DEFAULT '-', CV_Yolu TEXT DEFAULT '-')''',
        
        '''CREATE TABLE IF NOT EXISTS kullanicilar (id SERIAL PRIMARY KEY, Kullanici_Adi TEXT, Sifre TEXT, Rol TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS giderler (id SERIAL PRIMARY KEY, Tarih TEXT, Kategori TEXT, Aciklama TEXT, Tutar REAL)''',
        
        '''CREATE TABLE IF NOT EXISTS tahsilatlar (id SERIAL PRIMARY KEY, Tarih TEXT, Klinik_Unvani TEXT, Odeme_Turu TEXT, Tutar REAL, Aciklama TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS is_fotograflari (id SERIAL PRIMARY KEY, Is_ID INTEGER, Dosya_Yolu TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS is_3d_modelleri (id SERIAL PRIMARY KEY, Is_ID INTEGER, Dosya_Yolu TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS cihazlar (id SERIAL PRIMARY KEY, Cihaz_Adi TEXT, Kategori TEXT, Calisma_Saati REAL DEFAULT 0, 
            Bakim_Siniri REAL DEFAULT 500, Son_Bakim_Tarihi TEXT, 
            Durum TEXT DEFAULT 'Aktif', Gorsel_Yolu TEXT DEFAULT '-',
            Haftalik_Hedef TEXT, Aylik_Hedef TEXT, Yillik_Hedef TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS cihaz_bakim_gecmisi (id SERIAL PRIMARY KEY, Cihaz_Adi TEXT, Tarih TEXT, Islem TEXT, Maliyet REAL DEFAULT 0, Aciklama TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS kurye_islemleri (id SERIAL PRIMARY KEY, Tarih TEXT, Saat TEXT DEFAULT '00:00', Klinik_Unvani TEXT, 
            Aciklama TEXT, Durum TEXT DEFAULT 'Bekliyor')''',
        
        '''CREATE TABLE IF NOT EXISTS cam_bloklar (id SERIAL PRIMARY KEY, Blok_Kodu TEXT, Urun_Adi TEXT, Boyut_Renk TEXT, 
            Kapasite_Uye INTEGER, Kalan_Uye INTEGER, Durum TEXT DEFAULT 'Yarım')''',
        
        '''CREATE TABLE IF NOT EXISTS cam_frezler (id SERIAL PRIMARY KEY, Frez_Kodu TEXT, Urun_Adi TEXT, Uyumlu_Makine TEXT, 
            Max_Omur_Dk INTEGER, Kalan_Omur_Dk INTEGER, Durum TEXT DEFAULT 'Aktif')''',
        
        '''CREATE TABLE IF NOT EXISTS ayarlar 
           (Ayar_Adi TEXT PRIMARY KEY, Ayar_Degeri TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS personel_finans (id SERIAL PRIMARY KEY, Tarih TEXT, Personel_Adi TEXT, Islem_Turu TEXT, Tutar REAL, Aciklama TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS personel_izinler (id SERIAL PRIMARY KEY, Tarih TEXT, Personel_Adi TEXT, Baslangic_Tarihi TEXT, 
            Bitis_Tarihi TEXT, Gun_Sayisi INTEGER, Aciklama TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS klinik_asistanlari 
           (Klinik_Unvani TEXT, Asistan_Kadi TEXT PRIMARY KEY, Sifre TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS laboratuvar_dokumanlari (id SERIAL PRIMARY KEY, Tarih TEXT, Dokuman_Adi TEXT, Dosya_Yolu TEXT, Dosya_Turu TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS sistem_loglari (id SERIAL PRIMARY KEY, Tarih_Saat TEXT, Kullanici TEXT, Aksiyon TEXT, Goruldu INTEGER)''',
        
        '''CREATE TABLE IF NOT EXISTS mesajlar (id SERIAL PRIMARY KEY, Tarih_Saat TEXT, Gonderen TEXT, Alici TEXT, Mesaj TEXT, Okundu INTEGER)''',
        
        '''CREATE TABLE IF NOT EXISTS aktif_frezler 
           (id SERIAL PRIMARY KEY, makine_adi TEXT, yuva_no TEXT,
            frez_kod TEXT, frez_adi TEXT, toplam_omur_dk INTEGER, 
            kullanilan_dk INTEGER, birim_fiyat_euro REAL, durum TEXT)''',
            
        '''CREATE TABLE IF NOT EXISTS tedarikciler 
           (id SERIAL PRIMARY KEY, Firma_Unvani TEXT, Yetkili_Kisi TEXT, 
            Telefon TEXT, Email TEXT, Kategori TEXT, Bakiye REAL DEFAULT 0.0, 
            IBAN TEXT DEFAULT '-', Vergi_Dairesi TEXT DEFAULT '-', 
            Vergi_No TEXT DEFAULT '-', Adres TEXT DEFAULT '-', 
            Durum TEXT DEFAULT 'Aktif')''',

        '''CREATE TABLE IF NOT EXISTS fire_kayitlari
           (id SERIAL PRIMARY KEY, Tarih TEXT, Urun_Kodu TEXT, Urun_Adi TEXT DEFAULT '-', Miktar REAL, Neden TEXT, Kullanici TEXT, Kalan_Omur TEXT DEFAULT '-')''',

        '''CREATE TABLE IF NOT EXISTS malzeme_arsivi
           (id SERIAL PRIMARY KEY, Tarih TEXT, Urun_Kodu TEXT, Urun_Adi TEXT, Miktar REAL, Islem_Turu TEXT, Aciklama TEXT, Kullanici TEXT)'''
    ]
    
    for tablo_sql in tablolar:
        c.execute(tablo_sql)
        
    # Renk sütunu migrasyonu (mevcut tablolar için)
    try:
        c.execute("ALTER TABLE stok ADD COLUMN Renk TEXT DEFAULT '-'")
        print("[ERP] stok tablosuna Renk sütunu eklendi.")
    except Exception as e:
        pass # Zaten ekliyse hata verir, yoksay.
    
    # Admin kullanıcısı yoksa oluştur
    if c.execute("SELECT count(*) FROM kullanicilar").fetchone()[0] == 0:
        c.execute("INSERT INTO kullanicilar (Kullanici_Adi, Sifre, Rol) VALUES ('tamer', 'admin123', 'Admin')")
        c.execute("INSERT INTO kullanicilar (Kullanici_Adi, Sifre, Rol) VALUES ('kurye', '1234', 'Kurye')")
        print("[ERP] Admin kullanıcıları oluşturuldu.")
    
    # Varsayılan ayarlar
    if c.execute("SELECT count(*) FROM ayarlar").fetchone()[0] == 0:
        varsayilan_ayarlar = [
            ("Barkod_Onek", "OMG"),
            ("Para_Birimi", "TL"),
            ("KDV_Orani", "20"),
            ("Lobi_IP", "192.168.1.100"),
            ("Sms_Sessiz_Saatler", "22:00 - 08:00"),
            ("Kurye_Sablonu", "Sayın [Hekim_Adı],\nKurye talebiniz alınmıştır."),
            ("Sistem_Kilitli", "Hayır"),
            ("Kurumsal_Logo", "-"),
        ]
        c.executemany("INSERT INTO ayarlar (Ayar_Adi, Ayar_Degeri) VALUES (?, ?)", varsayilan_ayarlar)
        print("[ERP] Varsayılan ayarlar oluşturuldu.")
        
    # Varsayılan fiyat listesi (Boşsa doldur - Eski SQLite verilerinden)
    if c.execute("SELECT count(*) FROM fiyat_listesi").fetchone()[0] == 0:
        varsayilan_fiyatlar = [
            ('Multilayer Zirkonyum 5D Pro', 'ZİRKONYUM/ FULL SERAMİK RESTARASYONLAR', 36.0, 'EUR'),
            ('Multilayer Zirkonyum 3D Pro', 'ZİRKONYUM/ FULL SERAMİK RESTARASYONLAR', 30.0, 'EUR'),
            ('Multilayer Zirkonyum 4D Pro', 'ZİRKONYUM/ FULL SERAMİK RESTARASYONLAR', 34.0, 'EUR'),
            ('Zirkonyum Inley/Onlay', 'ZİRKONYUM/ FULL SERAMİK RESTARASYONLAR', 30.0, 'EUR'),
            ('Oklüzal Vidalı Zirkonyum', 'ZİRKONYUM/ FULL SERAMİK RESTARASYONLAR', 40.0, 'EUR'),
            ('İmplant Üzeri Zirkonyum', 'ZİRKONYUM/ FULL SERAMİK RESTARASYONLAR', 30.0, 'EUR'),
            ('Monolitik Zirkonyum', 'ZİRKONYUM/ FULL SERAMİK RESTARASYONLAR', 30.0, 'EUR'),
            ('Lazer Sinterleme Porselen', 'LAZER SİNTERLEME', 800.0, 'TL'),
            ('Lazer Sinterleme İmplant Üstü Porselen', 'LAZER SİNTERLEME', 875.0, 'TL'),
            ('Lazer Sinterleme Oklüzal Vidalı Porselen', 'LAZER SİNTERLEME', 1275.0, 'TL'),
            ('Lazer Sinterleme Dolder Bar (Tek Çene)', 'LAZER SİNTERLEME', 2900.0, 'TL'),
            ('Lazer Sinterleme Hibrit Bar (Tek Çene)', 'LAZER SİNTERLEME', 5300.0, 'TL'),
            ('E.Max Full Kron', 'FULL SERAMİK RESTARASYONLAR', 60.0, 'EUR'),
            ('E.Max Empress Laminate', 'FULL SERAMİK RESTARASYONLAR', 60.0, 'EUR'),
            ('Empress Inlay/Onlay', 'FULL SERAMİK RESTARASYONLAR', 60.0, 'EUR'),
            ('Kafes Döküm (Tek Çene)', 'İSKELET DÖKÜM PROTEZLER', 1100.0, 'TL'),
            ('İskelet Protez Lazer Sinter (Tek Çene)', 'İSKELET DÖKÜM PROTEZLER', 1600.0, 'TL'),
            ('Teleskop İskelet Protez Lazer Sinter (Tek Çene)', 'İSKELET DÖKÜM PROTEZLER', 1800.0, 'TL'),
            ('Kafes İlavesi', 'İSKELET DÖKÜM PROTEZLER', 300.0, 'TL'),
            ('Hassas Tutucu İskelet Lazer Sinter (Tek Çene)', 'İSKELET DÖKÜM PROTEZLER', 2000.0, 'TL'),
            ('Pivo Döküm', 'İSKELET DÖKÜM PROTEZLER', 550.0, 'TL'),
            ('Peek Bar (Tek Çene)', 'CAD/CAM MILLING', 200.0, 'EUR'),
            ('Titanyum Bar (Tek Çene)', 'CAD/CAM MILLING', 300.0, 'EUR'),
            ('Titanyum Toronto Milling (Tek Çene)', 'CAD/CAM MILLING', 350.0, 'EUR'),
            ('Hi-Impact-Acrly Total (Tek Çene)', 'HAREKETLİ PROTEZLER', 2800.0, 'TL'),
            ('Obturatör Total (Tek Çene)', 'HAREKETLİ PROTEZLER', 4500.0, 'TL'),
            ('Total Protez Tek Çenebitim (Tek Çene)', 'HAREKETLİ PROTEZLER', 2750.0, 'TL'),
            ('Parsiyel Protez Tek Çene Bitim (Tek Çene)', 'HAREKETLİ PROTEZLER', 2750.0, 'TL'),
            ('Immediyat (Total Parsiyel) (Tek Çene)', 'HAREKETLİ PROTEZLER', 3200.0, 'TL'),
            ('Işınlı Basplak (Tek Çene)', 'HAREKETLİ PROTEZLER', 200.0, 'TL'),
            ('Yumuşak Beslenme Molloplast (Tek Çene)', 'HAREKETLİ PROTEZLER', 5300.0, 'TL'),
            ('Işınlı Ölçü Kaşığı (Tek Çene)', 'HAREKETLİ PROTEZLER', 200.0, 'TL'),
            ('Total Beslenme (Tek Çene)', 'HAREKETLİ PROTEZLER', 750.0, 'TL'),
            ('Roch Köprü Protez (Tek Çene)', 'TAMİR PROTEZLER', 1650.0, 'TL'),
            ('Cad/Cam Pmma Geçici Kron', 'TAMİR PROTEZLER', 150.0, 'TL'),
            ('Cad/Cam Pmma Geçici İmmediat Yükleme', 'TAMİR PROTEZLER', 300.0, 'TL'),
            ('3D Printer Tam Model (Tek Çene)', 'TAMİR PROTEZLER', 420.0, 'TL'),
            ('Kapanış Geçicisi (Tek Çene)', 'TAMİR PROTEZLER', 900.0, 'TL'),
            ('Diş İlavesi', 'TAMİR PROTEZLER', 550.0, 'TL'),
            ('Porselen Tamiri', 'TAMİR PROTEZLER', 560.0, 'TL'),
            ('3D Printer Geçici Kron', 'TAMİR PROTEZLER', 150.0, 'TL'),
            ('3D Printer Yarım Model (Tek Çene)', 'TAMİR PROTEZLER', 280.0, 'TL'),
            ('Splint', 'ORTODONTİK APAREYLER', 3000.0, 'TL'),
            ('Aperey', 'ORTODONTİK APAREYLER', 1850.0, 'TL'),
            ('Aperey Vidalı (1 adet vida)', 'ORTODONTİK APAREYLER', 3000.0, 'TL'),
            ('Hareketli Yer Tutucu', 'ORTODONTİK APAREYLER', 1750.0, 'TL'),
            ('Hollama Plağı', 'ORTODONTİK APAREYLER', 3250.0, 'TL'),
            ('Sabit Yer Tutucu', 'ORTODONTİK APAREYLER', 1500.0, 'TL'),
            ('Ölçü Döküm (Tek Çene)', 'ÖZEL İŞLEMLER', 75.0, 'TL'),
            ('Mock-Up', 'ÖZEL İŞLEMLER', 125.0, 'TL'),
            ('Pattern Resin (Tek Çene)', 'ÖZEL İŞLEMLER', 600.0, 'TL'),
            ('Diş Eti İlavesi', 'ÖZEL İŞLEMLER', 1250.0, 'TL'),
            ('Gece Plağı', 'ORTODONTİK APAREYLER', 750.0, 'TL')
        ]
        c.executemany("INSERT INTO fiyat_listesi (Hizmet_Adi, Kategori, Fiyat, Para_Birimi) VALUES (?, ?, ?, ?)", varsayilan_fiyatlar)
        print("[ERP] Fiyat listesi eski yedekten otomatik oluşturuldu.")
        
    # Varsayılan BGS Blokları (Boşsa doldur - Eski SQLite verilerinden)
    if c.execute("SELECT count(*) FROM stok WHERE Kategori='Zirkonyum Blok'").fetchone()[0] == 0:
        bgs_bloklar = [
            ('BGS-5DML-12', 'BGS 5D ML 12mm', 'Zirkonyum Blok', 75.0),
            ('BGS-5DML-14', 'BGS 5D ML 14mm', 'Zirkonyum Blok', 80.0),
            ('BGS-5DML-16', 'BGS 5D ML 16mm', 'Zirkonyum Blok', 85.0),
            ('BGS-5DML-18', 'BGS 5D ML 18mm', 'Zirkonyum Blok', 90.0),
            ('BGS-5DML-20', 'BGS 5D ML 20mm', 'Zirkonyum Blok', 95.0),
            ('BGS-5DML-25', 'BGS 5D ML 25mm', 'Zirkonyum Blok', 100.0),
            ('BGS-4DML-12', 'BGS 4D ML 12mm', 'Zirkonyum Blok', 70.0),
            ('BGS-4DML-14', 'BGS 4D ML 14mm', 'Zirkonyum Blok', 75.0),
            ('BGS-4DML-16', 'BGS 4D ML 16mm', 'Zirkonyum Blok', 80.0),
            ('BGS-4DML-18', 'BGS 4D ML 18mm', 'Zirkonyum Blok', 85.0),
            ('BGS-4DML-20', 'BGS 4D ML 20mm', 'Zirkonyum Blok', 90.0),
            ('BGS-4DML-25', 'BGS 4D ML 25mm', 'Zirkonyum Blok', 95.0),
            ('BGS-3DPFS-12', 'BGS 3D PRO F.S 12mm', 'Zirkonyum Blok', 65.0),
            ('BGS-3DPFS-14', 'BGS 3D PRO F.S 14mm', 'Zirkonyum Blok', 70.0),
            ('BGS-3DPFS-16', 'BGS 3D PRO F.S 16mm', 'Zirkonyum Blok', 75.0),
            ('BGS-3DPFS-18', 'BGS 3D PRO F.S 18mm', 'Zirkonyum Blok', 80.0),
            ('BGS-3DPFS-20', 'BGS 3D PRO F.S 20mm', 'Zirkonyum Blok', 85.0),
            ('BGS-3DPFS-25', 'BGS 3D PRO F.S 25mm', 'Zirkonyum Blok', 90.0),
            ('BGS-3DPML-12', 'BGS 3D PRO ML 12mm', 'Zirkonyum Blok', 60.0),
            ('BGS-3DPML-14', 'BGS 3D PRO ML 14mm', 'Zirkonyum Blok', 65.0),
            ('BGS-3DPML-16', 'BGS 3D PRO ML 16mm', 'Zirkonyum Blok', 70.0),
            ('BGS-3DPML-18', 'BGS 3D PRO ML 18mm', 'Zirkonyum Blok', 75.0),
            ('BGS-3DPML-20', 'BGS 3D PRO ML 20mm', 'Zirkonyum Blok', 80.0),
            ('BGS-3DPML-25', 'BGS 3D PRO ML 25mm', 'Zirkonyum Blok', 85.0),
            ('BGS-3DML-12', 'BGS 3D ML 12mm', 'Zirkonyum Blok', 55.0),
            ('BGS-3DML-14', 'BGS 3D ML 14mm', 'Zirkonyum Blok', 60.0),
            ('BGS-3DML-16', 'BGS 3D ML 16mm', 'Zirkonyum Blok', 65.0),
            ('BGS-3DML-18', 'BGS 3D ML 18mm', 'Zirkonyum Blok', 70.0),
            ('BGS-3DML-20', 'BGS 3D ML 20mm', 'Zirkonyum Blok', 75.0),
            ('BGS-3DML-25', 'BGS 3D ML 25mm', 'Zirkonyum Blok', 80.0),
            ('BGS-STML-12', 'BGS ST ML 12mm', 'Zirkonyum Blok', 55.0),
            ('BGS-STML-14', 'BGS ST ML 14mm', 'Zirkonyum Blok', 60.0),
            ('BGS-STML-16', 'BGS ST ML 16mm', 'Zirkonyum Blok', 65.0),
            ('BGS-STML-18', 'BGS ST ML 18mm', 'Zirkonyum Blok', 70.0),
            ('BGS-STML-20', 'BGS ST ML 20mm', 'Zirkonyum Blok', 75.0),
            ('BGS-STML-25', 'BGS ST ML 25mm', 'Zirkonyum Blok', 80.0),
            ('BGS-STC-12', 'BGS ST-C 12mm', 'Zirkonyum Blok', 30.0),
            ('BGS-STC-14', 'BGS ST-C 14mm', 'Zirkonyum Blok', 35.0),
            ('BGS-STC-16', 'BGS ST-C 16mm', 'Zirkonyum Blok', 40.0),
            ('BGS-STC-18', 'BGS ST-C 18mm', 'Zirkonyum Blok', 45.0),
            ('BGS-STC-20', 'BGS ST-C 20mm', 'Zirkonyum Blok', 50.0),
            ('BGS-STC-25', 'BGS ST-C 25mm', 'Zirkonyum Blok', 55.0),
            ('BGS-UTC-12', 'BGS UT-C 12mm', 'Zirkonyum Blok', 30.0),
            ('BGS-UTC-14', 'BGS UT-C 14mm', 'Zirkonyum Blok', 35.0),
            ('BGS-UTC-16', 'BGS UT-C 16mm', 'Zirkonyum Blok', 40.0),
            ('BGS-UTC-18', 'BGS UT-C 18mm', 'Zirkonyum Blok', 45.0),
            ('BGS-UTC-20', 'BGS UT-C 20mm', 'Zirkonyum Blok', 50.0),
            ('BGS-UTC-25', 'BGS UT-C 25mm', 'Zirkonyum Blok', 55.0),
            ('BGS-SHT-12', 'BGS SHT 12mm', 'Zirkonyum Blok', 30.0),
            ('BGS-SHT-14', 'BGS SHT 14mm', 'Zirkonyum Blok', 35.0),
            ('BGS-SHT-16', 'BGS SHT 16mm', 'Zirkonyum Blok', 40.0),
            ('BGS-SHT-18', 'BGS SHT 18mm', 'Zirkonyum Blok', 45.0),
            ('BGS-SHT-20', 'BGS SHT 20mm', 'Zirkonyum Blok', 50.0),
            ('BGS-SHT-25', 'BGS SHT 25mm', 'Zirkonyum Blok', 55.0),
            ('BGS-ST-12', 'BGS ST 12mm', 'Zirkonyum Blok', 25.0),
            ('BGS-ST-14', 'BGS ST 14mm', 'Zirkonyum Blok', 30.0),
            ('BGS-ST-16', 'BGS ST 16mm', 'Zirkonyum Blok', 35.0),
            ('BGS-ST-18', 'BGS ST 18mm', 'Zirkonyum Blok', 40.0),
            ('BGS-ST-20', 'BGS ST 20mm', 'Zirkonyum Blok', 45.0),
            ('BGS-ST-25', 'BGS ST 25mm', 'Zirkonyum Blok', 50.0),
            ('BGS-UT-12', 'BGS UT 12mm ', 'Zirkonyum Blok', 25.0),
            ('BGS-UT-14', 'BGS UT 14mm ', 'Zirkonyum Blok', 30.0),
            ('BGS-UT-16', 'BGS UT 16mm ', 'Zirkonyum Blok', 35.0),
            ('BGS-UT-18', 'BGS UT 18mm ', 'Zirkonyum Blok', 40.0),
            ('BGS-UT-20', 'BGS UT 20mm ', 'Zirkonyum Blok', 45.0),
            ('BGS-UT-25', 'BGS UT 25mm ', 'Zirkonyum Blok', 50.0),
            ('BGS-HT-12', 'BGS HT 12mm', 'Zirkonyum Blok', 20.0),
            ('BGS-HT-14', 'BGS HT 14mm', 'Zirkonyum Blok', 25.0),
            ('BGS-HT-16', 'BGS HT 16mm', 'Zirkonyum Blok', 30.0),
            ('BGS-HT-18', 'BGS HT 18mm', 'Zirkonyum Blok', 35.0),
            ('BGS-HT-20', 'BGS HT 20mm', 'Zirkonyum Blok', 40.0),
            ('BGS-HT-25', 'BGS HT 25mm', 'Zirkonyum Blok', 45.0)
        ]
        # Insert them into stok
        c.executemany("INSERT INTO stok (Urun_Kodu, Urun_Adi, Kategori, Satis_Fiyati, Mevcut_Miktar, Birim, Kritik_Sinir, Durum) VALUES (?, ?, ?, ?, 0.0, 'Adet', 5.0, 'Aktif')", bgs_bloklar)
        print("[ERP] BGS Blok listesi eski yedekten otomatik oluşturuldu.")
    
    conn.commit()
    conn.close()
    print("[ERP] Ana veritabanı hazır.")


def uploads_klasoru_kur():
    """Gerekli klasörleri oluştur."""
    klasorler = [
        "uploads",
        "uploads/cihazlar",
        "uploads/qrcodes",
        "uploads/personel",
        "uploads/personel/fotolar",
        "uploads/personel/cvler",
        "uploads/kurumsal",
    ]
    for klasor in klasorler:
        os.makedirs(klasor, exist_ok=True)
    print("[Sistem] Klasör yapısı hazır.")


if __name__ == "__main__":
    print("OMG Smile Veritabanı Kurulum Başlıyor...")
    uploads_klasoru_kur()
    dentflow_db_kur()
    omg_erp_db_kur()
    print("\n✅ Tüm veritabanları başarıyla kuruldu!")
    print("Şimdi 'streamlit run ana_program.py' ile uygulamayı başlatabilirsiniz.")
