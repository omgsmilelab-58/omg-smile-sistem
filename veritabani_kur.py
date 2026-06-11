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
                  grup_id INTEGER, icerik TEXT, zaman TIMESTAMP, 
                  okundu INTEGER DEFAULT 0, tip TEXT DEFAULT 'sohbet')''')
    c.execute('''CREATE TABLE IF NOT EXISTS gruplar 
                 (id SERIAL PRIMARY KEY, 
                  grup_adi TEXT, kurucu_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS grup_uyeleri 
                 (grup_id INTEGER, kullanici_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS okunan_duyurular 
                 (kullanici_id TEXT, duyuru_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sistem_loglari 
                 (Tarih_Saat TEXT, Kullanici TEXT, Aksiyon TEXT, Goruldu INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS engellemeler 
                 (engelleyen_id TEXT, engellenen_id TEXT)''')
    
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
        '''CREATE TABLE IF NOT EXISTS cariler 
           (Klinik_Unvani TEXT, Yetkili_Kisi TEXT, Telefon TEXT, Email TEXT, 
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
        
        '''CREATE TABLE IF NOT EXISTS isler 
           (Tarih TEXT, Klinik_Unvani TEXT, Hasta_Adi TEXT, Is_Turu TEXT, 
            Renk TEXT, Asama TEXT, Tutar_TL REAL DEFAULT 0.0, 
            Sorumlu_Personel TEXT DEFAULT '-', Harcanan_Malzeme TEXT DEFAULT '-', 
            Teslim_Tarihi TEXT DEFAULT '2026-01-01', Barkod TEXT DEFAULT '-', 
            Lot_Numarasi TEXT DEFAULT '-', Sertifika_No TEXT DEFAULT '-',
            Aciklama TEXT DEFAULT '-')''',
        
        '''CREATE TABLE IF NOT EXISTS stok 
           (Urun_Kodu TEXT, Urun_Adi TEXT, Kategori TEXT, Mevcut_Miktar REAL, 
            Birim TEXT, Kritik_Sinir REAL, Satis_Fiyati REAL, Durum TEXT DEFAULT 'Aktif')''',
        
        '''CREATE TABLE IF NOT EXISTS fiyat_listesi 
           (Hizmet_Adi TEXT, Kategori TEXT, Fiyat REAL, Para_Birimi TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS personeller 
           (Ad_Soyad TEXT, Gorevi TEXT, Telefon TEXT, Maas REAL, 
            Baslama_Tarihi TEXT, Ayrilma_Tarihi TEXT, Durum TEXT,
            TC_No TEXT DEFAULT '-', Email TEXT DEFAULT '-',
            Adres TEXT DEFAULT '-', IBAN TEXT DEFAULT '-',
            Kalan_Izin INTEGER DEFAULT 14,
            Foto_Yolu TEXT DEFAULT '-', CV_Yolu TEXT DEFAULT '-')''',
        
        '''CREATE TABLE IF NOT EXISTS kullanicilar 
           (Kullanici_Adi TEXT, Sifre TEXT, Rol TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS giderler 
           (Tarih TEXT, Kategori TEXT, Aciklama TEXT, Tutar REAL)''',
        
        '''CREATE TABLE IF NOT EXISTS tahsilatlar 
           (Tarih TEXT, Klinik_Unvani TEXT, Odeme_Turu TEXT, Tutar REAL, Aciklama TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS is_fotograflari 
           (Is_ID INTEGER, Dosya_Yolu TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS is_3d_modelleri 
           (Is_ID INTEGER, Dosya_Yolu TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS cihazlar 
           (Cihaz_Adi TEXT, Kategori TEXT, Calisma_Saati REAL DEFAULT 0, 
            Bakim_Siniri REAL DEFAULT 500, Son_Bakim_Tarihi TEXT, 
            Durum TEXT DEFAULT 'Aktif', Gorsel_Yolu TEXT DEFAULT '-',
            Haftalik_Hedef TEXT, Aylik_Hedef TEXT, Yillik_Hedef TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS cihaz_bakim_gecmisi 
           (Cihaz_Adi TEXT, Tarih TEXT, Islem TEXT, Maliyet REAL DEFAULT 0, Aciklama TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS kurye_islemleri 
           (Tarih TEXT, Saat TEXT DEFAULT '00:00', Klinik_Unvani TEXT, 
            Aciklama TEXT, Durum TEXT DEFAULT 'Bekliyor')''',
        
        '''CREATE TABLE IF NOT EXISTS cam_bloklar 
           (Blok_Kodu TEXT, Urun_Adi TEXT, Boyut_Renk TEXT, 
            Kapasite_Uye INTEGER, Kalan_Uye INTEGER, Durum TEXT DEFAULT 'Yarım')''',
        
        '''CREATE TABLE IF NOT EXISTS cam_frezler 
           (Frez_Kodu TEXT, Urun_Adi TEXT, Uyumlu_Makine TEXT, 
            Max_Omur_Dk INTEGER, Kalan_Omur_Dk INTEGER, Durum TEXT DEFAULT 'Aktif')''',
        
        '''CREATE TABLE IF NOT EXISTS ayarlar 
           (Ayar_Adi TEXT PRIMARY KEY, Ayar_Degeri TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS personel_finans 
           (Tarih TEXT, Personel_Adi TEXT, Islem_Turu TEXT, Tutar REAL, Aciklama TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS personel_izinler 
           (Tarih TEXT, Personel_Adi TEXT, Baslangic_Tarihi TEXT, 
            Bitis_Tarihi TEXT, Gun_Sayisi INTEGER, Aciklama TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS klinik_asistanlari 
           (Klinik_Unvani TEXT, Asistan_Kadi TEXT PRIMARY KEY, Sifre TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS laboratuvar_dokumanlari 
           (Tarih TEXT, Dokuman_Adi TEXT, Dosya_Yolu TEXT, Dosya_Turu TEXT)''',
        
        '''CREATE TABLE IF NOT EXISTS sistem_loglari 
           (Tarih_Saat TEXT, Kullanici TEXT, Aksiyon TEXT, Goruldu INTEGER)''',
        
        '''CREATE TABLE IF NOT EXISTS mesajlar 
           (Tarih_Saat TEXT, Gonderen TEXT, Alici TEXT, Mesaj TEXT, Okundu INTEGER)''',
        
        '''CREATE TABLE IF NOT EXISTS aktif_frezler 
           (id SERIAL PRIMARY KEY, makine_adi TEXT, yuva_no TEXT,
            frez_kod TEXT, frez_adi TEXT, toplam_omur_dk INTEGER, 
            kullanilan_dk INTEGER, birim_fiyat_euro REAL, durum TEXT)''',
    ]
    
    for tablo_sql in tablolar:
        c.execute(tablo_sql)
    
    # Admin kullanıcısı yoksa oluştur
    if c.execute("SELECT count(*) FROM kullanicilar").fetchone()[0] == 0:
        c.execute("INSERT INTO kullanicilar VALUES ('tamer', 'admin123', 'Admin')")
        c.execute("INSERT INTO kullanicilar VALUES ('kurye', '1234', 'Kurye')")
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
        c.executemany("INSERT OR REPLACE INTO ayarlar VALUES (?, ?)", varsayilan_ayarlar)
        print("[ERP] Varsayılan ayarlar oluşturuldu.")
    
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
