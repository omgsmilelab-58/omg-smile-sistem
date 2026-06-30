from dotenv import load_dotenv
load_dotenv()
# Not: 'from click import style' kaldırıldı - kullanılmıyor ve requirements.txt'de yok
import streamlit as st
import pandas as pd
import sqlite3
import db_baglanti
import storage_utils
import os
import io
import urllib.parse
import textwrap
import qrcode
import base64
from PIL import Image
from datetime import datetime, timedelta
from fpdf import FPDF
import plotly.graph_objects as go
import plotly.express as px
try:
    from stl import mesh
except ImportError:
    mesh = None  # numpy-stl kurulu değilse STL özellikleri devre dışı
import numpy as np
import re
import xml.etree.ElementTree as ET
import urllib.request

def tcmb_kur_getir(doviz_cinsi='EUR'):
    import ssl
    import json
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        url = "https://www.tcmb.gov.tr/kurlar/today.xml"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3, context=ctx) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        for currency in root.findall('Currency'):
            if currency.get('CurrencyCode') == doviz_cinsi:
                return float(currency.find('ForexSelling').text)
    except Exception:
        pass
        
    try:
        # TCMB başarısız olursa alternatif bir API kullan (Google Cloud Run TCMB'yi engelleyebiliyor)
        alt_url = "https://api.exchangerate-api.com/v4/latest/" + doviz_cinsi
        req2 = urllib.request.Request(alt_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req2, timeout=3, context=ctx) as response2:
            data = json.loads(response2.read().decode('utf-8'))
            return float(data['rates']['TRY'])
    except Exception:
        pass
        
    return None

# --- YÖNETİCİ READ-ONLY YAMASI ---
from streamlit.delta_generator import DeltaGenerator

if not hasattr(DeltaGenerator, '_is_patched_for_readonly'):
    orig_button = DeltaGenerator._button
    orig_form_submit_button = DeltaGenerator._form_submit_button
    DeltaGenerator._is_patched_for_readonly = True

    def read_only_button(self, label=None, key=None, help=None, *args, **kwargs):
        izin_verilenler = ["Çıkış", "Terk Et", "Dön", "Cevabını Gör", "İndir", "Yazdır"]
        if st.session_state.get('kullanici_rolu') == 'Yönetici':
            _lbl = str(label)
            if not any(izin in _lbl for izin in izin_verilenler):
                kwargs['disabled'] = True
                help = "Yönetici rolü sadece görüntüleme yetkisine sahiptir. İşlem yapamaz."
        return orig_button(self, label, key, help, *args, **kwargs)

    def read_only_form_submit_button(self, label="Submit", help=None, *args, **kwargs):
        if st.session_state.get('kullanici_rolu') == 'Yönetici':
            kwargs['disabled'] = True
            help = "Yönetici rolü sadece görüntüleme yetkisine sahiptir. İşlem yapamaz."
        return orig_form_submit_button(self, label, help, *args, **kwargs)

    DeltaGenerator._button = read_only_button
    DeltaGenerator._form_submit_button = read_only_form_submit_button
# ----------------------------------

# ╔══════════════════════════════════════════════════════╗
# ║  BULUT BOOTSTRAP: Veritabanı ve klasörleri kur       ║
# ║  Cloud ortamında db dosyaları olmadan başlar,         ║
# ║  bu blok her şeyi sıfırdan oluşturur.                ║
# ╚══════════════════════════════════════════════════════╝
try:
    import veritabani_kur
    veritabani_kur.uploads_klasoru_kur()
    veritabani_kur.dentflow_db_kur()
    veritabani_kur.omg_erp_db_kur()
except Exception as _bootstrap_err:
    # Yerel ortamda db zaten varsa hata vermeden devam et
    pass

# --- Dosyalar İçin Klasör Oluşturma ---
if not os.path.exists("uploads"): os.makedirs("uploads")
if not os.path.exists("uploads/cihazlar"): os.makedirs("uploads/cihazlar")
if not os.path.exists("uploads/qrcodes"): os.makedirs("uploads/qrcodes")

# --- Personel Dosyaları İçin Klasörler ---
if not os.path.exists("uploads/personel"): os.makedirs("uploads/personel")
if not os.path.exists("uploads/personel/fotolar"): os.makedirs("uploads/personel/fotolar")
if not os.path.exists("uploads/personel/cvler"): os.makedirs("uploads/personel/cvler")

# --- Sayfa Ayarları ---
st.set_page_config(page_title="Omg Smile - Dijital Ekosistem", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# 🧠 DENTFLOW VERİTABANI MOTORU 🧠
# ==========================================

@st.cache_resource 
def dentflow_db_kur():
    conn = db_baglanti.get_connection('dentflow.db', check_same_thread=False)
    c = conn.cursor()
    
    # 1. Tabloları Oluştur (EKSİK OLAN MESAJLAR TABLOSU EKLENDİ!)
    c.execute('''CREATE TABLE IF NOT EXISTS klinikler (id INTEGER PRIMARY KEY, isim TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS kullanicilar (id INTEGER PRIMARY KEY, kullanici_adi TEXT, isim TEXT, sifre TEXT, rol TEXT, klinik_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS mesajlar (id INTEGER PRIMARY KEY, gonderen_id INTEGER, alici_id INTEGER, grup_id INTEGER, icerik TEXT, zaman TIMESTAMP, okundu INTEGER DEFAULT 0, tip TEXT DEFAULT 'sohbet')''')
    
    # 2. Eğer veritabanı boşsa örnek kişileri ekle
    c.execute("SELECT COUNT(*) FROM kullanicilar")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO klinikler (isim) VALUES ('Omg Smile Lab'), ('Dent58'), ('Çınar Klinik')")
        # Lab Personeli (Admin)
        c.execute("INSERT INTO kullanicilar (kullanici_adi, isim, sifre, rol, klinik_id) VALUES ('tamer', 'Tamer Köseoğlu', '123', 'lab', 1)")
        # Dent58 Personelleri
        c.execute("INSERT INTO kullanicilar (kullanici_adi, isim, sifre, rol, klinik_id) VALUES ('ayse', 'Dt. Ayşe Yılmaz', '123', 'doktor', 2)")
        c.execute("INSERT INTO kullanicilar (kullanici_adi, isim, sifre, rol, klinik_id) VALUES ('ahmet', 'Ahmet', '123', 'asistan', 2)")
        # Çınar Klinik Personeli
        c.execute("INSERT INTO kullanicilar (kullanici_adi, isim, sifre, rol, klinik_id) VALUES ('fatma', 'Dt. Fatma Acar', '123', 'doktor', 3)")
    conn.commit()
    conn.close()
    return True

def okuma_tablosunu_kur():
    conn = db_baglanti.get_connection('dentflow.db')
    c = conn.cursor()
    # Hangi kullanıcı, hangi duyuruyu okudu? Tablosu
    c.execute("CREATE TABLE IF NOT EXISTS okunan_duyurular (id SERIAL PRIMARY KEY, kullanici_id TEXT, duyuru_id INTEGER)")
    conn.commit()
    conn.close()

# Uygulama başlarken bir kez çalıştır
try:
    okuma_tablosunu_kur()
except Exception as e:
    print(f"okuma_tablosunu_kur() hatasi: {e}")

def grup_olustur(grup_adi, kurucu_id, secilen_kisiler):
    # Veritabanına bağlan
    conn = db_baglanti.get_connection('dentflow.db') # Senin DB adın neyse o
    cursor = conn.cursor()
    
    try:
        # 1. Önce "bütünü" yani Grubu yaratıyoruz
        cursor.execute("INSERT INTO gruplar (grup_adi, kurucu_id) VALUES (?, ?)", (grup_adi, kurucu_id))
        
        # 2. Yeni kurulan bu grubun eşsiz ID'sini çekiyoruz
        yeni_grup_id = cursor.lastrowid
        
        # 3. Seçilen kişileri (kurucu dahil) teker teker bu grubun içine atıyoruz
        for kisi_id in secilen_kisiler:
            cursor.execute("INSERT INTO grup_uyeleri (grup_id, kullanici_id) VALUES (?, ?)", (yeni_grup_id, kisi_id))
            
        # İşlemleri onayla ve kaydet
        conn.commit()
        return True
        
    except Exception as e:
        print(f"Grup kurma hatası: {e}")
        conn.rollback() # Hata olursa işlemi geri al, veritabanı çökmesin
        return False
        
    finally:
        conn.close()

# Sistemi yormadan DB'yi sadece 1 kez çalıştır
_ = dentflow_db_kur()


def sohbet_listesi_getir(aktif_kullanici_adi):
    conn = db_baglanti.get_connection('dentflow.db')
    c = conn.cursor()
    
    # 🚨 KRİTİK ÇÖZÜM: EĞER TABLOLAR YOKSA OTOMATİK YARAT (Çökmeyi Engeller) 🚨
    c.execute('''CREATE TABLE IF NOT EXISTS gruplar (id SERIAL PRIMARY KEY, grup_adi TEXT, kurucu_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS grup_uyeleri (id SERIAL PRIMARY KEY, grup_id INTEGER, kullanici_id INTEGER)''')
    conn.commit()
    
    # 1. Önce aktif kullanıcının bilgilerini ve ID'sini çekiyoruz
    c.execute("SELECT id, rol, klinik_id FROM kullanicilar WHERE kullanici_adi=?", (aktif_kullanici_adi,))
    kullanici_bilgisi = c.fetchone()
    
    if not kullanici_bilgisi:
        conn.close()
        return pd.DataFrame()
        
    benim_id, rol, klinik_id = kullanici_bilgisi
    
    # 2. NORMAL KULLANICILARI ÇEK (Senin orijinal mantığın)
    if rol == 'lab':
        query = """
        SELECT u.id, u.isim, k.isim as klinik_ismi, u.rol 
        FROM kullanicilar u 
        LEFT JOIN klinikler k ON u.klinik_id = k.id
        WHERE u.kullanici_adi != ?
        """
        params = (aktif_kullanici_adi,)
    else:
        query = """
        SELECT u.id, u.isim, k.isim as klinik_ismi, u.rol 
        FROM kullanicilar u 
        LEFT JOIN klinikler k ON u.klinik_id = k.id
        WHERE u.kullanici_adi != ? AND (u.rol = 'lab' OR u.klinik_id = ?)
        """
        params = (aktif_kullanici_adi, klinik_id)
        
    df_users = pd.read_sql_query(query, conn, params=params)
    
    # ID'leri metne çeviriyoruz (Gruplarla çakışmasın diye)
    df_users['id'] = df_users['id'].astype(str)
    
    # 3. ÜYESİ OLDUĞUM GRUPLARI ÇEK
    group_query = """
    SELECT g.id, g.grup_adi as isim, '' as klinik_ismi, 'grup' as rol 
    FROM gruplar g
    JOIN grup_uyeleri gu ON g.id = gu.grup_id
    WHERE gu.kullanici_id = ?
    """
    df_groups = pd.read_sql_query(group_query, conn, params=(benim_id,))
    
    # 🚨 Grup ID'lerinin başına 'g_' ekliyoruz (Örn: g_5) - Sistem karışmasın diye!
    if not df_groups.empty:
        df_groups['id'] = 'g_' + df_groups['id'].astype(str)
    
    # 4. İKİ LİSTEYİ BİRLEŞTİR VE GÖNDER
    if not df_groups.empty:
        df_final = pd.concat([df_users, df_groups], ignore_index=True)
    else:
        df_final = df_users

    conn.close()
    return df_final

def duyuru_ekle(kullanici_adi, icerik):
    conn = db_baglanti.get_connection('dentflow.db')
    c = conn.cursor()
    c.execute("SELECT id FROM kullanicilar WHERE kullanici_adi=?", (kullanici_adi,))
    gonderen = c.fetchone()
    if gonderen:
        gonderen_id = gonderen[0]
        zaman = datetime.now().strftime("%H:%M - %d.%m.%Y")
        c.execute("INSERT INTO mesajlar (gonderen_id, icerik, zaman, tip) VALUES (?, ?, ?, 'duyuru')", (gonderen_id, icerik, zaman))
        conn.commit()
    conn.close()

def duyurulari_getir():
    conn = db_baglanti.get_connection('dentflow.db')
    query = """
    SELECT m.icerik, m.zaman, u.isim as yazar 
    FROM mesajlar m 
    JOIN kullanicilar u ON m.gonderen_id = u.id 
    WHERE m.tip = 'duyuru' 
    ORDER BY m.id DESC
    """
    try:
        df = pd.read_sql_query(query, conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df

def duyuru_okundu_isaretle_db(kullanici_id, duyuru_id):
    conn = db_baglanti.get_connection('dentflow.db')
    c = conn.cursor()
    # Mükerrer kaydı önlemek için önce kontrol et
    c.execute("SELECT * FROM okunan_duyurular WHERE kullanici_id = ? AND duyuru_id = ?", (str(kullanici_id), duyuru_id))
    if not c.fetchone():
        c.execute("INSERT INTO okunan_duyurular (kullanici_id, duyuru_id) VALUES (?, ?)", (str(kullanici_id), duyuru_id))
    conn.commit()
    conn.close()

def aktif_id_bul(kullanici_adi):
    conn = db_baglanti.get_connection('dentflow.db')
    c = conn.cursor()
    c.execute("SELECT id FROM kullanicilar WHERE kullanici_adi=?", (kullanici_adi,))
    sonuc = c.fetchone()
    conn.close()
    return sonuc[0] if sonuc else None

def sohbet_mesajlarini_getir(benim_id, karsi_id):
    conn = db_baglanti.get_connection('dentflow.db')
    benim_str = str(benim_id).strip()
    karsi_str = str(karsi_id).strip()

    if karsi_str.startswith('g_'):
        query = """
        SELECT m.id, m.gonderen_id, m.alici_id, m.icerik, m.zaman, m.okundu, u.isim as gonderen_isim 
        FROM mesajlar m 
        LEFT JOIN kullanicilar u ON TRIM(CAST(m.gonderen_id AS TEXT)) = TRIM(CAST(u.id AS TEXT)) 
        WHERE TRIM(CAST(m.alici_id AS TEXT)) = ? 
        ORDER BY m.id ASC
        """
        params = (karsi_str,)
    else:
        # Sistem mesajlarını da iki tarafın görebileceği şekilde çekiyoruz
        query = """
        SELECT m.id, m.gonderen_id, m.alici_id, m.icerik, m.zaman, m.okundu, '' as gonderen_isim 
        FROM mesajlar m 
        WHERE 
        (TRIM(CAST(m.gonderen_id AS TEXT)) = ? AND TRIM(CAST(m.alici_id AS TEXT)) = ?) 
        OR (TRIM(CAST(m.gonderen_id AS TEXT)) = ? AND TRIM(CAST(m.alici_id AS TEXT)) = ?) 
        OR (TRIM(CAST(m.gonderen_id AS TEXT)) = 'system' AND (TRIM(CAST(m.alici_id AS TEXT)) = ? OR TRIM(CAST(m.alici_id AS TEXT)) = ?))
        ORDER BY m.id ASC
        """
        params = (benim_str, karsi_str, karsi_str, benim_str, karsi_str, benim_str)
        
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def mesajlari_okundu_isaretle(benim_id, karsi_id):
    conn = db_baglanti.get_connection('dentflow.db')
    c = conn.cursor()
    ben_str = str(benim_id).strip()
    karsi_str = str(karsi_id).strip()
    
    if karsi_str.startswith('g_'):
        # 🚨 GRUP BİLDİRİMLERİNİ SÖNDÜREN MOTOR (Artık Çalışıyor!) 🚨
        c.execute("UPDATE mesajlar SET okundu = 1 WHERE TRIM(CAST(alici_id AS TEXT)) = ? AND TRIM(CAST(gonderen_id AS TEXT)) != ? AND okundu = 0", (karsi_str, ben_str))
    else:
        c.execute("UPDATE mesajlar SET okundu = 1 WHERE TRIM(CAST(alici_id AS TEXT)) = ? AND TRIM(CAST(gonderen_id AS TEXT)) = ? AND okundu = 0", (ben_str, karsi_str))
        
    conn.commit()
    conn.close()

def okunmamis_mesaj_sayisi_getir(benim_id, karsi_id, c=None):
    kendi_baglantisi = False
    if c is None:
        conn = db_baglanti.get_connection('dentflow.db')
        c = conn.cursor()
        kendi_baglantisi = True
        
    benim_str = str(benim_id).strip()
    karsi_str = str(karsi_id).strip()
    
    if karsi_str.startswith('g_'):
        # Grup için sadece okundu=0 olanları say
        c.execute("SELECT COUNT(*) FROM mesajlar WHERE TRIM(CAST(alici_id AS TEXT)) = ? AND TRIM(CAST(gonderen_id AS TEXT)) != ? AND okundu = 0", (karsi_str, benim_str))
    else:
        # 🚨 Sadece okundu=0 olan gerçek mesajları say. Hayaletlere (-1) bakma bile! 🚨
        c.execute("SELECT COUNT(*) FROM mesajlar WHERE TRIM(CAST(gonderen_id AS TEXT)) = ? AND TRIM(CAST(alici_id AS TEXT)) = ? AND okundu = 0", (karsi_str, benim_str))
        
    sayi = c.fetchone()[0]
    
    if kendi_baglantisi:
        conn.close()
    return sayi

def toplam_okunmamis_sayisi_getir(benim_id):
    try:
        conn = db_baglanti.get_connection('dentflow.db')
        c = conn.cursor()
        ben_str = str(benim_id).strip()
        
        # 🚨 TEMİZLİK OPERASYONU: 
        # Bana gelen tüm 'system' mesajlarını otomatik olarak okundu (1) yap. 
        # Çünkü bunlar sistem uyarısıdır, ayrı bir sohbet odaları yoktur, asılı kalmasınlar!
        c.execute("UPDATE mesajlar SET okundu = 1 WHERE TRIM(CAST(alici_id AS TEXT)) = ? AND gonderen_id = 'system'", (ben_str,))
        conn.commit()

        # 1. Birebir Mesajlar: Sadece gerçek kullanıcılardan gelen ve hayalet olmayan (-1 değil) mesajları say
        c.execute("""
            SELECT COUNT(*) FROM mesajlar 
            WHERE TRIM(CAST(alici_id AS TEXT)) = ? 
            AND okundu = 0 
            AND gonderen_id != 'system'
        """, (ben_str,))
        birebir_sayi = c.fetchone()[0]
        
        # 2. Grup Mesajları: Benim atmadığım, okundu=0 olan grup mesajlarını say
        c.execute("""
            SELECT COUNT(m.id) FROM mesajlar m
            JOIN grup_uyeleri gu ON TRIM(CAST(m.alici_id AS TEXT)) = 'g_' || TRIM(CAST(gu.grup_id AS TEXT))
            WHERE TRIM(CAST(gu.kullanici_id AS TEXT)) = ? 
            AND TRIM(CAST(m.gonderen_id AS TEXT)) != ? 
            AND m.okundu = 0
            AND m.gonderen_id != 'system'
        """, (ben_str, ben_str))
        
        grup_f_res = c.fetchone()
        grup_sayi = grup_f_res[0] if grup_f_res else 0
        
        conn.close()
        return birebir_sayi + grup_sayi
    except Exception as e:
        return 0

def ozel_mesaj_gonder(benim_id, karsi_id, icerik):
    conn = db_baglanti.get_connection('dentflow.db')
    c = conn.cursor()
    from datetime import datetime
    zaman = datetime.now().strftime("%H:%M")
    
    # Her şeyi TRIM() ve str() ile zırhladık
    c.execute("INSERT INTO mesajlar (gonderen_id, alici_id, icerik, zaman, okundu) VALUES (?, ?, ?, ?, ?)",
              (str(benim_id).strip(), str(karsi_id).strip(), str(icerik).strip(), zaman, 0))
    conn.commit()
    conn.close()

def son_mesaji_getir(benim_id, karsi_id, c=None):
    kendi_baglantisi = False
    if c is None:
        conn = db_baglanti.get_connection('dentflow.db')
        c = conn.cursor()
        kendi_baglantisi = True
        
    benim_str = str(benim_id).strip()
    karsi_str = str(karsi_id).strip()
    
    if karsi_str.startswith('g_'):
        # Gruplar için mantık aynı kalıyor
        query = """
        SELECT u.isim, m.icerik, m.zaman 
        FROM mesajlar m 
        LEFT JOIN kullanicilar u ON TRIM(CAST(m.gonderen_id AS TEXT)) = TRIM(CAST(u.id AS TEXT)) 
        WHERE TRIM(CAST(m.alici_id AS TEXT)) = ? 
        ORDER BY m.id DESC LIMIT 1
        """
        params = (karsi_str,)
    else:
        # 🚨 KRİTİK DÜZELTME: Bana gelen mesajlarda okundu=-1 (Hayalet) olanları preview'da gösterme! 🚨
        query = """
        SELECT '' as isim, icerik, zaman FROM mesajlar 
        WHERE 
        (TRIM(CAST(gonderen_id AS TEXT)) = ? AND TRIM(CAST(alici_id AS TEXT)) = ?) 
        OR 
        (TRIM(CAST(gonderen_id AS TEXT)) = ? AND TRIM(CAST(alici_id AS TEXT)) = ? AND okundu != -1) 
        ORDER BY id DESC LIMIT 1
        """
        params = (benim_str, karsi_str, karsi_str, benim_str)
        
    c.execute(query, params)
    res = c.fetchone()
    
    if kendi_baglantisi:
        conn.close()
        
    if res:
        isim_on_eki = f"{res[0]}: " if res[0] else ""
        return f"{isim_on_eki}{res[1]}", res[2]
    return "Henüz mesaj yok", ""
# ==========================================
# 💎 V3.6 TAM DONANIMLI, GÜVENLİ VE OTOPİLOTLU SÜRÜM 💎
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800;900&display=swap');
        
        html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
        .stApp { background-color: #0f172a; color: #FFFFFF; background-image: radial-gradient(circle at 50% 0%, #1e3a8a 0%, #0f172a 60%); background-attachment: fixed; }
        h1, h2, h3, h4, h5, h6, label, p, span, div { color: #FFFFFF; }
        
        header[data-testid="stHeader"] { background-color: transparent !important; }
        .block-container {padding-top: 2rem !important; padding-bottom: 1rem !important;}
        
        /* 💎 EN ALTTAKİ BEYAZ ŞERİTİ VE İNATÇI BOŞLUKLARI KÖKTEN YOK ET 💎 */
        footer { display: none !important; visibility: hidden !important; }
        div[data-testid="stBottom"], div[data-testid="stBottom"] > div, div[data-testid="stBottomBlockContainer"] { background-color: transparent !important; background: transparent !important; }
        html, body { background-color: #0f172a !important; }
        
        /* Sidebar Ayarları */
        [data-testid="stSidebar"] { background-color: rgba(15, 23, 42, 0.85) !important; backdrop-filter: blur(15px); border-right: 1px solid rgba(56, 189, 248, 0.15) !important; }
        [data-testid="stSidebarNav"] {display: none;}
        [data-testid="collapsedControl"] svg, [data-testid="stSidebarCollapseButton"] svg { fill: #FFFFFF !important; color: #FFFFFF !important; }
        
        /* 🚀 Glassmorphism Kartları (GPU Optimize Edilmiş - Ghosting Giderildi) */
        .glass-card {
            background: rgba(15, 23, 42, 0.6); 
            backdrop-filter: blur(8px); /* Bulanıklık 12'den 8'e düşürüldü, performansı %50 artırır */
            -webkit-backdrop-filter: blur(8px);
            border-radius: 16px; 
            border: 1px solid rgba(56, 189, 248, 0.2); 
            padding: 20px;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1); 
            transition: transform 0.2s ease, box-shadow 0.2s ease;
            transform: translateZ(0); /* 🚨 EKRAN KARTINI (GPU) ZORLA DEVREYE SOKAR */
            will-change: transform; /* Tarayıcıya önceden haber verir, kasmayı engeller */
        }
        .glass-card:hover { transform: translateY(-5px); box-shadow: 0 8px 40px rgba(56, 189, 248, 0.2); border-color: rgba(56, 189, 248, 0.5); }
        
        /* 🚨 GHOSTING İÇİN KESİN ÇÖZÜM: Hantal Sayfa Geçiş Animasyonunu Kapat */
        [data-testid="stAppViewContainer"] > div:first-child {
            transition: none !important;
            animation: none !important;
        }
        
        .neon-text-blue { color: #38bdf8 !important; text-shadow: 0 0 10px rgba(56,189,248,0.5); font-weight: 900; }
        .neon-text-green { color: #34d399 !important; text-shadow: 0 0 10px rgba(52,211,153,0.5); font-weight: 900; }
        .neon-text-red { color: #f87171 !important; text-shadow: 0 0 10px rgba(248,113,113,0.5); font-weight: 900; }
        
        /* BUTONLARDAKİ BEYAZLIK HATASI DÜZELTİLDİ */
        button[kind="primary"], [data-testid="stFormSubmitButton"] button, div.stButton > button {
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important; color: white !important; border: none !important; border-radius: 10px !important;
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.4) !important; padding: 10px 20px !important;
        }
        button[kind="primary"] p, [data-testid="stFormSubmitButton"] button p, div.stButton > button p { color: #FFFFFF !important; font-weight: 800 !important; }
        button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] button:hover, div.stButton > button:hover { transform: translateY(-2px) !important; box-shadow: 0 8px 25px rgba(59, 130, 246, 0.6) !important; }
        
        /* Modül Seçici (Selectbox) Koyu Tema Yapıldı */
        div[data-baseweb="select"] > div { background-color: rgba(15, 23, 42, 0.9) !important; color: #FFFFFF !important; border: 1px solid rgba(56, 189, 248, 0.3) !important; border-radius: 8px !important; }
        div[data-baseweb="popover"] ul { background-color: #1e293b !important; color: #FFFFFF !important; }
        
        /* Textbox Kutuları */
        div[data-baseweb="input"] input, textarea { background-color: rgba(30, 41, 59, 0.8) !important; color: #FFFFFF !important; border: 1px solid rgba(56, 189, 248, 0.3) !important; border-radius: 8px !important; }
        div[data-baseweb="input"] input:focus { border-color: #38bdf8 !important; box-shadow: 0 0 10px rgba(56, 189, 248, 0.5) !important; }
        
        /* 💎 OMG AI CHAT INPUT (ASİSTAN MESAJ KUTUSU) KESİN ÇÖZÜM 💎 */
        [data-testid="stChatInput"] { background-color: rgba(30, 41, 59, 0.9) !important; border: 1px solid rgba(56, 189, 248, 0.5) !important; border-radius: 12px !important; box-shadow: 0 0 15px rgba(0, 0, 0, 0.5) !important; }
        [data-testid="stChatInput"] > div, [data-testid="stChatInput"] textarea { background-color: transparent !important; color: #FFFFFF !important; }
        [data-testid="stChatInput"] textarea::placeholder { color: #9CA3AF !important; }
        [data-testid="stChatInputSubmitButton"] { color: #38bdf8 !important; background-color: transparent !important; }
        [data-testid="stChatInputSubmitButton"]:hover { background-color: rgba(56, 189, 248, 0.2) !important; border-radius: 50%; }

        /* Tablolar ve Sekmeler */
        .stTabs [data-baseweb="tab-list"] button { color: #9CA3AF !important; background-color: rgba(30, 41, 59, 0.5) !important; border-radius: 5px 5px 0 0 !important; border-bottom: 2px solid transparent !important; }
        .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] { color: #FFFFFF !important; background-color: rgba(211, 16, 39, 0.1) !important; border-bottom: 2px solid #d31027 !important; }
        [data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; border: 1px solid rgba(56, 189, 248, 0.2); }
        [data-testid="stTable"] tr { background-color: transparent !important; }
        
        /* YATAY VE ANİMASYONLU ALARM KUTUSU */
        @keyframes pulse-alarm { 0% { box-shadow: 0 0 10px rgba(248,113,113,0.2); } 50% { box-shadow: 0 0 25px rgba(248,113,113,0.6); } 100% { box-shadow: 0 0 10px rgba(248,113,113,0.2); } }
        .alarm-bar { background: linear-gradient(90deg, rgba(248,113,113,0.1) 0%, rgba(15,23,42,0) 100%); border-left: 5px solid #f87171; padding: 15px 20px; border-radius: 8px; margin-bottom: 25px; animation: pulse-alarm 2s infinite; display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
        .alarm-title { color: #f87171; font-weight: 900; margin: 0; font-size: 18px; letter-spacing: 1px; }
        .alarm-badge { background: rgba(248,113,113,0.2); border: 1px solid rgba(248,113,113,0.4); padding: 6px 15px; border-radius: 20px; color: #fff; font-size: 14px; font-weight: 600; display: inline-flex; align-items: center; gap: 5px; }
        
        .module-banner { background: linear-gradient(90deg, rgba(30, 58, 138, 0.8) 0%, rgba(15, 23, 42, 0.9) 100%); border-left: 5px solid #38bdf8; backdrop-filter: blur(10px); padding: 25px 30px; border-radius: 15px; margin-bottom: 30px; box-shadow: 0 8px 30px rgba(0,0,0,0.4); }
        .module-banner h2 { color: #ffffff !important; font-weight: 900 !important; margin: 0; letter-spacing: 2px; }
        
        .radar-container { display: flex; justify-content: space-between; align-items: center; background: rgba(15,23,42,0.6); padding: 30px 20px; border-radius: 15px; border: 1px solid rgba(56,189,248,0.2); position: relative; margin-top: 10px; margin-bottom: 20px;}
        .radar-line { position: absolute; top: 50%; left: 5%; right: 5%; height: 4px; background: rgba(255,255,255,0.1); z-index: 1; transform: translateY(-50%); }
        .radar-step { position: relative; z-index: 2; display: flex; flex-direction: column; align-items: center; width: 20%; }
        .radar-circle { width: 50px; height: 50px; border-radius: 50%; background: #1e293b; border: 3px solid #475569; display: flex; justify-content: center; align-items: center; font-size: 20px; font-weight: 900; color: white; transition: all 0.4s; box-shadow: 0 0 10px rgba(0,0,0,0.5); }
        .radar-label { margin-top: 10px; font-size: 13px; font-weight: 600; color: #FFFFFF; text-align: center; text-transform: uppercase; letter-spacing: 1px;}
        .step-active .radar-circle { border-color: #38bdf8; background: rgba(56,189,248,0.2); color: #38bdf8; box-shadow: 0 0 20px rgba(56,189,248,0.6); animation: pulse-glow 2s infinite; }
        @keyframes pulse-glow { 0% { box-shadow: 0 0 10px rgba(56,189,248,0.4); } 50% { box-shadow: 0 0 25px rgba(56,189,248,0.8); } 100% { box-shadow: 0 0 10px rgba(56,189,248,0.4); } }
        
        .wp-btn { display:block; text-align:center; background: linear-gradient(135deg, #25D366 0%, #128C7E 100%); color:white !important; padding:12px; border-radius:8px; text-decoration:none; font-size:16px; font-weight:bold; box-shadow: 0 4px 15px rgba(37, 211, 102, 0.4); margin-top: 10px; transition: transform 0.2s; }
        .wp-btn:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(37, 211, 102, 0.6); }
        
        div.stButton > button[key="btn_ayarlar_alt"] { background: transparent !important; border: none !important; box-shadow: none !important; padding: 5px !important; display: flex; justify-content: flex-start; }
        div.stButton > button[key="btn_ayarlar_alt"] p { color: #94a3b8 !important; font-size: 13px !important; font-weight: 600 !important; transition: color 0.3s; }
        div.stButton > button[key="btn_ayarlar_alt"]:hover p { color: #38bdf8 !important; text-shadow: 0 0 8px rgba(56,189,248,0.5); }
</style>
""", unsafe_allow_html=True)

GOREVLER = ["Genel Müdür", "Laboratuvar Müdürü", "Sekreterya", "CAD/CAM Uzmanı", "Teknisyen", "Alçı & Model Teknisyeni", "Döküm Teknisyeni", "Tesviye Teknisyeni", "Seramist", "Akrilik & İskelet Teknisyeni", "Teknik Ekip", "Lojistik / Kurye"]    
KATEGORILER = ["ZİRKONYUM/ FULL SERAMİK RESTARASYONLAR", "LAZER SİNTERLEME", "FULL SERAMİK RESTARASYONLAR", "İSKELET DÖKÜM PROTEZLER", "CAD/CAM MILLING", "HAREKETLİ PROTEZLER", "TAMİR PROTEZLER", "ORTODONTİK APAREYLER", "ÖZEL İŞLEMLER"]
STOK_KATEGORILER = ["Blok", "Frez", "Metal Tozu", "Porselen", "Reçine", "Sarf Malzeme"]

BAKIM_RECELERI = {
    "redon gtr": ["Spindle İçi Havayla Temizlendi", "ATC Yuvaları Kontrol Edildi", "Su Tankı ve Filtre Değişimi", "Pens Lityum Gres İle Yağlandı"],
    "redon hybrid": ["Kuru Kazıma Vakum Temizliği", "Spindle İçi Havayla Temizlendi", "Pens Lityum Gres İle Yağlandı", "Kalibrasyon Diski Kesildi"],
    "fırın": ["Rezistans Gözle Kontrol Edildi", "Sıcaklık Kalibrasyonu Yapıldı", "Asansör Mekanizması Temizlendi"],
    "3d yazıcı": ["Reçine Tankı Alkolle Temizlendi", "Z Ekseni Mili Yağlandı", "LCD Ekran Toz Kontrolü"]
}

# --- 🚀 VERİTABANI BAĞLANTISI ---
try:
    conn = db_baglanti.get_connection('omg_smile_erp.db', check_same_thread=False, timeout=20)
    # conn.execute('PRAGMA journal_mode=WAL;')
    c = conn.cursor()
except Exception as e:
    st.error(f"Veritabanina baglanilamadi! Veritabanlarinin (dentflow, omg_smile_erp) var oldugundan emin olun. Hata: {e}")
    st.stop()



@st.dialog("🧑‍⚕️ Hasta Kartı", width="large")
def hasta_karti_goster(hasta_adi, klinik_unvani):
    h_isler = pd.read_sql("SELECT id, Tarih, Hasta_Kodu, Is_Turu, Adet, Asama, Aciklama, Harcanan_Malzeme, Sinter_Sarfiyati, Recine_Sarfiyati, Sorumlu_Personel, Tutar_TL FROM isler WHERE Hasta_Adi=? AND Klinik_Unvani=? ORDER BY Tarih ASC", conn, params=(hasta_adi, klinik_unvani))
    hasta_kodu_metni = '-'
    if not h_isler.empty and 'Hasta_Kodu' in h_isler.columns:
        kodlar = [k for k in h_isler['Hasta_Kodu'].dropna().unique() if k and str(k).strip() != '-']
        if kodlar: hasta_kodu_metni = ' / '.join(kodlar)
    
    # Fiyat ve Fatura hesaplama
    toplam_fiyat = float(h_isler['Tutar_TL'].sum()) if not h_isler.empty and 'Tutar_TL' in h_isler.columns else 0.0
    
    fatura_nolari = set()
    if not h_isler.empty:
        ekstre_ids = c.execute("SELECT id, Baslangic_Tarihi, Bitis_Tarihi FROM hesap_ekstreleri WHERE Klinik_Unvani=?", (klinik_unvani,)).fetchall()
        for j_tarih_tam in h_isler['Tarih']:
            j_tarih = str(j_tarih_tam).split(" ")[0]
            for e_id, e_bas, e_bit in ekstre_ids:
                if e_bas <= j_tarih <= e_bit:
                    fno = c.execute("SELECT Fatura_No FROM faturalar WHERE Ekstre_ID=?", (e_id,)).fetchone()
                    if fno:
                        fatura_nolari.add(str(fno[0]))
    
    fatura_metni = ", ".join(fatura_nolari) if fatura_nolari else "Fatura Kesilmemiş"
    
    st.markdown(f"## 🧑‍⚕️ {hasta_adi} | Kodu: {hasta_kodu_metni}")
    hk1, hk2, hk3 = st.columns(3)
    hk1.markdown(f"**🏥 Klinik:** {klinik_unvani}")
    if st.session_state.get('kullanici_rolu') in ['Yönetici', 'Admin']:
        hk2.markdown(f"**💰 Toplam Fiyat:** {toplam_fiyat:,.2f} TL")
    else:
        hk2.markdown(f"**💰 Toplam Fiyat:** ***** TL")
    hk3.markdown(f"**🧾 Fatura No:** {fatura_metni}")
    st.markdown("---")
    
    if not h_isler.empty:
        toplam_is = len(h_isler)
        tamamlanan = len(h_isler[h_isler['Asama'] == 'Teslim Edildi'])
        devam_eden = toplam_is - tamamlanan
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Toplam Kayıtlı İş", toplam_is)
        c2.metric("Tamamlanan", tamamlanan)
        c3.metric("Devam Eden", devam_eden)
        

        st.markdown("#### 📜 Yapılan İşlemler (Reçeteler)")
        if 'adet' in h_isler.columns: h_isler = h_isler.rename(columns={'adet': 'Adet'})
        if 'sinter_sarfiyati' in h_isler.columns: h_isler = h_isler.rename(columns={'sinter_sarfiyati': 'Sinter_Sarfiyati'})
        if 'harcanan_malzeme' in h_isler.columns: h_isler = h_isler.rename(columns={'harcanan_malzeme': 'Harcanan_Malzeme'})
        h_isler_goster = h_isler.rename(columns={"Tarih": "TARİH", "Is_Turu": "İŞİN TÜRÜ", "Adet": "ADET", "Asama": "AŞAMA", "Aciklama": "AÇIKLAMA"})
        st.dataframe(h_isler_goster[["TARİH", "İŞİN TÜRÜ", "ADET", "AŞAMA", "AÇIKLAMA"]], hide_index=True, use_container_width=True)
        
        if st.session_state.get("kullanici_rolu") not in ["Klinik", "Klinik_Asistan"]:
            st.markdown("#### 💎 Kullanılan Malzemeler")
            malzemeler = []
            import json
            for _, r in h_isler.iterrows():
                satir_bilgi = []
                if pd.notna(r['Harcanan_Malzeme']) and str(r['Harcanan_Malzeme']).strip() != "-" and str(r['Harcanan_Malzeme']).strip() != "":
                    satir_bilgi.append(f"**CAM:** {r['Harcanan_Malzeme']}")
            
                s_sarf = r['Sinter_Sarfiyati']
                if pd.notna(s_sarf) and str(s_sarf).strip() != "-" and str(s_sarf).strip() != "" and str(s_sarf).startswith("{"):
                    try:
                        s_data = json.loads(s_sarf)
                        s_metin = ""
                        if s_data.get("f1") and s_data["f1"] != "-- Seçiniz --" and s_data.get("s1", 0) > 0:
                            s_metin += f"Fırın 1: {s_data['f1']} ({s_data['s1']} Dk)"
                        if s_data.get("f2") and s_data["f2"] != "-- Seçiniz --" and s_data.get("s2", 0) > 0:
                            if s_metin: s_metin += " | "
                            s_metin += f"Fırın 2: {s_data['f2']} ({s_data['s2']} Dk)"
                        if s_metin:
                            satir_bilgi.append(f"**Sinter:** {s_metin}")
                    except: pass
                
                r_sarf = r.get('Recine_Sarfiyati')
                if pd.notna(r_sarf) and str(r_sarf).strip() != "-" and str(r_sarf).strip() != "" and str(r_sarf).startswith("{"):
                    try:
                        r_data = r_sarf if isinstance(r_sarf, dict) else json.loads(r_sarf)
                        r_metin = ""
                        yazici = r_data.get("yazici")
                        recine = r_data.get("recine")
                        if recine and recine != "-- Seçiniz --":
                            if " | " in recine:
                                recine = recine.split(" | ")[1]
                            r_metin += f"Reçine: {recine} ({r_data.get('tuketim_gr', 0)} gr)"
                        if yazici and yazici != "-- Seçiniz --":
                            if r_metin: r_metin += " | "
                            r_metin += f"Yazıcı: {yazici} ({r_data.get('sure', 0)} Dk)"
                        if r_metin:
                            satir_bilgi.append(f"**Reçine & 3D:** {r_metin}")
                    except: pass
                
                if satir_bilgi:
                    malzemeler.append(f"**{r['Is_Turu']} ({r['Tarih']})** 👉 " + " | ".join(satir_bilgi))
        
            if malzemeler:
                for m in malzemeler:
                    st.markdown(f"- {m}")
            else:
                st.info("Bu hastaya ait özel malzeme veya fırın sarfiyatı kaydedilmemiş.")
            
            st.markdown("#### 👨‍🔧 İlgili Teknisyen(ler)")
            teknisyenler = h_isler['Sorumlu_Personel'].unique()
            t_list = [t for t in teknisyenler if t and str(t).strip() != "-"]
            if t_list:
                st.markdown(", ".join(t_list))
            else:
                st.caption("Henüz teknisyen atanmamış.")
            
    else:
        st.warning("Bu hastaya ait detaylı veri bulunamadı.")





try:
    c.execute("SELECT id FROM sistem_loglari LIMIT 1")
except Exception:
    conn.rollback()
    print("ESKİ ŞEMA TESPİT EDİLDİ (id sütunu yok). VERİTABANI SIFIRLANIYOR...")
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    conn.commit()

c.execute('''CREATE TABLE IF NOT EXISTS cariler (id SERIAL PRIMARY KEY, Klinik_Unvani TEXT, Yetkili_Kisi TEXT, Telefon TEXT, Email TEXT, Bakiye REAL, Risk_Limiti REAL, Indirim_Orani REAL DEFAULT 0.0, Sifre TEXT DEFAULT '1234')''')
c.execute('''CREATE TABLE IF NOT EXISTS isler (id SERIAL PRIMARY KEY, Tarih TEXT, Klinik_Unvani TEXT, Hasta_Adi TEXT, Is_Turu TEXT, Renk TEXT, Asama TEXT, Tutar_TL REAL DEFAULT 0.0, Sorumlu_Personel TEXT DEFAULT '-', Harcanan_Malzeme TEXT DEFAULT '-', Teslim_Tarihi TEXT DEFAULT '2026-01-01', Barkod TEXT DEFAULT '-', Lot_Numarasi TEXT DEFAULT '-', Sertifika_No TEXT DEFAULT '-', Adet INTEGER DEFAULT 1, Sinter_Sarfiyati TEXT DEFAULT '-')''')
try: c.execute("ALTER TABLE isler ADD COLUMN Adet INTEGER DEFAULT 1")
except: pass
try: c.execute("ALTER TABLE isler ADD COLUMN Sinter_Sarfiyati TEXT DEFAULT '-'")
except: pass
try: c.execute("ALTER TABLE isler ADD COLUMN Recine_Sarfiyati TEXT DEFAULT '-'")
except: pass
try: c.execute("ALTER TABLE isler ADD COLUMN Fatura_Tarihi TEXT DEFAULT '-'")
except: pass
try: c.execute("ALTER TABLE isler ADD COLUMN Iskonto REAL DEFAULT 0.0")
except: pass
try: c.execute("ALTER TABLE isler ADD COLUMN Hasta_Kodu TEXT DEFAULT '-'")
except: pass
try: c.execute("ALTER TABLE isler ADD COLUMN Bakiye_Durumu TEXT DEFAULT 'Bekliyor'")
except: pass
c.execute('''CREATE TABLE IF NOT EXISTS stok (id SERIAL PRIMARY KEY, Urun_Kodu TEXT, Urun_Adi TEXT, Kategori TEXT, Mevcut_Miktar REAL, Birim TEXT, Kritik_Sinir REAL, Satis_Fiyati REAL, Durum TEXT DEFAULT 'Aktif', Renk TEXT DEFAULT '-', Guncelleme_Tarihi TEXT DEFAULT '-', Marka TEXT DEFAULT '-')''')
c.execute('''CREATE TABLE IF NOT EXISTS fiyat_listesi (id SERIAL PRIMARY KEY, Hizmet_Adi TEXT, Kategori TEXT, Fiyat REAL, Para_Birimi TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS hizmet_maliyetleri (id SERIAL PRIMARY KEY, hizmet_id INTEGER, kalem_adi TEXT, tutar REAL)''')
c.execute('''CREATE TABLE IF NOT EXISTS personeller (id SERIAL PRIMARY KEY, Ad_Soyad TEXT, Gorevi TEXT, Telefon TEXT, Maas REAL, Baslama_Tarihi TEXT, Ayrilma_Tarihi TEXT, Durum TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS kullanicilar (id SERIAL PRIMARY KEY, Kullanici_Adi TEXT, Sifre TEXT, Rol TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS giderler (id SERIAL PRIMARY KEY, Tarih TEXT, Kategori TEXT, Aciklama TEXT, Tutar REAL)''')
c.execute('''CREATE TABLE IF NOT EXISTS tahsilatlar (id SERIAL PRIMARY KEY, Tarih TEXT, Klinik_Unvani TEXT, Odeme_Turu TEXT, Tutar REAL, Aciklama TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS fatura_tahsilatlar (id SERIAL PRIMARY KEY, Fatura_ID INTEGER, Tarih TEXT, Tutar REAL, Odeme_Turu TEXT, Aciklama TEXT, Klinik_Unvani TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS is_fotograflari (id SERIAL PRIMARY KEY, Is_ID INTEGER, Dosya_Yolu TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS is_3d_modelleri (id SERIAL PRIMARY KEY, Is_ID INTEGER, Dosya_Yolu TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS cihazlar (id SERIAL PRIMARY KEY, Cihaz_Adi TEXT, Kategori TEXT, Calisma_Saati REAL DEFAULT 0, Bakim_Siniri REAL DEFAULT 500, Son_Bakim_Tarihi TEXT, Durum TEXT DEFAULT 'Aktif', Gorsel_Yolu TEXT DEFAULT '-', Haftalik_Hedef TEXT DEFAULT '2026-01-01', Aylik_Hedef TEXT DEFAULT '2026-01-01', Yillik_Hedef TEXT DEFAULT '2026-01-01')''')
c.execute('''CREATE TABLE IF NOT EXISTS cihaz_bakim_gecmisi (id SERIAL PRIMARY KEY, Cihaz_Adi TEXT, Tarih TEXT, Islem TEXT, Maliyet REAL DEFAULT 0, Aciklama TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS kurye_islemleri (id SERIAL PRIMARY KEY, Tarih TEXT, Saat TEXT, Klinik_Unvani TEXT, Aciklama TEXT, Durum TEXT DEFAULT 'Bekliyor')''')
c.execute('''CREATE TABLE IF NOT EXISTS cam_bloklar (id SERIAL PRIMARY KEY, Blok_Kodu TEXT, Urun_Adi TEXT, Boyut_Renk TEXT, Kapasite_Uye INTEGER, Kalan_Uye INTEGER, Durum TEXT DEFAULT 'Yarım')''')
c.execute('''CREATE TABLE IF NOT EXISTS cam_frezler (id SERIAL PRIMARY KEY, Frez_Kodu TEXT, Urun_Adi TEXT, Uyumlu_Makine TEXT, Max_Omur_Dk INTEGER, Kalan_Omur_Dk INTEGER, Durum TEXT DEFAULT 'Aktif')''')

c.execute('''CREATE TABLE IF NOT EXISTS ayarlar (Ayar_Adi TEXT PRIMARY KEY, Ayar_Degeri TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS personel_finans (id SERIAL PRIMARY KEY, Tarih TEXT, Personel_Adi TEXT, Islem_Turu TEXT, Tutar REAL, Aciklama TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS personel_izinler (id SERIAL PRIMARY KEY, Tarih TEXT, Personel_Adi TEXT, Baslangic_Tarihi TEXT, Bitis_Tarihi TEXT, Gun_Sayisi INTEGER, Aciklama TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS klinik_asistanlari (Klinik_Unvani TEXT, Asistan_Kadi TEXT PRIMARY KEY, Sifre TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS laboratuvar_dokumanlari (id SERIAL PRIMARY KEY, Tarih TEXT, Dokuman_Adi TEXT, Dosya_Yolu TEXT, Dosya_Turu TEXT)''')

# 💎 FAZ 42: CANLI BİLDİRİM VE CHAT ALTYAPISI (BEYİN) 💎
# Sistemdeki anlık hareketleri (giriş yaptı, reçete yazdı vb.) tutar. 
# Goruldu=0 ise henüz ekrana fırlatılmamıştır, Goruldu=1 ise kullanıcı görmüştür.
c.execute('''CREATE TABLE IF NOT EXISTS sistem_loglari (id SERIAL PRIMARY KEY, Tarih_Saat TEXT, Kullanici TEXT, Aksiyon TEXT, Goruldu INTEGER)''')

# Hekimler ve laboratuvar arasındaki anlık yazışmaları tutar.
c.execute('''CREATE TABLE IF NOT EXISTS mesajlar (id SERIAL PRIMARY KEY, Tarih_Saat TEXT, Gonderen TEXT, Alici TEXT, Mesaj TEXT, Okundu INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS fire_kayitlari (id SERIAL PRIMARY KEY, Tarih TEXT, Urun_Kodu TEXT, Urun_Adi TEXT DEFAULT '-', Miktar REAL, Neden TEXT, Kullanici TEXT, Kalan_Omur TEXT DEFAULT '-')''')
conn.commit()

# 💎 FAZ 42: CANLI BİLDİRİM MOTORU (RADAR) 💎
# Bu kod her sayfa açıldığında veya bir butona basıldığında arkada gizlice çalışır.
# BUG DÜZELTİLDİ: Tablo oluşturulduktan SONRA sorgu yapılıyor
try:
    bekleyen_bildirimler = c.execute("SELECT id, Tarih_Saat, Kullanici, Aksiyon FROM sistem_loglari WHERE Goruldu=0").fetchall()
    for b in bekleyen_bildirimler:
        st.toast(f"🔔 **{b[2]}**\n\n{b[3]}", icon="🚀")
        c.execute("UPDATE sistem_loglari SET Goruldu=1 WHERE id=?", (b[0],))
    conn.commit()
except Exception:
    pass
def ayar_getir(ayar_adi, varsayilan=""):
    sorgu = c.execute("SELECT Ayar_Degeri FROM ayarlar WHERE Ayar_Adi=?", (ayar_adi,)).fetchone()
    return sorgu[0] if sorgu else varsayilan

def ayar_kaydet(ayar_adi, deger):
    # Eğer ayar varsa günceller, yoksa ekler (PostgreSQL ve SQLite Uyumlu)
    mevcut = c.execute("SELECT COUNT(*) FROM ayarlar WHERE Ayar_Adi=?", (ayar_adi,)).fetchone()
    if mevcut and mevcut[0] > 0:
        c.execute("UPDATE ayarlar SET Ayar_Degeri=? WHERE Ayar_Adi=?", (str(deger), ayar_adi))
    else:
        c.execute("INSERT INTO ayarlar (Ayar_Adi, Ayar_Degeri) VALUES (?, ?)", (ayar_adi, str(deger)))
    conn.commit()

def ayar_varsayilan_ekle(ayar_adi, deger):
    try:
        mevcut = c.execute("SELECT COUNT(*) FROM ayarlar WHERE Ayar_Adi=?", (ayar_adi,)).fetchone()
        if not mevcut or mevcut[0] == 0:
            c.execute("INSERT INTO ayarlar (Ayar_Adi, Ayar_Degeri) VALUES (?, ?)", (ayar_adi, str(deger)))
            conn.commit()
    except: pass

if not c.execute("SELECT count(*) FROM ayarlar").fetchone()[0] > 0:
    ayar_kaydet("Barkod_Onek", "OMG")
    ayar_kaydet("Para_Birimi", "TL")
    ayar_kaydet("KDV_Orani", "20")
    ayar_kaydet("Lobi_IP", "192.168.1.100")
    ayar_kaydet("Sms_Sessiz_Saatler", "22:00 - 08:00")
    ayar_kaydet("Kurye_Sablonu", "Sayın [Hekim_Adı],\nKurye talebiniz alınmıştır. Kuryemiz en kısa sürede adresinize yönlendirilecektir.\nTeşekkür ederiz.")
    ayar_kaydet("Sistem_Kilitli", "Hayır")

ayar_varsayilan_ekle("Elektrik_kWh_Fiyati", "3.0")
ayar_varsayilan_ekle("Uretim_Disi_Maliyet", "0")
ayar_varsayilan_ekle("Manuel_Euro_Kuru", "35.0")
ayar_varsayilan_ekle("Kur_Guncelleme_Saati", "1970-01-01 00:00")

try:
    c.execute("""CREATE TABLE IF NOT EXISTS gorevler (
        id SERIAL PRIMARY KEY, 
        olusturan TEXT, 
        atanan_kullanici TEXT, 
        gorev_basligi TEXT, 
        gorev_detayi TEXT, 
        son_tarih TEXT, 
        durum TEXT DEFAULT 'Bekliyor', 
        oncelik TEXT DEFAULT 'Normal',
        olusturma_tarihi TEXT
    )""")
    conn.commit()
except Exception as e:
    pass

try:
    c.execute("""CREATE TABLE IF NOT EXISTS uretim_loglari
               (id SERIAL PRIMARY KEY, is_id INTEGER, is_adi TEXT, malzeme_turu TEXT, 
                malzeme_kodu TEXT, malzeme_adi TEXT, uye_sayisi INTEGER, tarih TEXT)""")
    conn.commit()
except:
    pass

def guncel_euro_kuru_getir():
    manuel_kur = float(ayar_getir("Manuel_Euro_Kuru", "35.0"))
    if 'canli_euro_kuru' not in st.session_state:
        yeni_kur = tcmb_kur_getir('EUR')
        if yeni_kur:
            try:
                ayar_kaydet("Manuel_Euro_Kuru", str(yeni_kur))
            except: pass
            st.session_state['canli_euro_kuru'] = yeni_kur
        else:
            st.session_state['canli_euro_kuru'] = manuel_kur
    return st.session_state['canli_euro_kuru']

def kazima_makinelerini_getir():
    try:
        makineler = [row[0] for row in c.execute("SELECT Cihaz_Adi FROM cihazlar WHERE Kategori='Kazıma Makinesi (Milling)' AND Durum='Aktif'").fetchall()]
        return makineler if makineler else ["Redon GTR", "Redon Hybrid", "Roland DWX", "Diğer"]
    except:
        return ["Redon GTR", "Redon Hybrid", "Roland DWX", "Diğer"]

def otomatik_maliyetleri_guncelle():
    """Tüm hizmet maliyetlerini canlı kurlara, elektriğe ve depo fiyatlarına göre yeniden hesaplar."""
    euro_kuru = guncel_euro_kuru_getir()
    kwh_fiyat = float(ayar_getir("Elektrik_kWh_Fiyati", "3.0"))
    try:
        maliyetler = c.execute("SELECT h.id, h.hizmet_id, h.kalem_adi, h.tutar, f.Para_Birimi FROM hizmet_maliyetleri h JOIN fiyat_listesi f ON h.hizmet_id = f.id").fetchall()
        for m in maliyetler:
            m_id, s_id, kalem_adi, eski_tutar, s_pb = m
            yeni_tutar = None
            
            match_mak = re.search(r'Makine Üretimi - (.+) \((\d+(?:\.\d+)?) Dk\)', kalem_adi)
            if match_mak:
                secili_mak = match_mak.group(1).strip()
                makine_dk = float(match_mak.group(2))
                m_data = c.execute("SELECT Guc_kW FROM cihazlar WHERE Cihaz_Adi=? AND Durum='Aktif'", (secili_mak,)).fetchone()
                kw_guc = float(m_data[0]) if m_data else float(ayar_getir("Makine_Gucu_kW", "2.5"))
                elektrik_tl_maliyet = (kw_guc * kwh_fiyat) / 60.0 * makine_dk
                yeni_tutar = float(elektrik_tl_maliyet / euro_kuru if euro_kuru > 0 else 0) if s_pb in ["EUR", "Euro"] else float(elektrik_tl_maliyet)
            
            match_stok = re.search(r'Stok Tüketimi(?: \((Ortalama|Miktar)\))? - (.+) \((\d+(?:\.\d+)?) (.+)\)', kalem_adi)
            if match_stok:
                hesap_tipi = match_stok.group(1) # Ortalama, Miktar veya None
                urun_adi = match_stok.group(2).strip()
                adet_veya_uye = float(match_stok.group(3))
                s_data = c.execute("SELECT Satis_Fiyati, Kategori FROM stok WHERE Urun_Adi=? AND Durum='Aktif'", (urun_adi,)).fetchone()
                if s_data:
                    fiyat = float(s_data[0])
                    kat = str(s_data[1]).lower()
                    fiyat_tl = fiyat * euro_kuru if 'blok' in kat else fiyat
                    
                    if hesap_tipi == "Ortalama":
                        ort_data = c.execute('''
                            SELECT CAST(SUM(uye_sayisi) AS FLOAT) / COUNT(DISTINCT malzeme_kodu) 
                            FROM uretim_loglari WHERE malzeme_adi=?
                        ''', (urun_adi,)).fetchone()
                        ortalama_verim = ort_data[0] if ort_data and ort_data[0] else 1.0
                        if ortalama_verim <= 0: ortalama_verim = 1.0
                        toplam_tl = (fiyat_tl / ortalama_verim) * adet_veya_uye
                    else:
                        toplam_tl = fiyat_tl * adet_veya_uye
                        
                    yeni_tutar = float(toplam_tl / euro_kuru if euro_kuru > 0 else 0) if s_pb in ["EUR", "Euro"] else float(toplam_tl)
                    
            if yeni_tutar is not None and abs(yeni_tutar - (eski_tutar if eski_tutar else 0)) > 0.001:
                c.execute("UPDATE hizmet_maliyetleri SET tutar=? WHERE id=?", (yeni_tutar, m_id))
        conn.commit()
    except Exception as e:
        pass

otomatik_maliyetleri_guncelle()

def tablo_yama_uygula(tablo_adi, sutun_adi, sutun_turu):
    try: 
        c.execute(f"ALTER TABLE {tablo_adi} ADD COLUMN {sutun_adi} {sutun_turu}")
        conn.commit()
    except: 
        conn.rollback()

tablo_yama_uygula("cariler", "Indirim_Orani", "REAL DEFAULT 0.0")
tablo_yama_uygula("cariler", "Sifre", "TEXT DEFAULT '1234'")
tablo_yama_uygula("cariler", "Adres", "TEXT DEFAULT '-'")
tablo_yama_uygula("cariler", "Firma_Unvani", "TEXT DEFAULT '-'")
tablo_yama_uygula("cariler", "Vergi_Dairesi", "TEXT DEFAULT '-'")
tablo_yama_uygula("cariler", "Vergi_No", "TEXT DEFAULT '-'")
tablo_yama_uygula("stok", "Renk", "TEXT DEFAULT '-'")
tablo_yama_uygula("stok", "Guncelleme_Tarihi", "TEXT DEFAULT '-'")
tablo_yama_uygula("stok", "Marka", "TEXT DEFAULT '-'")
tablo_yama_uygula("cariler", "IBAN", "TEXT DEFAULT '-'")
tablo_yama_uygula("isler", "Barkod", "TEXT DEFAULT '-'")
tablo_yama_uygula("stok", "Guncelleme_Tarihi", "TEXT DEFAULT '-'")
tablo_yama_uygula("isler", "Lot_Numarasi", "TEXT DEFAULT '-'")
tablo_yama_uygula("isler", "Sertifika_No", "TEXT DEFAULT '-'")
tablo_yama_uygula("isler", "Aciklama", "TEXT DEFAULT '-'")
tablo_yama_uygula("stok", "Durum", "TEXT DEFAULT 'Aktif'")
tablo_yama_uygula("cihazlar", "Gorsel_Yolu", "TEXT DEFAULT '-'")
tablo_yama_uygula("cihazlar", "Haftalik_Hedef", f"TEXT DEFAULT '{datetime.now().strftime('%Y-%m-%d')}'")
tablo_yama_uygula("cihazlar", "Aylik_Hedef", f"TEXT DEFAULT '{datetime.now().strftime('%Y-%m-%d')}'")
tablo_yama_uygula("cihazlar", "Yillik_Hedef", f"TEXT DEFAULT '{datetime.now().strftime('%Y-%m-%d')}'")
tablo_yama_uygula("cihazlar", "Guc_kW", "REAL DEFAULT 0.0")
tablo_yama_uygula("kurye_islemleri", "Saat", "TEXT DEFAULT '00:00'")

tablo_yama_uygula("personeller", "TC_No", "TEXT DEFAULT '-'")
tablo_yama_uygula("personeller", "Email", "TEXT DEFAULT '-'")
tablo_yama_uygula("personeller", "Adres", "TEXT DEFAULT '-'")
tablo_yama_uygula("personeller", "IBAN", "TEXT DEFAULT '-'")
tablo_yama_uygula("personeller", "Kalan_Izin", "INTEGER DEFAULT 14")
tablo_yama_uygula("personeller", "TC_No", "TEXT DEFAULT '-'")

# 💎 FAZ 37 & 38 İÇİN VERİTABANI YAMALARI 💎
tablo_yama_uygula("cariler", "Bildirim_Kurye", "TEXT DEFAULT 'WhatsApp'")
tablo_yama_uygula("cariler", "Bildirim_Fatura", "TEXT DEFAULT 'E-Posta'")
tablo_yama_uygula("cariler", "Bildirim_Asama", "TEXT DEFAULT 'Sessiz (İstemiyorum)'")
tablo_yama_uygula("cariler", "Otopilot_Kategori", "TEXT DEFAULT '-'")
tablo_yama_uygula("cariler", "Otopilot_Islem", "TEXT DEFAULT '-'")
tablo_yama_uygula("cariler", "Otopilot_Renk", "TEXT DEFAULT 'A2'")

tablo_yama_uygula("cariler", "IBAN", "TEXT DEFAULT '-'")
tablo_yama_uygula("cariler", "VIP_Seviye", "TEXT DEFAULT 'Standart'")

# --- Veritabanı Yamaları ---
tablo_yama_uygula("personeller", "Foto_Yolu", "TEXT DEFAULT '-'")
tablo_yama_uygula("personeller", "CV_Yolu", "TEXT DEFAULT '-'")
tablo_yama_uygula("fire_kayitlari", "Kalan_Omur", "TEXT DEFAULT '-'")
tablo_yama_uygula("fire_kayitlari", "Urun_Adi", "TEXT DEFAULT '-'")
try:
    c.execute("UPDATE fire_kayitlari SET Urun_Adi = (SELECT Urun_Adi FROM stok WHERE stok.Urun_Kodu = fire_kayitlari.Urun_Kodu) WHERE Urun_Adi = '-'")
    conn.commit()
except: pass

if db_baglanti.USE_POSTGRES:
    try:
        conn_df = db_baglanti.get_connection('dentflow.db')
        c_df = conn_df.cursor()
        c_df.execute("ALTER TABLE mesajlar ALTER COLUMN zaman TYPE TEXT")
        conn_df.commit()
        conn_df.close()
    except Exception:
        pass

conn.commit()

if c.execute("SELECT count(*) FROM kullanicilar").fetchone()[0] == 0:
    c.execute("INSERT INTO kullanicilar (Kullanici_Adi, Sifre, Rol) VALUES ('tamer', 'admin123', 'Admin')")
    conn.commit()

# 💎 FAZ 40: KURYE ROLÜNÜ VERİTABANINA EKLE 💎
if c.execute("SELECT count(*) FROM kullanicilar WHERE Rol='Kurye'").fetchone()[0] == 0:
    c.execute("INSERT INTO kullanicilar (Kullanici_Adi, Sifre, Rol) VALUES ('kurye', '1234', 'Kurye')")
    conn.commit()

def banner_olustur(ikon, baslik, aciklama):
    st.markdown(f"""<div class="module-banner"><h2><span style="color:#38bdf8;">{ikon}</span> {baslik}</h2><p style="color:#FFFFFF;">{aciklama}</p></div>""", unsafe_allow_html=True)

def wp_link_olustur(telefon, mesaj):
    temiz_tel = "".join(filter(str.isdigit, str(telefon)))
    if temiz_tel.startswith("0"): temiz_tel = "90" + temiz_tel[1:]
    elif not temiz_tel.startswith("90"): temiz_tel = "90" + temiz_tel
    return f"https://wa.me/{temiz_tel}?text={urllib.parse.quote(mesaj)}"

def akilli_klasor_yolu(klinik, hasta):
    def temizle(metin):
        karakterler = {"ı":"i", "ğ":"g", "ü":"u", "ş":"s", "ö":"o", "ç":"c", "İ":"I", "Ğ":"G", "Ü":"U", "Ş":"S", "Ö":"O", "Ç":"C", " ": "_", "/": "-", "\\": "-"}
        for k, v in karakterler.items(): metin = str(metin).replace(k, v)
        return "".join([c for c in metin if c.isalnum() or c in ['_', '-']])
    yil = datetime.now().strftime("%Y"); ay = datetime.now().strftime("%m")
    hedef_dizin = os.path.join("uploads", yil, ay, temizle(klinik), temizle(hasta))
    if not os.path.exists(hedef_dizin): os.makedirs(hedef_dizin)
    return hedef_dizin

def qr_kod_olustur(veri):
    qr = qrcode.QRCode(version=1, box_size=5, border=1); qr.add_data(veri); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white"); buf = io.BytesIO(); img.save(buf, format="PNG")
    return buf.getvalue()

def stl_ciz(dosya_yolu):
    try:
        my_mesh = mesh.Mesh.from_file(storage_utils.yerel_yol_getir(dosya_yolu))
        vertices = my_mesh.vectors.reshape(-1, 3); x, y, z = vertices[:,0], vertices[:,1], vertices[:,2]
        i, j, k = np.arange(0, len(x), 3), np.arange(1, len(x), 3), np.arange(2, len(x), 3)
        fig = go.Figure(data=[go.Mesh3d(x=x, y=y, z=z, i=i, j=j, k=k, color='#9CA3AF', opacity=1.0, lighting=dict(ambient=0.4, diffuse=0.8, roughness=0.5, specular=0.3, fresnel=0.2))])
        fig.update_layout(scene=dict(xaxis=dict(visible=False), yaxis=dict(visible=False), zaxis=dict(visible=False)), margin=dict(r=0, l=0, b=0, t=0), paper_bgcolor="#0f172a")
        st.plotly_chart(fig, use_container_width=True)
    except: st.error("3D Model Çizilirken Bir Hata Oluştu.")

def timer_renk_hesapla(hedef_tarih_str, periyot_gun):
    try:
        if pd.isna(hedef_tarih_str) or hedef_tarih_str == "-" or not hedef_tarih_str: hedef_tarih_str = datetime.now().strftime("%Y-%m-%d")
        bugun = datetime.now(); hedef = datetime.strptime(str(hedef_tarih_str)[:10], "%Y-%m-%d")
        kalan_gun = (hedef - bugun).days
        yuzde = max(min(kalan_gun / periyot_gun, 1.0), 0.0); renk = "#34D399" if yuzde > 0.5 else "#FBBF24" if yuzde > 0.2 else "#FB923C" if kalan_gun > 0 else "#F87171"
        metin = f"{kalan_gun} Gün Kaldı" if kalan_gun > 0 else "Bugün!" if kalan_gun == 0 else f"{abs(kalan_gun)} Gün Gecikti!"
        return f"""<div style="width: 100%; background-color: #334155; border-radius: 4px; margin-bottom: 2px;"><div style="width: {yuzde*100}%; height: 12px; background-color: {renk}; border-radius: 4px;"></div></div><div style="font-size: 11px; font-weight: bold; color: {renk}; text-align: right;">{metin}</div>"""
    except: return ""

def garanti_sertifikasi_uret(hasta, klinik, is_turu, tarih, lot, cert_no):
    def tr_karakter_duzelt(metin): return str(metin).replace('ı','i').replace('ş','s').replace('ğ','g').replace('ö','o').replace('ç','c').replace('ü','u').replace('İ','I').replace('Ş','S').replace('Ğ','G').replace('Ö','O').replace('Ç','C').replace('Ü','U')
    pdf = FPDF(orientation='L', unit='mm', format='A5'); pdf.set_auto_page_break(auto=False, margin=0); pdf.add_page()
    pdf.set_draw_color(30, 58, 138); pdf.set_line_width(1.5); pdf.rect(5, 5, 200, 138); pdf.set_line_width(0.5); pdf.rect(7, 7, 196, 134)
    # 💎 LOGO KONTROLÜ (SOL ÜST KÖŞEYE ZARİF YERLEŞTİRME) 💎
    logo_yolu = ayar_getir("Kurumsal_Logo", "-")
    if logo_yolu != "-" and os.path.exists(logo_yolu):
        # Logoyu sol üst köşeye daha kibar (30mm genişlik) yerleştiriyoruz
        pdf.image(logo_yolu, x=12, y=10, w=30) 
    
    # Başlığı logodan bağımsız, temiz bir konuma çekiyoruz
    pdf.set_y(15) 
    pdf.set_font("Courier", "B", 18)
    pdf.set_text_color(30, 58, 138)
    pdf.cell(0, 10, tr_karakter_duzelt("DIJITAL GARANTI SERTIFIKASI"), ln=True, align="C")
    
    # Yazıların iç içe girmemesi için dikey boşluğu ayarlıyoruz
    pdf.set_y(35)
    pdf.set_text_color(0, 0, 0); pdf.set_font("Courier", "B", 12); pdf.ln(8)
    
    pdf.set_x(15); pdf.cell(50, 8, "Sertifika No", 0, 0); pdf.cell(5, 8, ":", 0, 0); pdf.cell(100, 8, cert_no, 0, 1)
    pdf.set_x(15); pdf.cell(50, 8, "Hasta Adi", 0, 0); pdf.cell(5, 8, ":", 0, 0); pdf.cell(100, 8, tr_karakter_duzelt(hasta), 0, 1)
    pdf.set_x(15); pdf.cell(50, 8, "Klinik / Hekim", 0, 0); pdf.cell(5, 8, ":", 0, 0); pdf.cell(100, 8, tr_karakter_duzelt(klinik), 0, 1)
    pdf.set_x(15); pdf.cell(50, 8, "Uygulama", 0, 0); pdf.cell(5, 8, ":", 0, 0); pdf.cell(100, 8, tr_karakter_duzelt(is_turu), 0, 1)
    pdf.set_x(15); pdf.cell(50, 8, "Materyal Lot No", 0, 0); pdf.cell(5, 8, ":", 0, 0); pdf.cell(100, 8, tr_karakter_duzelt(lot), 0, 1)
    pdf.set_x(15); pdf.cell(50, 8, "Uretim Tarihi", 0, 0); pdf.cell(5, 8, ":", 0, 0); pdf.cell(100, 8, tarih, 0, 1)
    
    pdf.ln(8); pdf.set_x(15); pdf.set_font("Courier", "I", 10)
    pdf.multi_cell(180, 5, tr_karakter_duzelt("Bu restorasyon OMG Smile Laboratuvari tarafindan, T.C. Saglik Bakanligi, CE ve FDA onayli biyouyumlu materyaller kullanilarak Endustri 4.0 standartlarinda uretilmistir."))
    qr_data = f"Sertifika: {cert_no} | Hasta: {tr_karakter_duzelt(hasta)} | Orijinal OMG Smile Uretimi"
    qr = qrcode.QRCode(version=1, box_size=4, border=1); qr.add_data(qr_data); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white"); qr_path = os.path.join("uploads", "qrcodes", f"{cert_no}_qr.png"); img.save(qr_path)
    pdf.image(qr_path, x=160, y=55, w=35) 
    
    pdf.set_y(130); pdf.set_font("Courier", "I", 8); pdf.set_text_color(120, 120, 120) 
    pdf.cell(0, 4, tr_karakter_duzelt("* Kullanilan tum materyaller T.C. Saglik Bakanligi Urun Takip Sistemi (UTS) kayitlidir."), ln=True, align="C")
    pdf.cell(0, 4, tr_karakter_duzelt("Laboratuvar Ruhsat No: OMG-LAB-2024/001 | Bu sertifika fatura yerine gecmez."), ln=True, align="C")
    return pdf.output(dest='S').encode('latin1')

def ekstre_pdf_uret(klinik, df, son_bakiye):
    def tr(metin): return str(metin).replace('ı','i').replace('ş','s').replace('ğ','g').replace('ö','o').replace('ç','c').replace('ü','u').replace('İ','I').replace('Ş','S').replace('Ğ','G').replace('Ö','O').replace('Ç','C').replace('Ü','U')
    pdf = FPDF(orientation='P', unit='mm', format='A4'); pdf.set_auto_page_break(auto=True, margin=15); pdf.add_page()
    # 💎 LOGO KONTROLÜ 💎
    logo_yolu = ayar_getir("Kurumsal_Logo", "-")
    if logo_yolu != "-" and os.path.exists(logo_yolu):
        pdf.image(logo_yolu, x=10, y=10, w=35) # Sol üste küçük logo
        pdf.set_y(25)
    
    pdf.set_font("Courier", "B", 16); pdf.set_text_color(30, 58, 138); 
    pdf.cell(0, 10, tr("LABORATUVAR HESAP EKSTRESI"), ln=True, align="C")
    pdf.set_font("Courier", "", 11); pdf.set_text_color(0, 0, 0); pdf.cell(0, 10, tr(f"Klinik: {klinik}"), ln=True, align="L")
    pdf.cell(0, 5, tr(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}"), ln=True, align="L"); pdf.ln(5)
    
    pdf.set_fill_color(220, 220, 220); pdf.set_font("Courier", "B", 9)
    pdf.cell(25, 8, "Tarih", border=1, fill=True); pdf.cell(85, 8, "Islem", border=1, fill=True)
    pdf.cell(25, 8, "Borc (TL)", border=1, align="R", fill=True); pdf.cell(25, 8, "Alacak(TL)", border=1, align="R", fill=True)
    pdf.cell(30, 8, "Bakiye(TL)", border=1, align="R", ln=True, fill=True)
    
    para_birimi = ayar_getir("Para_Birimi", "TL")
    pdf.set_font("Courier", "", 8)
    for _, row in df.iterrows():
        islem = str(row['Islem'])
        if len(islem) > 42: islem = islem[:39] + "..."
        pdf.cell(25, 6, str(row['Tarih']), border=1); pdf.cell(85, 6, tr(islem), border=1)
        pdf.cell(25, 6, f"{row['Borc']:,.2f}", border=1, align="R"); pdf.cell(25, 6, f"{row['Alacak']:,.2f}", border=1, align="R")
        pdf.cell(30, 6, f"{row['Kümülatif Bakiye']:,.2f}", border=1, align="R", ln=True)
        
    pdf.ln(10); pdf.set_font("Courier", "B", 12); pdf.set_text_color(220, 38, 38) 
    pdf.cell(0, 10, tr(f"GUNCEL KALAN BORC: {son_bakiye:,.2f} {para_birimi}"), ln=True, align="R")
    pdf_out = pdf.output(dest='S')
    return pdf_out.encode('latin1') if hasattr(pdf_out, 'encode') else bytes(pdf_out)


def fatura_pdf_uret(fatura_no, klinik, ekstre_df, toplam_tutar, fatura_tarihi, kdv_orani=20, aciklama=""):
    import uuid
    def tr(metin): return str(metin).replace('ı','i').replace('ş','s').replace('ğ','g').replace('ö','o').replace('ç','c').replace('ü','u').replace('İ','I').replace('Ş','S').replace('Ğ','G').replace('Ö','O').replace('Ç','C').replace('Ü','U')
    def sayiyi_yaziya_cevir(sayi):
        birler = ["", "Bir", "Iki", "Uc", "Dort", "Bes", "Alti", "Yedi", "Sekiz", "Dokuz"]
        onlar = ["", "On", "Yirmi", "Otuz", "Kirk", "Elli", "Atmis", "Yetmis", "Seksen", "Doksan"]
        binler = ["", "Bin", "Milyon", "Milyar"]
        tam_kisim = int(sayi)
        krs_kisim = int(round((sayi - tam_kisim) * 100))
        if tam_kisim == 0: return "Sifir TRY"
        def uclu_oku(n):
            if n == 0: return ""
            yuz = n // 100
            kalan = n % 100
            on = kalan // 10
            bir = kalan % 10
            okunus = ""
            if yuz > 1: okunus += birler[yuz] + "Yuz"
            elif yuz == 1: okunus += "Yuz"
            okunus += onlar[on] + birler[bir]
            return okunus
        str_sayi = str(tam_kisim)
        gruplar = []
        while len(str_sayi) > 0:
            gruplar.append(int(str_sayi[-3:]))
            str_sayi = str_sayi[:-3]
        sonuc = ""
        for i in range(len(gruplar)-1, -1, -1):
            grup = gruplar[i]
            if grup == 0: continue
            if i == 1 and grup == 1: sonuc += "Bin"
            else: sonuc += uclu_oku(grup) + binler[i]
        krs_metin = f" {uclu_oku(krs_kisim)}Kurus" if krs_kisim > 0 else ""
        return f"#{sonuc} TRY{krs_metin}#"

    try:
        k_veri = c.execute("SELECT Firma_Unvani, Adres, Vergi_Dairesi, Vergi_No FROM cariler WHERE Klinik_Unvani=?", (klinik,)).fetchone()
        if k_veri:
            klinik_bilgi = {"Firma_Unvani": k_veri[0], "Adres": k_veri[1], "Vergi_Dairesi": k_veri[2], "Vergi_No": k_veri[3], "Klinik_Unvani": klinik}
        else:
            klinik_bilgi = {"Klinik_Unvani": klinik}
    except:
        klinik_bilgi = {"Klinik_Unvani": klinik}

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Courier", "", 8)

    # 1. Sol Üst: Gönderici Bilgileri
    pdf.set_xy(10, 10)
    pdf.set_font("Courier", "B", 9)
    pdf.cell(0, 4, tr("OMG SMILE SAGLIK TEKNOLOJILERI VE HIZMETLERI LIMITED SIRKETI"), ln=True)
    pdf.set_font("Courier", "", 8)
    satirlar = [
        "AHMETTURANGAZİ OSB MAH. OSB-10 SK.",
        "No:2 /1A",
        "MERKEZ / SIVAS / TURKIYE",
        "Tel: 0501 542 0258",
        "E-Posta: info@omgsmile.com.tr",
        "Vergi Dairesi: Kale Vergi Dairesi Mudurlugu",
        "VKN: 6420997799",
        "TICARETSICILNO: 000"
    ]
    for s in satirlar:
        pdf.cell(0, 4, tr(s), ln=True)

    pdf.set_line_width(0.8)
    pdf.line(10, 45, 100, 45)
    pdf.set_line_width(0.2)

    # 2. Orta: Logo ve e-Fatura
    try:
        if os.path.exists('gib_logo.png'):
            pdf.image('gib_logo.png', x=95, y=10, w=20)
    except: pass
    pdf.set_xy(90, 32)
    pdf.set_font("Courier", "B", 12)
    pdf.cell(30, 5, "e-FATURA", align='C')

    # 3. Sağ Üst: Kutu Bilgiler
    pdf.set_font("Courier", "B", 8)
    x_sag, y_sag = 135, 15
    kutu_satirlari = [
        ("Ozellestirme No:", "TR1.2"),
        ("Senaryo:", "TEMELFATURA"),
        ("Fatura Tipi:", "SATIS"),
        ("Fatura No:", tr(fatura_no)),
        ("Fatura Tarihi:", tr(fatura_tarihi))
    ]
    for baslik, deger in kutu_satirlari:
        pdf.set_xy(x_sag, y_sag)
        pdf.cell(30, 5, baslik, border=1, fill=False)
        pdf.cell(35, 5, deger, border=1, fill=False)
        y_sag += 5

    # 4. Sol Orta: Alıcı Bilgileri
    pdf.set_xy(10, 50)
    pdf.set_font("Courier", "B", 9)
    pdf.cell(0, 5, "SAYIN", ln=True)
    pdf.set_font("Courier", "", 8)
    k_unvan = klinik_bilgi.get("Firma_Unvani", klinik)
    if not k_unvan or k_unvan == "-": k_unvan = klinik
    pdf.cell(0, 4, tr(k_unvan), ln=True)
    pdf.cell(0, 4, tr(klinik_bilgi.get("Adres", "-")), ln=True)
    pdf.cell(0, 4, tr(f"Vergi Dairesi: {klinik_bilgi.get('Vergi_Dairesi', '-')}"), ln=True)
    pdf.cell(0, 4, tr(f"VKN: {klinik_bilgi.get('Vergi_No', '-')}"), ln=True)

    # 5. ETTN
    pdf.set_xy(10, 80)
    pdf.set_font("Courier", "B", 8)
    pdf.cell(0, 5, f"ETTN: {str(uuid.uuid4())}", ln=True)

    # 6. Tablo Başlığı
    pdf.set_xy(10, 90)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Courier", "B", 8)
    w_cols = [12, 60, 15, 20, 20, 23, 30]
    h_cols = ["Sira No", "Mal Hizmet", "Miktar", "Birim Fiyat", "KDV Orani", "KDV Tutari", "Mal Hizmet Tutari"]
    for i in range(len(w_cols)): pdf.cell(w_cols[i], 8, h_cols[i], border=1, align="C", fill=True)
    pdf.ln()

    # Tablo Satırları
    pdf.set_font("Courier", "", 7)
    sira = 1
    kdv_oran_float = float(kdv_orani) if kdv_orani else 20.0
    item_printed = False

    for _, row in ekstre_df.iterrows():
        b = float(row.get('Borc', row.get('borc', 0)) or 0)
        if b <= 0: continue
        item_printed = True
        islem_adi = str(row.get('Islem', row.get('islem', '-')))
        if len(islem_adi) > 45: islem_adi = islem_adi[:42] + "..."
        k_tutari = b * (kdv_oran_float / 100.0)

        pdf.cell(w_cols[0], 6, str(sira), border=1, align="C")
        pdf.cell(w_cols[1], 6, tr(islem_adi), border=1)
        pdf.cell(w_cols[2], 6, "1 Adet", border=1, align="C")
        pdf.cell(w_cols[3], 6, f"{b:,.2f}TL", border=1, align="R")
        pdf.cell(w_cols[4], 6, f"%{kdv_oran_float:.2f}", border=1, align="C")
        pdf.cell(w_cols[5], 6, f"{k_tutari:,.2f}TL", border=1, align="R")
        pdf.cell(w_cols[6], 6, f"{b:,.2f}TL", border=1, align="R")
        pdf.ln()
        sira += 1

    if not item_printed:
        pdf.cell(w_cols[0], 6, "1", border=1, align="C")
        pdf.cell(w_cols[1], 6, "Muhtelif Dis Protez Islemleri", border=1)
        pdf.cell(w_cols[2], 6, "1 Adet", border=1, align="C")
        pdf.cell(w_cols[3], 6, f"{float(toplam_tutar):,.2f}TL", border=1, align="R")
        pdf.cell(w_cols[4], 6, f"%{kdv_oran_float:.2f}", border=1, align="C")
        pdf.cell(w_cols[5], 6, f"{float(toplam_tutar) * (kdv_oran_float / 100.0):,.2f}TL", border=1, align="R")
        pdf.cell(w_cols[6], 6, f"{float(toplam_tutar):,.2f}TL", border=1, align="R")
        pdf.ln()


    # 7. Dip Toplamlar
    pdf.ln(5)
    pdf.set_font("Courier", "B", 8)
    toplam_mal_hizmet = float(toplam_tutar)
    toplam_kdv = toplam_mal_hizmet * (kdv_oran_float / 100.0)
    genel_toplam = toplam_mal_hizmet + toplam_kdv
    sol_bosluk = sum(w_cols) - 70 
    
    toplamlar = [
        ("Mal Hizmet Toplam Tutari", f"{toplam_mal_hizmet:,.2f}TL"),
        (f"Hesaplanan GERCEK USULDE KDV (%{kdv_oran_float:.2f})", f"{toplam_kdv:,.2f}TL"),
        ("Vergiler Dahil Toplam Tutar", f"{genel_toplam:,.2f}TL"),
        ("Odenecek Tutar", f"{genel_toplam:,.2f}TL")
    ]
    for baslik, deger in toplamlar:
        pdf.set_x(10 + sol_bosluk)
        pdf.cell(45, 6, baslik, border=1, align="R", fill=False)
        pdf.cell(25, 6, deger, border=1, align="R", fill=False)
        pdf.ln()

    # 8. Yazıyla
    pdf.ln(5)
    pdf.set_font("Courier", "", 9)
    yazi = sayiyi_yaziya_cevir(genel_toplam)
    pdf.cell(0, 15, f"YALNIZ: {yazi}", border=1, ln=True)
    if aciklama:
        pdf.ln(2)
        pdf.cell(0, 6, tr(f"Aciklama: {aciklama}"), ln=True)

    pdf_out = pdf.output(dest='S')
    return pdf_out.encode('latin1') if hasattr(pdf_out, 'encode') else bytes(pdf_out)

# 💎 AYARLAR (SESSION STATE) 💎
if "w_ciro" not in st.session_state: st.session_state.update({"w_ciro": True, "w_radar": True, "w_grafikler": True})

# --- 🔒 GÜVENLİK (GİRİŞ EKRANI SİMETRİSİ VE KIOSK KİLİDİ) ---
if "giris_yapildi" not in st.session_state: st.session_state.update({"giris_yapildi": False, "kullanici_adi": "", "kullanici_rolu": "", "ana_klinik": ""})

client_ip = st.query_params.get("ip", "127.0.0.1") 
kayitli_lobi_ip = ayar_getir("Lobi_IP", "192.168.1.100")

if client_ip == kayitli_lobi_ip and kayitli_lobi_ip != "" and not st.session_state["giris_yapildi"]:
    st.session_state.update({
        "giris_yapildi": True, 
        "kullanici_adi": "Lobi_TV", 
        "kullanici_rolu": "Kiosk",
        "aktif_sayfa": "📺 Lobi / TV Ekranı",
        "ana_klinik": ""
    })
# 🚨 FAZ 41: SİBER GÜVENLİK PROTOKOLÜ KONTROLÜ 🚨
sistem_kilitli_mi = ayar_getir("Sistem_Kilitli", "Hayır")
if sistem_kilitli_mi == "Evet" and st.session_state.get("kullanici_rolu", "") != "Admin":
    st.markdown("""
        <div style="height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; background-color: #0f172a;">
            <div style="font-size: 100px;">🚨</div>
            <h1 style="color: #f87171; font-weight: 900; letter-spacing: 5px; font-size: 50px; text-shadow: 0 0 20px rgba(248,113,113,0.8);">SİSTEM KİLİTLİ</h1>
            <p style="color: #94a3b8; font-size: 20px; max-width: 600px;">Laboratuvarımızda uygulanan güvenlik protokolü veya bakım çalışması nedeniyle sistem şu an yetkisiz erişime kapatılmıştır. Lütfen yöneticinizle iletişime geçiniz.</p>
        </div>
    """, unsafe_allow_html=True)
    if st.button("🚪 Sistemi Terk Et", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.stop()
if not st.session_state["giris_yapildi"]:
    st.markdown("""
<style>
        /* FORMU DARALTMA VE ORTALAMA */
        div[data-testid="stForm"] { max-width: 360px !important; margin: 0 auto !important; }
        div[data-testid="stElementContainer"]:has(div[data-testid="stRadio"]), 
        div[data-testid="stRadio"] { display: flex !important; justify-content: center !important; align-items: center !important; width: 100% !important; margin-bottom: 10px !important;}
        div[data-testid="stRadio"] > div[role="radiogroup"] { display: inline-flex !important; justify-content: center !important; align-items: center !important; margin: 0 auto !important; width: auto !important; padding: 10px 20px !important; gap: 15px !important; background: rgba(255, 255, 255, 0.05) !important; backdrop-filter: blur(12px) !important; -webkit-backdrop-filter: blur(12px) !important; border: 1px solid rgba(255, 255, 255, 0.1) !important; border-radius: 40px !important; box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5) !important; }
        
        /* 🚨 SİNİR BOZUCU "PRESS ENTER" YAZISINI GİZLEYEN ZIRH 🚨 */
        div[data-testid="InputInstructions"] { display: none !important; }
</style>
    """, unsafe_allow_html=True)
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_space_left, col_login, col_space_right = st.columns([1, 1.2, 1])
    with col_login:
        st.markdown("""<div style='text-align: center; margin-bottom: 20px;'><div style='font-size: 90px; line-height: 1; margin-bottom: 10px; text-shadow: 0 0 30px rgba(56, 189, 248, 0.8);'>🦷</div><h1 style='color: #fff; margin: 0; font-size: 48px; font-weight: 900; letter-spacing: 3px; text-shadow: 0 0 15px rgba(255,255,255,0.3);'>OMG SMILE ERP</h1><h4 style='color: #38bdf8; margin: 0; font-weight: 600; letter-spacing: 3px;'>Dijital Ekosistem</h4></div>""", unsafe_allow_html=True)
        giris_tipi = st.radio(" ", ["👨‍🔬 Sisteme Giriş", "🏥 Klinik Portalı"], horizontal=True, label_visibility="collapsed")
        
        with st.form("giris_formu"):
            if giris_tipi == "👨‍🔬 Sisteme Giriş":
                st.markdown("<h3 style='text-align:center; color:#38bdf8;'>Laboratuvar Yetkili Girişi</h3>", unsafe_allow_html=True)
                kullanici_giris = st.text_input("Kullanıcı Adı")
                sifre_giris = st.text_input("Şifre", type="password")
                st.markdown("<br>", unsafe_allow_html=True)
                if st.form_submit_button("Sistemi Başlat", use_container_width=True):
                    sorgu = c.execute("SELECT Rol FROM kullanicilar WHERE Kullanici_Adi=? AND Sifre=?", (kullanici_giris, sifre_giris)).fetchone()
                    if sorgu: st.session_state.update({"giris_yapildi": True, "kullanici_adi": kullanici_giris, "kullanici_rolu": sorgu[0], "ana_klinik": ""}); st.rerun()
                    else: st.error("Erişim Reddedildi!")
            else:
                st.markdown("<h3 style='text-align:center; color:#38bdf8;'>Hekim VIP Portal</h3>", unsafe_allow_html=True)
                klinikler_listesi = [row[0] for row in c.execute("SELECT Klinik_Unvani FROM cariler").fetchall()]
                
                asistan_girisi_mi = st.checkbox("👩‍💻 Asistan Girişi (Alt Hesap)")
                
                if asistan_girisi_mi:
                    kullanici_giris = st.text_input("Asistan Kullanıcı Adı (Örn: OMG_Ayse)")
                else:
                    if klinikler_listesi:
                        kullanici_giris = st.selectbox("Kayıtlı Klinik", klinikler_listesi)
                    else: st.warning("Kayıtlı klinik yok."); kullanici_giris = ""
                
                sifre_giris = st.text_input("Şifre", type="password")
                st.markdown("<br>", unsafe_allow_html=True)
                if st.form_submit_button("Portala Gir", use_container_width=True):
                    if asistan_girisi_mi:
                        sorgu = c.execute("SELECT Klinik_Unvani, Sifre FROM klinik_asistanlari WHERE Asistan_Kadi=? AND Sifre=?", (kullanici_giris, sifre_giris)).fetchone()
                        if sorgu:
                            st.session_state.update({"giris_yapildi": True, "kullanici_adi": kullanici_giris, "kullanici_rolu": "Klinik_Asistan", "ana_klinik": sorgu[0]})
                            st.rerun()
                        else: st.error("Asistan bilgileri hatalı!")
                    else:
                        sorgu = c.execute("SELECT Sifre FROM cariler WHERE Klinik_Unvani=? AND Sifre=?", (kullanici_giris, sifre_giris)).fetchone()
                        if sorgu: 
                            st.session_state.update({"giris_yapildi": True, "kullanici_adi": kullanici_giris, "kullanici_rolu": "Klinik", "ana_klinik": kullanici_giris})
                            st.rerun()
                        else: st.error("Şifre Hatalı!")
    st.stop()

# --- 🚀 MENÜ YÖNLENDİRMESİ VE GÜVENLİ ROTA KONTROLÜ ---
rol = st.session_state["kullanici_rolu"]; kullanici_adi = st.session_state['kullanici_adi']
ana_klinik = st.session_state.get('ana_klinik', '')
if "aktif_sayfa" not in st.session_state: st.session_state.aktif_sayfa = "🎯 Komuta Merkezi"

if rol in ["Admin", "Yönetici"]: menu = ["🏠 Komuta Merkezi", "📅 Görev & Planlama", "📺 Lobi / TV Ekranı", "🤝 Hekim ve Cari Kayıt", "⚙️ İş Akışı", "👥 Personel Yönetimi", "📦 Stok Yönetimi", "🏢 Varlık Yönetimi", "🏭 Tedarikçi Yönetimi", "💰 Finans & Analitik", "📉 Maliyet Yönetimi", "📱 Teknisyen Terminali", "📱 WhatsApp Entegrasyonu",  "🛵 Kurye Lojistik",  "🔧 Makine Parkuru ve Bakımı", "🔐 Kullanıcı & Yetki Yönetimi", "🏢 Kurumsal Bilgi"]
elif rol == "Sekreter": menu = ["🏠 Komuta Merkezi", "📅 Görev & Planlama", "📺 Lobi / TV Ekranı", "🤝 Hekim ve Cari Kayıt", "⚙️ İş Akışı", "📱 WhatsApp Entegrasyonu", "🏭 Tedarikçi Yönetimi", "💰 Finans & Analitik", "🛵 Kurye Lojistik", "🏢 Kurumsal Bilgi"]
elif rol == "Teknisyen": menu = ["⚙️ İş Akışı", "📅 Görev & Planlama", "📺 Lobi / TV Ekranı", "📱 Teknisyen Terminali", "📦 Stok Yönetimi", "🏭 Tedarikçi Yönetimi", "🔧 Makine Parkuru ve Bakımı"]
elif rol == "Klinik": menu = ["🦷 Klinik Paneli", "📺 Lobi / TV Ekranı", "📤 Yeni Sipariş (Reçete)", "🧾 Detaylı Ekstre", "📅 Doktor Takvimi", "🏢 Kurumsal Bilgi"]
elif rol == "Klinik_Asistan": menu = ["🦷 Klinik Paneli", "📺 Lobi / TV Ekranı", "📤 Yeni Sipariş (Reçete)", "📅 Doktor Takvimi", "🏢 Kurumsal Bilgi"]
elif rol == "Kurye": menu = ["🛵 Kurye Mobil Terminali", "📺 Lobi / TV Ekranı"]
elif rol == "Kiosk": menu = ["📺 Lobi / TV Ekranı"]

if st.session_state.aktif_sayfa not in menu and st.session_state.aktif_sayfa not in ["⚙️ Ayarlar", "🤖 OMG AI Asistan"]:
    st.session_state.aktif_sayfa = menu[0]

if st.session_state.aktif_sayfa == "📺 Lobi / TV Ekranı":
    st.markdown("<style>[data-testid='stSidebar'] {display: none !important;}</style>", unsafe_allow_html=True)
    st.markdown("""<div style='text-align:center; padding:30px;'><h1 class='neon-text-blue' style='font-size:60px;'>OMG SMILE ÜRETİM MERKEZİ</h1><h3 style='color:#94a3b8; letter-spacing:5px;'>CANLI DURUM EKRANI</h3></div>""", unsafe_allow_html=True)
    df_isler = pd.read_sql("SELECT Asama, Klinik_Unvani FROM isler", conn)
    c_sip = len(df_isler[df_isler["Asama"]=="Sipariş Alındı (Hekim Girdi)"])
    c_tas = len(df_isler[df_isler["Asama"]=="Tasarım Bekliyor"])
    c_kaz = len(df_isler[df_isler["Asama"]=="Kazıma/Döküm"])
    c_fir = len(df_isler[df_isler["Asama"]=="Seramik/Fırın"])
    c_tes = len(df_isler[df_isler["Asama"]=="Teslim Edildi"])
    
    st.markdown(f"""
        <div class="radar-container" style="padding: 60px 20px;">
            <div class="radar-line"></div>
            <div class="radar-step {'step-active' if c_sip > 0 else ''}"><div class="radar-circle">{c_sip}</div><div class="radar-label">Sipariş<br>Alındı</div></div>
            <div class="radar-step {'step-active' if c_tas > 0 else ''}"><div class="radar-circle">{c_tas}</div><div class="radar-label">CAD<br>Tasarım</div></div>
            <div class="radar-step {'step-active' if c_kaz > 0 else ''}"><div class="radar-circle">{c_kaz}</div><div class="radar-label">CAM<br>Kazıma</div></div>
            <div class="radar-step {'step-active' if c_fir > 0 else ''}"><div class="radar-circle">{c_fir}</div><div class="radar-label">Fırın &<br>Seramik</div></div>
            <div class="radar-step step-active"><div class="radar-circle" style="border-color:#34d399; color:#34d399;">{c_tes}</div><div class="radar-label" style="color:#34d399;">Teslim<br>Edildi</div></div>
        </div>
    """, unsafe_allow_html=True)
    
    l1, l2 = st.columns(2)
    kurye_bekleyen = c.execute("SELECT count(*) FROM kurye_islemleri WHERE Durum='Bekliyor'").fetchone()[0]
    l1.markdown(f"<div class='glass-card' style='text-align:center;'><h2 style='color:#FFFFFF;'>Toplam Aktif İş</h2><h1 class='neon-text-blue' style='font-size:80px;'>{c_sip+c_tas+c_kaz+c_fir}</h1></div>", unsafe_allow_html=True)
    l2.markdown(f"<div class='glass-card' style='text-align:center;'><h2 style='color:#FFFFFF;'>Bekleyen Kurye</h2><h1 class='neon-text-red' style='font-size:80px;'>{kurye_bekleyen}</h1></div>", unsafe_allow_html=True)
    
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    if rol != "Kiosk":
        if st.button("🔙 Lobi Modundan Çık / Panele Dön", use_container_width=True):
            st.session_state.aktif_sayfa = menu[0]; st.rerun()
    st.stop()

    # 💎 FAZ 40: KURYE MOBİL TERMİNALİ (TAM EKRAN APP) 💎
if st.session_state.aktif_sayfa == "🛵 Kurye Mobil Terminali":
    st.markdown("<style>[data-testid='stSidebar'] {display: none !important;}</style>", unsafe_allow_html=True)
    st.markdown("""<div style='text-align:center; padding:20px;'><h2 class='neon-text-blue' style='font-size:30px;'>OMG Lojistik</h2><h4 style='color:#94a3b8;'>Canlı Kurye Rota Ekranı</h4></div>""", unsafe_allow_html=True)
    
    bekleyenler = pd.read_sql("SELECT id, Tarih, Saat, Klinik_Unvani, Aciklama FROM kurye_islemleri WHERE Durum='Bekliyor' ORDER BY Tarih ASC, Saat ASC", conn)
    if not bekleyenler.empty:
        for _, r in bekleyenler.iterrows():
            klinik_adi = r["Klinik_Unvani"]
            adres_sorgu = c.execute("SELECT Adres FROM cariler WHERE Klinik_Unvani=?", (klinik_adi,)).fetchone()
            k_adres = adres_sorgu[0] if adres_sorgu and adres_sorgu[0] != "-" else "Adres Kayıtlı Değil"
            
            st.markdown(f"""
            <div class="glass-card" style="margin-bottom:15px; border-left: 5px solid #FBBF24;">
                <h3 style="margin-top:0; color:#FBBF24;">{klinik_adi}</h3>
                <p><b>Talep:</b> {r["Tarih"]} {r["Saat"]}<br><b>Açıklama:</b> {r["Aciklama"]}</p>
                <p style="color:#9CA3AF; font-size:14px;">📍 {k_adres}</p>
            </div>
            """, unsafe_allow_html=True)
            
            col_k1, col_k2 = st.columns(2)
            harita_url = f"http://maps.google.com/?q={urllib.parse.quote(k_adres)}"
            col_k1.markdown(f"""<a href="{harita_url}" target="_blank" class="wp-btn" style="background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);">🗺️ Haritada Aç</a>""", unsafe_allow_html=True)
            
            if col_k2.button(f"✅ İşi Teslim Aldım (ID: {r['id']})", key=f"teslim_{r['id']}", use_container_width=True):
                c.execute("UPDATE kurye_islemleri SET Durum='Teslim Alındı (Laboratuvara Geldi)' WHERE id=?", (r['id'],))
                conn.commit(); st.success("İş teslim alındı ve merkeze bildirildi!"); st.rerun()
            st.markdown("<hr>", unsafe_allow_html=True)
    else:
        st.success("🎉 Şimdilik bekleyen hiçbir rota yok. Beklemede kalın!")
    
    st.markdown("<br><br>", unsafe_allow_html=True)
    if st.button("🚪 Sistemden Çıkış Yap", use_container_width=True):
        st.session_state.clear(); st.rerun()
    st.stop()

# --- STANDART MENÜ ---
# --- SİDEBAR (LOGO DESTEKLİ) ---
logo_yolu = ayar_getir("Kurumsal_Logo", "-")
if logo_yolu != "-" and os.path.exists(logo_yolu):
    st.sidebar.image(logo_yolu, use_container_width=True)
else:
    st.sidebar.markdown("<div style='text-align:center; margin-bottom:20px;'><span style='font-size:40px;'>🦷</span><h2 style='margin:0; letter-spacing:2px;'>OMG SMILE</h2></div>", unsafe_allow_html=True)

alt_baslik = f"{rol} Yetkisi" if rol != "Klinik_Asistan" else f"{ana_klinik} Asistanı"
st.sidebar.markdown(f"""<div class='glass-card' style='padding: 15px; text-align:center; margin-bottom:20px;'><h4 class='neon-text-blue' style='margin:0;'>{kullanici_adi.upper()}</h4><span style='color:#FFFFFF; font-size:12px;'>{alt_baslik}</span></div>""", unsafe_allow_html=True)

kategoriler = {
    "🛠️ 1. Operasyon & Üretim": [
        "🏠 Komuta Merkezi", "📅 Görev & Planlama", "⚙️ İş Akışı", 
        "📱 Teknisyen Terminali", "📺 Lobi / TV Ekranı", "🦷 Klinik Paneli"
    ],
    "🤝 2. Müşteri & İletişim (CRM)": [
        "🤝 Hekim ve Cari Kayıt", "📱 WhatsApp Entegrasyonu", "🛵 Kurye Lojistik",
        "📤 Yeni Sipariş (Reçete)", "🛵 Kurye Mobil Terminali", "📅 Doktor Takvimi"
    ],
    "💰 3. Finans & Tedarik": [
        "💰 Finans & Analitik", "📉 Maliyet Yönetimi", "📦 Stok Yönetimi", 
        "🏭 Tedarikçi Yönetimi", "🧾 Detaylı Ekstre"
    ],
    "🏢 4. Altyapı & Yönetim": [
        "🔧 Makine Parkuru ve Bakımı", "🏢 Varlık Yönetimi", 
        "👥 Personel Yönetimi", "🔐 Kullanıcı & Yetki Yönetimi"
    ]
}

kategori_bulundu = False
for mods in kategoriler.values():
    if st.session_state.aktif_sayfa in mods:
        kategori_bulundu = True
        break

for kat_adi, moduller in kategoriler.items():
    izinli_moduller = [m for m in moduller if m in menu]
    if izinli_moduller:
        is_expanded = (st.session_state.aktif_sayfa in izinli_moduller) or (not kategori_bulundu and kat_adi.startswith("🛠️"))
        with st.sidebar.expander(kat_adi, expanded=is_expanded):
            for modul in izinli_moduller:
                btn_type = "primary" if modul == st.session_state.aktif_sayfa else "secondary"
                if st.button(modul, key=f"nav_{modul}", use_container_width=True, type=btn_type):
                    st.session_state.aktif_sayfa = modul
                    st.rerun()

# Diğer modüller menüsü iptal edildi (ekstra_moduller)

st.sidebar.markdown("<br>", unsafe_allow_html=True)

st.sidebar.markdown("""
<style>
    [data-testid=\"stSidebar\"] > div:first-child {
        display: flex;
        flex-direction: column;
        height: 100vh;
    }
    [data-testid=\"stSidebar\"] .stMarkdown:has(div.bottom-spacer) {
        flex-grow: 1 !important;
    }
    div.bottom-spacer {
        height: 100%;
    }
</style>
<div class=\"bottom-spacer\"></div>
""", unsafe_allow_html=True)

if rol in ["Admin", "Yönetici", "Sekreter"]:
    if st.sidebar.button("🤖 OMG AI Asistan", type="primary", use_container_width=True): st.session_state.aktif_sayfa = "🤖 OMG AI Asistan"; st.rerun()

if "🏢 Kurumsal Bilgi" in menu:
    if st.sidebar.button("🏢 Kurumsal Bilgi", type="primary", use_container_width=True):
        st.session_state.aktif_sayfa = "🏢 Kurumsal Bilgi"
        st.rerun()

st.sidebar.markdown("<hr style='border-color: rgba(56, 189, 248, 0.2); margin: 5px 0;'>", unsafe_allow_html=True)
if rol not in ["Teknisyen", "Kiosk", "Klinik_Asistan"]:
    c1, c2 = st.sidebar.columns(2)
    if c1.button("🚪 Çıkış", help="Sistemden Çıkış Yap", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    if c2.button("⚙️ Ayarlar", help="Sistem ve Güvenlik Ayarları", use_container_width=True):
        st.session_state.aktif_sayfa = "⚙️ Ayarlar"
        st.rerun()
else:
    if st.sidebar.button("🚪 Çıkış Yap", help="Sistemden Çıkış Yap", use_container_width=True):
        st.session_state.clear()
        st.rerun()

sayfa = st.session_state.aktif_sayfa

# =====================================================================
# --- # =====================================================================
# --- 🦷 KLİNİK (HEKİM & ASİSTAN) ARAYÜZÜ ---
# =====================================================================
if rol in ["Klinik", "Klinik_Asistan"]:
    
    vip_sorgu = c.execute("SELECT VIP_Seviye FROM cariler WHERE Klinik_Unvani=?", (ana_klinik,)).fetchone()
    vip_svy = vip_sorgu[0] if vip_sorgu else "Standart"
    vip_renk = "neon-text-gold" if vip_svy == "Gold" else "neon-text-plat" if vip_svy == "Platinum" else "neon-text-blue"
    vip_rozet = f" <span style='font-size:18px; vertical-align:middle;' title='{vip_svy} Müşteri'>{'👑' if vip_svy == 'Gold' else '💎' if vip_svy == 'Platinum' else ''}</span>" if vip_svy != "Standart" else ""

    hosgeldin_yazi = f"🦷 {kullanici_adi.upper()}{vip_rozet}" if rol == "Klinik" else f"👩‍💻 {kullanici_adi.upper()} (Asistan)"
    
    st.markdown(f"""
    <div class="glass-card" style="text-align: center; margin-bottom: 30px; border-color: rgba(59, 130, 246, 0.5);">
        <h1 class="{vip_renk}" style="font-size: 40px; margin: 0;">{hosgeldin_yazi}</h1>
        <p style="color: #93c5fd; letter-spacing: 4px; margin-top: 5px;">VİP DİJİTAL KLİNİK PORTALI</p>
    </div>
    """, unsafe_allow_html=True)

    if sayfa == "🦷 Klinik Paneli":
        kurye_durumu = c.execute("SELECT Tarih, Saat, Aciklama, Durum FROM kurye_islemleri WHERE Klinik_Unvani=? ORDER BY id DESC LIMIT 1", (ana_klinik,)).fetchone()
        if kurye_durumu:
            k_tarih, k_saat, k_aciklama, k_durum = kurye_durumu
            if k_durum == "Bekliyor": k_renk, k_ikon, k_mesaj = "#FBBF24", "⏳", "Kurye Talebiniz Alındı, Yönlendirme Bekleniyor..."
            elif k_durum == "Kurye Yolda": k_renk, k_ikon, k_mesaj = "#38BDF8", "🛵", "Kuryemiz Yola Çıktı, Size Doğru Geliyor!"
            else: k_renk, k_ikon, k_mesaj = "#10B981", "✅", "İşleriniz Laboratuvara Ulaştı ve Üretime Alındı."
            st.markdown(f"""
            <div class="glass-card" style="text-align: center; margin-bottom: 25px; border-color:{k_renk}; box-shadow: 0 0 15px {k_renk}40;">
                <h3 style="color:{k_renk}; margin-top:0;">{k_ikon} Canlı Lojistik Radarı</h3>
                <p style="font-size:20px; color:#FFFFFF; font-weight:bold; margin-bottom:5px;">{k_mesaj}</p>
                <span style="color:#FFFFFF; font-size:14px;">Son Talep: {k_tarih} {k_saat} | Durum: <b>{k_durum}</b></span>
            </div>
            """, unsafe_allow_html=True)
            
        df_isler = pd.read_sql(f"SELECT * FROM isler WHERE Klinik_Unvani='{ana_klinik}'", conn)
        
        if rol == "Klinik_Asistan":
            m1, m2 = st.columns(2)
            m1.markdown(f"""<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>Laboratuvardaki İşler</span><br><span class='neon-text-blue' style='font-size:32px;'>{len(df_isler[df_isler["Asama"] != "Teslim Edildi"])}</span></div>""", unsafe_allow_html=True)
            m2.markdown(f"""<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>Teslim Edilenler</span><br><span class='neon-text-green' style='font-size:32px;'>{len(df_isler[df_isler["Asama"] == "Teslim Edildi"])}</span></div>""", unsafe_allow_html=True)
        else:
            _toplam_is = c.execute("SELECT SUM(Tutar_TL) FROM isler WHERE Klinik_Unvani=? AND Bakiye_Durumu='Aktarıldı'", (ana_klinik,)).fetchone()[0] or 0.0
            _kdv = float(ayar_getir("KDV_Orani", "20"))
            _tahs_kdvli = c.execute("SELECT SUM(Tutar) FROM tahsilatlar WHERE Klinik_Unvani=?", (ana_klinik,)).fetchone()[0] or 0.0
            _tahs_net = _tahs_kdvli / (1.0 + (_kdv / 100.0))
            anlik_bakiye = _toplam_is - _tahs_net
            para_birimi = ayar_getir("Para_Birimi", "TL")
            m1, m2, m3 = st.columns(3)
            m1.markdown(f"""<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>Laboratuvardaki İşler</span><br><span class='neon-text-blue' style='font-size:32px;'>{len(df_isler[df_isler["Asama"] != "Teslim Edildi"])}</span></div>""", unsafe_allow_html=True)
            m2.markdown(f"""<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>Teslim Edilenler</span><br><span class='neon-text-green' style='font-size:32px;'>{len(df_isler[df_isler["Asama"] == "Teslim Edildi"])}</span></div>""", unsafe_allow_html=True)
            m3.markdown(f"""<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>Güncel Borç (Bakiye)</span><br><span class='neon-text-red' style='font-size:32px;'>{anlik_bakiye:,.2f} {para_birimi}</span></div>""", unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("🛵 Laboratuvardan Kurye Çağır", expanded=False):
            with st.form("kurye_formu"):
                kurye_notu = st.text_area("Açıklama (Örn: 3 adet ölçü, 1 adet kapanış)")
                if st.form_submit_button("🚀 Kurye Talebini İlet"):
                    c.execute("INSERT INTO kurye_islemleri (Tarih, Saat, Klinik_Unvani, Aciklama, Durum) VALUES (?,?,?,?,?)", (datetime.now().strftime('%Y-%m-%d'), datetime.now().strftime('%H:%M'), ana_klinik, kurye_notu, "Bekliyor"))
                    conn.commit(); st.success("Talebiniz laboratuvara iletildi!")
        
        st.subheader("🔍 Aktif ve Tamamlanan Siparişleriniz")
        if not df_isler.empty:
            df_isler = df_isler.sort_values(by="Tarih", ascending=False).reset_index(drop=True)
            goster_cols = ["Tarih", "Hasta_Kodu", "Hasta_Adi", "Is_Turu", "Asama"]
            mevcut_cols = [c for c in goster_cols if c in df_isler.columns]
            df_goster = df_isler[mevcut_cols].copy()
            df_goster = df_goster.rename(columns={"Tarih": "TARİH", "Hasta_Kodu": "HASTA KODU", "Hasta_Adi": "HASTA ADI", "Is_Turu": "İŞLEM TÜRÜ", "Asama": "AŞAMA"})
            secili_klinik_is = st.dataframe(df_goster, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row")
            if secili_klinik_is.selection.rows:
                s_idx = secili_klinik_is.selection.rows[0]
                s_hasta = df_isler.iloc[s_idx]["Hasta_Adi"]
                st.markdown("---")
                hasta_karti_goster(s_hasta, ana_klinik)
                st.markdown("---")
        else: st.info("Henüz bir iş göndermediniz.")

    elif sayfa == "📅 Doktor Takvimi":
        TAKVIM_URL = "https://3f240962e9f3e342-104-28-154-250.serveousercontent.com"
        st.markdown("""
        <div class="glass-card" style="text-align:center; margin-bottom:18px; border-color:rgba(99,102,241,0.5);">
            <h2 style="color:#818cf8; margin:0;">📅 Doktor Takvimi</h2>
            <p style="color:#c7d2fe; margin-top:6px; font-size:14px; letter-spacing:2px;">RANDEVU VE PROGRAM YÖNETİMİ</p>
        </div>
        """, unsafe_allow_html=True)

        # Dışarıda aç butonu
        btn_col, spacer = st.columns([1, 3])
        btn_col.link_button(
            "🔗 Takvimi Yeni Sekmede Aç",
            f"{TAKVIM_URL}/login",
            use_container_width=True,
            type="primary"
        )

        # iframe gömme
        st.markdown(
            f"""
            <div style="border-radius:14px; overflow:hidden; border:1.5px solid rgba(99,102,241,0.4); 
                        box-shadow: 0 0 30px rgba(99,102,241,0.15); margin-top:10px;">
                <iframe
                    src="{TAKVIM_URL}/login"
                    width="100%"
                    height="820"
                    frameborder="0"
                    allow="fullscreen"
                    sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-top-navigation-by-user-activation"
                    style="border:none; display:block; background:#0f172a;"
                ></iframe>
            </div>
            """,
            unsafe_allow_html=True
        )

    elif sayfa == "📤 Yeni Sipariş (Reçete)":
        
        # 🚨 İŞTE SENİN PREMIUM UPLOADER ZIRHINI BURAYA EKLİYORUZ 🚨
        st.markdown("""
<style>
            /* Sürükle-Bırak Alanının Kutusu */
            div[data-testid="stFileUploader"] > section {
                background-color: #0F1626 !important;
                border: 2px dashed #3A3B3C !important;
                border-radius: 10px !important;
                padding: 20px !important;
            }
            
            /* Yazıların Rengi */
            div[data-testid="stFileUploader"] > section * {
                color: #E4E6EB !important;
            }
            
            /* Dosya Seç Butonu (İnci Beyazı Yazı & Medikal Mavi Zemin) */
            div[data-testid="stFileUploader"] button {
                background-color: #1877F2 !important;
                color: #ffffff !important;
                border: none !important;
                font-weight: 800 !important;
                border-radius: 8px !important;
                padding: 6px 18px !important;
                transition: 0.3s !important;
            }

            div[data-testid="stFileUploader"] button:hover {
                background-color: #166FE5 !important;
                box-shadow: 0 4px 10px rgba(24,119,242,0.4) !important;
                transform: scale(1.02) !important;
            }
</style>
        """, unsafe_allow_html=True)

        banner_olustur("📤", "Yeni Sipariş Gönder", "Laboratuvara dijital reçetenizi iletin.")
        
        # 💎 FAZ 38: OTOPİLOT REÇETE VERİLERİNİ ÇEK 💎
        oto_veri = c.execute("SELECT Otopilot_Kategori, Otopilot_Islem, Otopilot_Renk FROM cariler WHERE Klinik_Unvani=?", (ana_klinik,)).fetchone()
        
        # ... BURADAN AŞAĞISI SENİN KODUNDAKİ GİBİ DEVAM EDİYOR ...
        varsayilan_kat = oto_veri[0] if oto_veri and oto_veri[0] != '-' else KATEGORILER[0]
        kat_idx = KATEGORILER.index(varsayilan_kat) if varsayilan_kat in KATEGORILER else 0
        
        kat_sec = st.selectbox("İşlem Kategorisi", KATEGORILER, index=kat_idx)
        
        import random
        c_out1, c_out2 = st.columns([2, 1])
        ha = c_out1.text_input("Hasta Adı / Dosya No", key="hekim_ha_input")
        h_kodu = ""
        if ha:
            mevcut_kodlar = [m[0] for m in c.execute("SELECT DISTINCT Hasta_Kodu FROM isler WHERE Hasta_Adi=? AND Hasta_Kodu != '-' AND Klinik_Unvani=?", (ha, ana_klinik)).fetchall()]
            if mevcut_kodlar:
                h_kodu_secim = c_out2.selectbox("Hasta Kodu (Kayıtlı)", mevcut_kodlar + ["Yeni Kod Oluştur"])
                if h_kodu_secim == "Yeni Kod Oluştur":
                    h_kodu = f"OMG-HST-{random.randint(100000, 999999)}"
                    c_out2.info(f"Yeni kod oluşturulacak: {h_kodu}")
                else:
                    h_kodu = h_kodu_secim
            else:
                h_kodu = f"OMG-HST-{random.randint(100000, 999999)}"
                c_out2.text_input("Hasta Kodu", value=h_kodu, disabled=True)
        else:
            c_out2.text_input("Hasta Kodu", disabled=True)

        with st.form("klinik_yeni_is"):
            c1, c2 = st.columns([1, 1])
            
            hizmetler = c.execute("SELECT Hizmet_Adi FROM fiyat_listesi WHERE Kategori=?", (kat_sec,)).fetchall()
            hizmet_listesi = [h[0] for h in hizmetler] if hizmetler else ["-"]
            
            v_islem = oto_veri[1] if oto_veri and oto_veri[1] != '-' else "-"
            islem_idx = hizmet_listesi.index(v_islem) if v_islem in hizmet_listesi else 0
            
            secilen = c2.selectbox("Yapılmasını İstediğiniz İşlem", hizmet_listesi, index=islem_idx)
            renk = c1.text_input("Diş Rengi", value=oto_veri[2] if oto_veri and oto_veri[2] != '-' else "A2")
            teslim_tarihi = c2.date_input("İstenen Teslim Tarihi").strftime("%Y-%m-%d")
            
            yuklenen_stl = st.file_uploader("3D Tarama Dosyası (.stl)", type=["stl"])
            yuklenen_foto = st.file_uploader("Ağız İçi Fotoğrafları (.jpg, .png)", type=["jpg", "jpeg", "png"])
            
            if st.form_submit_button("🚀 Siparişi Onayla"):
                if ha and hizmetler:
                    c.execute("INSERT INTO isler (Tarih, Klinik_Unvani, Hasta_Adi, Is_Turu, Renk, Asama, Tutar_TL, Sorumlu_Personel, Harcanan_Malzeme, Teslim_Tarihi, Barkod, Lot_Numarasi, Sertifika_No, Aciklama, Hasta_Kodu) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (datetime.now().strftime("%Y-%m-%d"), ana_klinik, ha, secilen, renk, "Sipariş Alındı (Hekim Girdi)", 0.0, "-", "-", teslim_tarihi, "-", "-", "-", "-", h_kodu))
                    yeni_id = c.lastrowid
                    onek = ayar_getir("Barkod_Onek", "OMG")
                    yeni_barkod = f"{onek}-{yeni_id:06d}"
                    c.execute("UPDATE isler SET Barkod=? WHERE id=?", (yeni_barkod, yeni_id))
                    
                    hedef_klasor = akilli_klasor_yolu(ana_klinik, ha)
                    if yuklenen_stl:
                        dosya_yolu_stl = os.path.join(hedef_klasor, f"STL_{yeni_id}_{yuklenen_stl.name}")
                        dosya_yolu_stl = storage_utils.dosya_kaydet(os.path.dirname(dosya_yolu_stl), os.path.basename(dosya_yolu_stl), yuklenen_stl)
                        c.execute("INSERT INTO is_3d_modelleri (Is_ID, Dosya_Yolu) VALUES (?, ?)", (yeni_id, dosya_yolu_stl))
                    if yuklenen_foto:
                        dosya_yolu_foto = os.path.join(hedef_klasor, f"FOTO_{yeni_id}_{yuklenen_foto.name}")
                        dosya_yolu_foto = storage_utils.dosya_kaydet(os.path.dirname(dosya_yolu_foto), os.path.basename(dosya_yolu_foto), yuklenen_foto)
                        c.execute("INSERT INTO is_fotograflari (Is_ID, Dosya_Yolu) VALUES (?, ?)", (yeni_id, dosya_yolu_foto))
                    conn.commit(); st.success(f"Sipariş İletildi! Barkod: {yeni_barkod}"); st.balloons()
                elif not ha: st.error("Lütfen Hasta Adı giriniz!")
                # 💎 KLİNİK İÇİN GÜNCEL FİYAT LİSTESİ (AÇILIR PANOLU) 💎
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("📊 Güncel Laboratuvar Fiyat Tarifesi", expanded=False):
            df_fiyat_klinik = pd.read_sql('SELECT Hizmet_Adi as "İşlem", Kategori, Fiyat, Para_Birimi FROM fiyat_listesi', conn)
            if not df_fiyat_klinik.empty:
                st.dataframe(df_fiyat_klinik, hide_index=True, use_container_width=True)
            else:
                st.info("Fiyat listesi şu an güncelleniyor...")


    elif sayfa == "🏢 Kurumsal Bilgi":
        banner_olustur("🏢", "Laboratuvar Kurumsal Bilgi", "Laboratuvarımıza ait resmi kurumsal bilgiler, vergi, ödeme ve iletişim detayları.")
        
        lab_adi = ayar_getir("Lab_Ad", "OMG Smile Sistem")
        lab_unvan = ayar_getir("Lab_Unvan", "Belirtilmemiş")
        lab_kurulus = ayar_getir("Lab_Kurulus_Tarihi", "Bilinmiyor")
        lab_sorumlu = ayar_getir("Lab_Sorumlu_Kisi", "Belirtilmemiş")
        lab_vergi_no = ayar_getir("Lab_Vergi_No", "Belirtilmemiş")
        lab_vergi_dairesi = ayar_getir("Lab_Vergi_Dairesi", "Belirtilmemiş")
        lab_iban = ayar_getir("Lab_IBAN", "TR00 0000 0000 0000 0000 0000 00")
        lab_kep = ayar_getir("Lab_Kep", "Belirtilmemiş")
        lab_telefon = ayar_getir("Lab_Telefon", "Belirtilmemiş")
        lab_email = ayar_getir("Lab_Email", "Belirtilmemiş")
        lab_web = ayar_getir("Lab_Web", "Belirtilmemiş")
        lab_adres = ayar_getir("Lab_Adres", "Belirtilmemiş")
        
        st.markdown(f"""
        <div class='glass-card' style='padding: 30px; border-radius: 15px; text-align: center; margin-bottom: 20px;'>
            <h1 style='color: #4CAF50; font-size: 2.5em; margin-bottom: 10px;'>{lab_adi}</h1>
            <h4 style='color: #E5E9F0; font-weight: normal; margin-top: -5px; margin-bottom: 20px;'>{lab_unvan}</h4>
            <hr style='border-top: 2px solid rgba(255,255,255,0.1); margin: 20px 0;'>
            <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; text-align: left;'>
                <div style='background: rgba(255,255,255,0.05); padding: 20px; border-radius: 10px;'>
                    <h3 style='color: #88C0D0; margin-bottom: 15px;'><i class='fas fa-info-circle'></i> Genel Bilgiler</h3>
                    <p><b>🏢 Kuruluş Tarihi:</b> <span style='color:#E5E9F0;'>{lab_kurulus}</span></p>
                    <p><b>👨‍💼 Sorumlu Kişi:</b> <span style='color:#E5E9F0;'>{lab_sorumlu}</span></p>
                    <p><b>🌐 Web Sitesi:</b> <span style='color:#88C0D0;'>{lab_web}</span></p>
                </div>
                <div style='background: rgba(255,255,255,0.05); padding: 20px; border-radius: 10px;'>
                    <h3 style='color: #A3BE8C; margin-bottom: 15px;'><i class='fas fa-file-invoice-dollar'></i> Finans & Vergi</h3>
                    <p><b>💳 IBAN:</b> <span style='color:#EBCB8B; font-family: monospace; font-size: 1.1em;'>{lab_iban}</span></p>
                    <p><b>🏛️ Vergi Dairesi:</b> <span style='color:#E5E9F0;'>{lab_vergi_dairesi}</span></p>
                    <p><b>📑 Vergi No:</b> <span style='color:#E5E9F0;'>{lab_vergi_no}</span></p>
                </div>
                <div style='background: rgba(255,255,255,0.05); padding: 20px; border-radius: 10px;'>
                    <h3 style='color: #EBCB8B; margin-bottom: 15px;'><i class='fas fa-address-book'></i> İletişim Bilgileri</h3>
                    <p><b>📞 Telefon:</b> <span style='color:#E5E9F0;'>{lab_telefon}</span></p>
                    <p><b>✉️ E-Mail:</b> <span style='color:#E5E9F0;'>{lab_email}</span></p>
                    <p><b>🔏 KEP Adresi:</b> <span style='color:#E5E9F0;'>{lab_kep}</span></p>
                    <p><b>📍 Adres:</b> <span style='color:#E5E9F0;'>{lab_adres}</span></p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
    elif sayfa == "🧾 Detaylı Ekstre" and rol == "Klinik":
        banner_olustur("🧾", "Detaylı Hesap Ekstresi", "Borç ve ödeme geçmişinizi takip edin.")
        _toplam_is = c.execute("SELECT SUM(Tutar_TL) FROM isler WHERE Klinik_Unvani=? AND Bakiye_Durumu='Aktarıldı'", (kullanici_adi,)).fetchone()[0] or 0.0
        _kdv = float(ayar_getir("KDV_Orani", "20"))
        _tahs_kdvli = c.execute("SELECT SUM(Tutar) FROM tahsilatlar WHERE Klinik_Unvani=?", (kullanici_adi,)).fetchone()[0] or 0.0
        _tahs_net = _tahs_kdvli / (1.0 + (_kdv / 100.0))
        anlik_bakiye = _toplam_is - _tahs_net
        para_birimi = ayar_getir("Para_Birimi", "TL")
        st.markdown(f"<div class='glass-card' style='text-align:center;'><h2 style='color:#FFFFFF;'>Güncel Borcunuz</h2><h1 class='neon-text-red'>{anlik_bakiye:,.2f} {para_birimi}</h1></div>", unsafe_allow_html=True)
        
        df_ch_borc = pd.read_sql(f"SELECT Tarih, Barkod, Hasta_Adi, Is_Turu, Tutar_TL as borc FROM isler WHERE Klinik_Unvani='{kullanici_adi}' AND Bakiye_Durumu='Aktarıldı' AND (Tutar_TL > 0 OR Is_Turu LIKE '%(RPT)%')", conn)
        df_ch_alacak = pd.read_sql(f"SELECT id, Tarih, Odeme_Turu, Aciklama, Tutar as alacak FROM tahsilatlar WHERE Klinik_Unvani='{kullanici_adi}'", conn)
        
        df_list = []
        if not df_ch_borc.empty:
            df_ch_borc.columns = [c.lower() for c in df_ch_borc.columns]
            df_ch_borc['belge_no'] = df_ch_borc['barkod']
            df_ch_borc['aciklama'] = df_ch_borc['hasta_adi'].astype(str) + ' - ' + df_ch_borc['is_turu'].astype(str)
            df_ch_borc['alacak'] = 0.0
            df_list.append(df_ch_borc[['tarih', 'belge_no', 'aciklama', 'borc', 'alacak']])
        
        if not df_ch_alacak.empty:
            df_ch_alacak.columns = [c.lower() for c in df_ch_alacak.columns]
            df_ch_alacak['belge_no'] = 'TAH-' + df_ch_alacak['id'].astype(str)
            df_ch_alacak['aciklama'] = df_ch_alacak['odeme_turu'].astype(str) + ' Tahsilatı (' + df_ch_alacak['aciklama'].astype(str) + ')'
            df_ch_alacak['borc'] = 0.0
            kdv_c = float(ayar_getir("KDV_Orani", "20"))
            carpan_c = 1.0 + (kdv_c / 100.0)
            df_ch_alacak['alacak'] = df_ch_alacak['alacak'] / carpan_c
            df_list.append(df_ch_alacak[['tarih', 'belge_no', 'aciklama', 'borc', 'alacak']])
        
        if df_list:
            df_hareket = pd.concat(df_list).sort_values(by="tarih").reset_index(drop=True)
            df_hareket['bakiye'] = df_hareket['borc'].cumsum() - df_hareket['alacak'].cumsum()
            df_hareket_ters = df_hareket.iloc[::-1].reset_index(drop=True)
        
            df_goster_ch = df_hareket_ters.rename(columns={
                "tarih": "TARİH", "belge_no": "BELGE NO", "aciklama": "AÇIKLAMA", "borc": "BORÇ", "alacak": "ALACAK", "bakiye": "BAKİYE"
            })
        
            st.markdown("---")
            st.dataframe(df_goster_ch.style.format({
                "BORÇ": "{:,.2f} ₺", "ALACAK": "{:,.2f} ₺", "BAKİYE": "{:,.2f} ₺"
            }), hide_index=True, use_container_width=True)
        
            df_ekstre = df_hareket.copy()
            df_ekstre['Islem'] = df_ekstre['belge_no'].astype(str) + " - " + df_ekstre['aciklama'].astype(str)
            df_ekstre = df_ekstre.rename(columns={"tarih": "Tarih", "borc": "Borc", "alacak": "Alacak", "bakiye": "Kümülatif Bakiye"})
        
            pdf_dosyasi = ekstre_pdf_uret(kullanici_adi, df_ekstre, anlik_bakiye)
            st.download_button("📥 PDF İndir & Yazdır", data=pdf_dosyasi, file_name=f"{kullanici_adi}_Ekstre.pdf", mime="application/pdf", type="primary", use_container_width=True)
        else:
            st.info("Laboratuvarımız ile henüz bir finansal (işlem/ödeme) geçmişiniz bulunmuyor.")

    # 💎 HEKİM PANELİ VIP AYARLAR (FAZ 36, 37, 38) 💎
    elif sayfa == "⚙️ Ayarlar" and rol == "Klinik":
        banner_olustur("⚙️", "Klinik Ayarları", "Şifre, güvenlik, asistan ve otonom laboratuvar tercihlerinizi yönetin.")
        
        tab_sifre, tab_asistan, tab_bildirim, tab_otopilot = st.tabs(["🔑 Şifre Değiştir", "👥 Asistan / Alt Hesaplar", "🔔 Bildirim Tercihleri", "⚡ Otopilot Reçete"])
        
        with tab_sifre:
            col_bos1, col_form, col_bos2 = st.columns([1, 2, 1])
            with col_form:
                with st.form("sifre_degistir_form_hekim"):
                    st.markdown("#### 🔑 Şifre Değiştirme Merkezi")
                    eski_s = st.text_input("Mevcut Şifreniz", type="password")
                    yeni_s = st.text_input("Yeni Şifre Belirleyin", type="password")
                    if st.form_submit_button("Şifreyi Güncelle", type="primary", use_container_width=True):
                        gercek_eski = c.execute("SELECT Sifre FROM cariler WHERE Klinik_Unvani=?", (kullanici_adi,)).fetchone()[0]
                        if eski_s == gercek_eski: 
                            c.execute("UPDATE cariler SET Sifre=? WHERE Klinik_Unvani=?", (yeni_s, kullanici_adi))
                            conn.commit(); st.success("Şifreniz başarıyla değiştirildi!")
                        else: st.error("Eski şifre hatalı!")
                        
        with tab_asistan:
            st.markdown("### 👥 Asistan Hesapları")
            st.info("Oluşturduğunuz asistan hesapları 'Güncel Borç' ve 'Ekstre' bilgilerini göremez, sadece laboratuvara iş fırlatabilir ve kurye çağırabilir.")
            with st.form("yeni_asistan"):
                a_kadi = st.text_input("Asistan Kullanıcı Adı (Örn: OMG_Asistan_Ayse)")
                a_sifre = st.text_input("Asistan Şifresi", type="password")
                if st.form_submit_button("Asistan Hesabı Oluştur", type="primary"):
                    if c.execute("SELECT count(*) FROM klinik_asistanlari WHERE Asistan_Kadi=?", (a_kadi,)).fetchone()[0] > 0:
                        st.error("Bu asistan kullanıcı adı zaten başka bir klinikte kullanılıyor! Lütfen farklı bir isim seçin.")
                    elif a_kadi and a_sifre:
                        c.execute("INSERT INTO klinik_asistanlari (Klinik_Unvani, Asistan_Kadi, Sifre) VALUES (?,?,?)", (kullanici_adi, a_kadi, a_sifre))
                        conn.commit(); st.success("Asistan hesabı başarıyla açıldı!"); st.rerun()
            
            st.markdown("#### 📋 Mevcut Asistanlar")
            asistanlar = pd.read_sql('SELECT Asistan_Kadi as "Kullanıcı Adı", \'Kısıtlı Erişim (Sadece Üretim ve Lojistik)\' as Yetki FROM klinik_asistanlari WHERE Klinik_Unvani=?', conn, params=(kullanici_adi,))
            st.dataframe(asistanlar, hide_index=True, use_container_width=True)
            if not asistanlar.empty:
                silinecek = st.selectbox("Sistemden Kaldırılacak Asistan", asistanlar['Kullanıcı Adı'].tolist())
                if st.button("🗑️ Seçili Asistanın Erişimini Kapat"):
                    c.execute("DELETE FROM klinik_asistanlari WHERE Asistan_Kadi=? AND Klinik_Unvani=?", (silinecek, kullanici_adi))
                    conn.commit(); st.success("Asistan silindi!"); st.rerun()

        with tab_bildirim:
            st.markdown("### 🔔 Akıllı Bildirim ve İletişim Tercihleri")
            st.info("Laboratuvarımızdan (OMG AI) gelecek otonom bildirimlerin hangi kanaldan iletileceğini seçin.")
            b_veri = c.execute("SELECT Bildirim_Kurye, Bildirim_Fatura, Bildirim_Asama FROM cariler WHERE Klinik_Unvani=?", (kullanici_adi,)).fetchone()
            bk = b_veri[0] if b_veri and b_veri[0] else 'WhatsApp'
            bf = b_veri[1] if b_veri and b_veri[1] else 'E-Posta'
            ba = b_veri[2] if b_veri and b_veri[2] else 'Sessiz (İstemiyorum)'
            
            with st.form("bildirim_tercih_formu"):
                c1, c2, c3 = st.columns(3)
                idx_k = ["WhatsApp", "E-Posta", "Sessiz (İstemiyorum)"].index(bk) if bk in ["WhatsApp", "E-Posta", "Sessiz (İstemiyorum)"] else 0
                idx_f = ["WhatsApp", "E-Posta", "Sessiz (İstemiyorum)"].index(bf) if bf in ["WhatsApp", "E-Posta", "Sessiz (İstemiyorum)"] else 1
                idx_a = ["WhatsApp", "E-Posta", "Sessiz (İstemiyorum)"].index(ba) if ba in ["WhatsApp", "E-Posta", "Sessiz (İstemiyorum)"] else 2
                
                yeni_bk = c1.selectbox("Kurye & Lojistik Durumları", ["WhatsApp", "E-Posta", "Sessiz (İstemiyorum)"], index=idx_k)
                yeni_bf = c2.selectbox("Finans & Fatura Hatırlatmaları", ["WhatsApp", "E-Posta", "Sessiz (İstemiyorum)"], index=idx_f)
                yeni_ba = c3.selectbox("Üretim Aşaması Değişimleri", ["WhatsApp", "E-Posta", "Sessiz (İstemiyorum)"], index=idx_a)
                
                if st.form_submit_button("Tercihleri Kaydet", type="primary"):
                    c.execute("UPDATE cariler SET Bildirim_Kurye=?, Bildirim_Fatura=?, Bildirim_Asama=? WHERE Klinik_Unvani=?", (yeni_bk, yeni_bf, yeni_ba, kullanici_adi))
                    conn.commit(); st.success("Bildirim tercihleriniz OMG AI sistemine başarıyla entegre edildi!"); st.rerun()

        with tab_otopilot:
            st.markdown("### ⚡ Otopilot Reçete")
            st.info("Sürekli aynı tür işler gönderiyorsanız, varsayılan tercihlerinizi belirleyin. Yeni Sipariş ekranı sizin için otomatik dolsun.")
            oto_veri = c.execute("SELECT Otopilot_Kategori, Otopilot_Islem, Otopilot_Renk FROM cariler WHERE Klinik_Unvani=?", (kullanici_adi,)).fetchone()
            
            with st.form("otopilot_formu"):
                kat_sec_oto = st.selectbox("Varsayılan Kategori", ["-"] + KATEGORILER, index=(["-"] + KATEGORILER).index(oto_veri[0]) if oto_veri and oto_veri[0] in (["-"] + KATEGORILER) else 0)
                islem_sec_oto = st.text_input("Varsayılan İşlem (Örn: Zirkonyum Kron)", value=oto_veri[1] if oto_veri and oto_veri[1] != '-' else "")
                renk_sec_oto = st.text_input("Varsayılan Renk", value=oto_veri[2] if oto_veri else "A2")
                
                if st.form_submit_button("Otopilotu Kaydet", type="primary"):
                    c.execute("UPDATE cariler SET Otopilot_Kategori=?, Otopilot_Islem=?, Otopilot_Renk=? WHERE Klinik_Unvani=?", (kat_sec_oto, islem_sec_oto, renk_sec_oto, kullanici_adi))
                    conn.commit(); st.success("Otopilot reçete ayarları kaydedildi!"); st.rerun()


# =====================================================================
# --- 👨‍🔬 LABORATUVAR ARAYÜZÜ ---
# =====================================================================

elif rol in ["Admin", "Yönetici", "Sekreter", "Teknisyen"]:

    if sayfa == "🏢 Kurumsal Bilgi":
        banner_olustur("🏢", "Laboratuvar Kurumsal Bilgi", "Laboratuvarımıza ait resmi kurumsal bilgiler, vergi, ödeme ve iletişim detayları.")
        
        lab_adi = ayar_getir("Lab_Ad", "OMG Smile Sistem")
        lab_unvan = ayar_getir("Lab_Unvan", "Belirtilmemiş")
        lab_kurulus = ayar_getir("Lab_Kurulus_Tarihi", "Bilinmiyor")
        lab_sorumlu = ayar_getir("Lab_Sorumlu_Kisi", "Belirtilmemiş")
        lab_vergi_no = ayar_getir("Lab_Vergi_No", "Belirtilmemiş")
        lab_vergi_dairesi = ayar_getir("Lab_Vergi_Dairesi", "Belirtilmemiş")
        lab_iban = ayar_getir("Lab_IBAN", "TR00 0000 0000 0000 0000 0000 00")
        lab_kep = ayar_getir("Lab_Kep", "Belirtilmemiş")
        lab_telefon = ayar_getir("Lab_Telefon", "Belirtilmemiş")
        lab_email = ayar_getir("Lab_Email", "Belirtilmemiş")
        lab_web = ayar_getir("Lab_Web", "Belirtilmemiş")
        lab_adres = ayar_getir("Lab_Adres", "Belirtilmemiş")
        
        st.markdown(f"""
        <div class='glass-card' style='padding: 30px; border-radius: 15px; text-align: center; margin-bottom: 20px;'>
            <h1 style='color: #4CAF50; font-size: 2.5em; margin-bottom: 10px;'>{lab_adi}</h1>
            <h4 style='color: #E5E9F0; font-weight: normal; margin-top: -5px; margin-bottom: 20px;'>{lab_unvan}</h4>
            <hr style='border-top: 2px solid rgba(255,255,255,0.1); margin: 20px 0;'>
            <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; text-align: left;'>
                <div style='background: rgba(255,255,255,0.05); padding: 20px; border-radius: 10px;'>
                    <h3 style='color: #88C0D0; margin-bottom: 15px;'><i class='fas fa-info-circle'></i> Genel Bilgiler</h3>
                    <p><b>🏢 Kuruluş Tarihi:</b> <span style='color:#E5E9F0;'>{lab_kurulus}</span></p>
                    <p><b>👨‍💼 Sorumlu Kişi:</b> <span style='color:#E5E9F0;'>{lab_sorumlu}</span></p>
                    <p><b>🌐 Web Sitesi:</b> <span style='color:#88C0D0;'>{lab_web}</span></p>
                </div>
                <div style='background: rgba(255,255,255,0.05); padding: 20px; border-radius: 10px;'>
                    <h3 style='color: #A3BE8C; margin-bottom: 15px;'><i class='fas fa-file-invoice-dollar'></i> Finans & Vergi</h3>
                    <p><b>💳 IBAN:</b> <span style='color:#EBCB8B; font-family: monospace; font-size: 1.1em;'>{lab_iban}</span></p>
                    <p><b>🏛️ Vergi Dairesi:</b> <span style='color:#E5E9F0;'>{lab_vergi_dairesi}</span></p>
                    <p><b>📑 Vergi No:</b> <span style='color:#E5E9F0;'>{lab_vergi_no}</span></p>
                </div>
                <div style='background: rgba(255,255,255,0.05); padding: 20px; border-radius: 10px;'>
                    <h3 style='color: #EBCB8B; margin-bottom: 15px;'><i class='fas fa-address-book'></i> İletişim Bilgileri</h3>
                    <p><b>📞 Telefon:</b> <span style='color:#E5E9F0;'>{lab_telefon}</span></p>
                    <p><b>✉️ E-Mail:</b> <span style='color:#E5E9F0;'>{lab_email}</span></p>
                    <p><b>🔏 KEP Adresi:</b> <span style='color:#E5E9F0;'>{lab_kep}</span></p>
                    <p><b>📍 Adres:</b> <span style='color:#E5E9F0;'>{lab_adres}</span></p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
    elif sayfa == "🏠 Komuta Merkezi":
        st.markdown("<h1 class='neon-text-blue' style='margin-top:-20px; margin-bottom:10px;'>KOMUTA MERKEZİ</h1>", unsafe_allow_html=True)
            
        df_cariler = pd.read_sql("SELECT * FROM cariler", conn)
        df_isler = pd.read_sql("SELECT * FROM isler", conn)
        
        yeni_siparis = len(df_isler[df_isler["Asama"]=="Sipariş Alındı (Hekim Girdi)"])
        kurye_bekleyen = c.execute("SELECT count(*) FROM kurye_islemleri WHERE Durum='Bekliyor'").fetchone()[0]
        kritik_stok = c.execute("SELECT count(*) FROM stok WHERE Mevcut_Miktar <= Kritik_Sinir AND Durum='Aktif'").fetchone()[0]
        geciken_is = c.execute("SELECT count(*) FROM isler WHERE Asama != 'Teslim Edildi' AND Teslim_Tarihi < ?", (datetime.now().strftime('%Y-%m-%d'),)).fetchone()[0]
        
        if kurye_bekleyen > 0 or yeni_siparis > 0 or kritik_stok > 0 or geciken_is > 0:
            alarms_html = ""
            if yeni_siparis > 0: alarms_html += f"<div class='alarm-badge'>🔔 {yeni_siparis} Yeni İş</div>"
            if kurye_bekleyen > 0: alarms_html += f"<div class='alarm-badge'>🛵 {kurye_bekleyen} Kurye</div>"
            if kritik_stok > 0: alarms_html += f"<div class='alarm-badge'>📦 {kritik_stok} Stok Uyarısı</div>"
            if geciken_is > 0: alarms_html += f"<div class='alarm-badge'>⌛ {geciken_is} Geciken İş</div>"
            
            st.markdown(f"""
            <div class="alarm-bar">
                <span class="alarm-title">⚠️ SİSTEM ALARMLARI:</span>
                {alarms_html}
            </div>
            """, unsafe_allow_html=True)
            
        if st.session_state.w_ciro:
            if not df_isler.empty and 'Bakiye_Durumu' in df_isler.columns:
                toplam_gelir = pd.to_numeric(df_isler[df_isler['Bakiye_Durumu'] == 'Aktarıldı']['Tutar_TL'], errors='coerce').sum()
            else:
                toplam_gelir = pd.to_numeric(df_isler['Tutar_TL'], errors='coerce').sum() if not df_isler.empty else 0
            bugun_gun = datetime.now().day
            if bugun_gun == 0: bugun_gun = 1
            ai_tahmin = (toplam_gelir / bugun_gun) * 30
            para_birimi = ayar_getir("Para_Birimi", "TL")
            
            # Gerçek zamanlı global bakiye hesaplaması
            _g_toplam_is = c.execute("SELECT SUM(Tutar_TL) FROM isler WHERE Bakiye_Durumu='Aktarıldı'").fetchone()[0] or 0.0
            _g_kdv = float(ayar_getir("KDV_Orani", "20"))
            _g_tahs_kdvli = c.execute("SELECT SUM(Tutar) FROM tahsilatlar").fetchone()[0] or 0.0
            _g_tahs_net = _g_tahs_kdvli / (1.0 + (_g_kdv / 100.0))
            global_piyasa_alacak = _g_toplam_is - _g_tahs_net

            f1, f2, f3, f4 = st.columns(4)
            f1.markdown(f"<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>Gerçekleşen Ciro</span><br><span class='neon-text-green' style='font-size:30px;'>{toplam_gelir:,.0f} {para_birimi}</span></div>", unsafe_allow_html=True)
            f2.markdown(f"<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>🤖 AI Ay Sonu Tahmini</span><br><span class='neon-text-blue' style='font-size:30px;'>{ai_tahmin:,.0f} {para_birimi}</span></div>", unsafe_allow_html=True)
            f3.markdown(f"<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>Piyasadaki Alacak</span><br><span class='neon-text-red' style='font-size:30px;'>{global_piyasa_alacak:,.0f} {para_birimi}</span></div>", unsafe_allow_html=True)
            f4.markdown(f"<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>Aktif Üretim</span><br><span style='color:#fff; font-size:30px; font-weight:900;'>{len(df_isler[df_isler['Asama'] != 'Teslim Edildi'])} Adet</span></div>", unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

        if st.session_state.w_radar:
            st.markdown("<h4 style='color:#FFFFFF;'>🟢 Canlı Üretim Bandı</h4>", unsafe_allow_html=True)
            c_sip = len(df_isler[df_isler["Asama"]=="Sipariş Alındı (Hekim Girdi)"])
            c_tas = len(df_isler[df_isler["Asama"]=="Tasarım Bekliyor"])
            c_kaz = len(df_isler[df_isler["Asama"]=="Kazıma/Döküm"])
            c_fir = len(df_isler[df_isler["Asama"]=="Seramik/Fırın"])
            c_tes = len(df_isler[df_isler["Asama"]=="Teslim Edildi"])
            
            st.markdown(f"""
                <div class="radar-container">
                    <div class="radar-line"></div>
                    <div class="radar-step {'step-active' if c_sip > 0 else ''}"><div class="radar-circle">{c_sip}</div><div class="radar-label">Sipariş Alındı</div></div>
                    <div class="radar-step {'step-active' if c_tas > 0 else ''}"><div class="radar-circle">{c_tas}</div><div class="radar-label">Tasarım Bekliyor</div></div>
                    <div class="radar-step {'step-active' if c_kaz > 0 else ''}"><div class="radar-circle">{c_kaz}</div><div class="radar-label">Kazıma/Döküm</div></div>
                    <div class="radar-step {'step-active' if c_fir > 0 else ''}"><div class="radar-circle">{c_fir}</div><div class="radar-label">Seramik/Fırın</div></div>
                    <div class="radar-step"><div class="radar-circle" style="border-color:#475569; color:#94a3b8;">{c_tes}</div><div class="radar-label">Teslim Edilen</div></div>
                </div>
            """, unsafe_allow_html=True)

        if st.session_state.w_grafikler:
            st.markdown("<br>", unsafe_allow_html=True)
            
            # ÜST SIRA: 3'LÜ KİBAR GRAFİK KOKPİTİ
            g1, g2, g3 = st.columns(3)
            
            with g1:
                with st.container(border=False):
                    st.markdown("<div class='glass-card' style='padding: 10px; margin-bottom: 5px;'><h5 style='text-align: center; color: #38bdf8; margin:0; font-size: 14px;'>📊 Klinik İş Dağılımı</h5></div>", unsafe_allow_html=True)
                    if not df_isler.empty:
                        klinik_dagilim = df_isler["Klinik_Unvani"].value_counts().reset_index()
                        klinik_dagilim.columns = ["Klinik", "İş Sayısı"]
                        fig_donut = px.pie(klinik_dagilim, names="Klinik", values="İş Sayısı", hole=0.65, color_discrete_sequence=px.colors.sequential.Tealgrn_r)
                        fig_donut.update_layout(height=240, template="plotly_dark", margin=dict(t=5, b=5, l=5, r=5), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                        fig_donut.update_traces(textposition='inside', textinfo='percent+label')
                        st.plotly_chart(fig_donut, use_container_width=True)
            
            with g2:
                with st.container(border=False):
                    st.markdown("<div class='glass-card' style='padding: 10px; margin-bottom: 5px;'><h5 style='text-align: center; color: #38bdf8; margin:0; font-size: 14px;'>🚀 Aktif Üretim Aşamaları</h5></div>", unsafe_allow_html=True)
                    if not df_isler.empty:
                        aktif_df = df_isler[df_isler["Asama"] != "Teslim Edildi"]
                        if not aktif_df.empty:
                            asama_dagilim = aktif_df["Asama"].value_counts().reset_index()
                            asama_dagilim.columns = ["Aşama", "İş Sayısı"]
                            fig_bar = px.bar(asama_dagilim, x="Aşama", y="İş Sayısı", text="İş Sayısı", color="Aşama", color_discrete_sequence=px.colors.qualitative.Vivid)
                            fig_bar.update_layout(height=240, template="plotly_dark", margin=dict(t=5, b=5, l=5, r=5), xaxis_title="", yaxis_title="", showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                            fig_bar.update_traces(textposition='outside', cliponaxis=False)
                            fig_bar.update_xaxes(showticklabels=False) # Alt yazıları gizledik ki hantal durmasın
                            st.plotly_chart(fig_bar, use_container_width=True)
                        else:
                            st.info("Üretim bandında aktif iş yok.")

            with g3:
                with st.container(border=False):
                    st.markdown("<div class='glass-card' style='padding: 10px; margin-bottom: 5px;'><h5 style='text-align: center; color: #38bdf8; margin:0; font-size: 14px;'>🔥 En Popüler 5 İşlem</h5></div>", unsafe_allow_html=True)
                    if not df_isler.empty:
                        islem_dagilim = df_isler["Is_Turu"].value_counts().head(5).reset_index()
                        islem_dagilim.columns = ["İşlem", "Sayı"]
                        fig_hbar = px.bar(islem_dagilim, y="İşlem", x="Sayı", orientation='h', text="Sayı", color_discrete_sequence=["#8B5CF6"])
                        fig_hbar.update_layout(height=240, template="plotly_dark", margin=dict(t=5, b=5, l=5, r=5), xaxis_title="", yaxis_title="", showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                        fig_hbar.update_yaxes(autorange="reversed", showgrid=False)
                        fig_hbar.update_xaxes(showgrid=False, showticklabels=False)
                        st.plotly_chart(fig_hbar, use_container_width=True)

            # ALT SIRA: GENİŞ CİRO EĞRİSİ
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("<div class='glass-card' style='padding: 12px; margin-bottom: 5px;'><h4 style='text-align: center; color: #34d399; margin:0;'>📈 Son 14 Günlük Ciro/Üretim Eğrisi</h4></div>", unsafe_allow_html=True)
            
            if not df_isler.empty:
                df_trend = df_isler.copy()
                df_trend['Tarih_Formatli'] = pd.to_datetime(df_trend['Tarih'], errors='coerce')
                df_trend = df_trend.dropna(subset=['Tarih_Formatli'])
                
                # Son 14 günü alıyoruz
                son_14_gun = datetime.now() - timedelta(days=14)
                df_trend = df_trend[df_trend['Tarih_Formatli'] >= son_14_gun]
                
                gunluk_ciro = df_trend[df_trend['Bakiye_Durumu'] == 'Aktarıldı'].groupby(df_trend['Tarih_Formatli'].dt.strftime('%Y-%m-%d'))['Tutar_TL'].sum().reset_index()
                
                if not gunluk_ciro.empty:
                    fig_line = px.area(gunluk_ciro, x="Tarih_Formatli", y="Tutar_TL", markers=True, color_discrete_sequence=["#10B981"])
                    fig_line.update_layout(height=260, template="plotly_dark", margin=dict(t=10, b=20, l=10, r=10), xaxis_title="", yaxis_title=f"Ciro ({ayar_getir('Para_Birimi', 'TL')})", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig_line, use_container_width=True)
                else:
                    st.info("Son 14 güne ait gelir verisi bulunmuyor.")

    elif sayfa == "📅 Görev & Planlama":
        st.markdown("## 📅 Görev & Planlama")
        st.markdown("Laboratuvar içi görevleri organize edebilir, personellere iş atayabilir ve takip edebilirsiniz.")
        
        tab_yeni, tab_pano = st.tabs(["➕ Yeni Görev Oluştur", "📋 Görev Panosu (Kanban)"])
        
        kullanicilar_list = [row[0] for row in c.execute("SELECT Kullanici_Adi FROM kullanicilar WHERE Rol != 'Klinik'").fetchall()]
        
        with tab_yeni:
            if rol in ["Admin", "Yönetici", "Sekreter"]:
                with st.container(border=True):
                    st.markdown("#### 🎯 Görev Detayları")
                    g_baslik = st.text_input("Görev Başlığı")
                    g_detay = st.text_area("Görev Açıklaması")
                    
                    c1, c2, c3 = st.columns(3)
                    g_atanan = c1.selectbox("Kime Atanacak?", ["-- Seçiniz --"] + kullanicilar_list)
                    g_tarih = c2.date_input("Son Teslim Tarihi")
                    g_oncelik = c3.selectbox("Öncelik Derecesi", ["Normal", "Düşük", "Acil"])
                    
                    if st.button("🚀 Görevi Ata ve Bildirim Gönder", type="primary", use_container_width=True):
                        if g_baslik and g_atanan != "-- Seçiniz --":
                            olusturma_tarihi = datetime.now().strftime("%Y-%m-%d %H:%M")
                            son_tarih_str = g_tarih.strftime("%Y-%m-%d")
                            
                            c.execute("INSERT INTO gorevler (olusturan, atanan_kullanici, gorev_basligi, gorev_detayi, son_tarih, oncelik, olusturma_tarihi) VALUES (?,?,?,?,?,?,?)",
                                      (kullanici_adi, g_atanan, g_baslik, g_detay, son_tarih_str, g_oncelik, olusturma_tarihi))
                            conn.commit()
                            
                            mesaj_metni = f"📅 YENİ GÖREV: {g_baslik} (Öncelik: {g_oncelik}) - Son Tarih: {son_tarih_str}. Detaylar: {g_detay}"
                            c.execute("INSERT INTO mesajlar (Tarih_Saat, Gonderen, Alici, Mesaj, Okundu) VALUES (?,?,?,?,0)",
                                      (olusturma_tarihi, kullanici_adi, g_atanan, mesaj_metni))
                            conn.commit()
                            
                            st.success(f"Görev başarıyla oluşturuldu ve {g_atanan} adlı kullanıcıya bildirim gönderildi!")
                        else:
                            st.error("Lütfen görev başlığı ve atanacak kişiyi seçtiğinizden emin olun.")
            else:
                st.info("Yeni görev oluşturma yetkiniz bulunmuyor. Görev panosunu kullanarak size atanan işleri takip edebilirsiniz.")

        with tab_pano:
            st.markdown("#### 📌 Güncel Görevler")
            f_kullanici = st.selectbox("Gösterilecek Kullanıcı", ["Tümü", "Sadece Bana Atananlar"], index=1)
            
            query = "SELECT id, olusturan, atanan_kullanici, gorev_basligi, gorev_detayi, son_tarih, durum, oncelik, olusturma_tarihi FROM gorevler"
            if f_kullanici == "Sadece Bana Atananlar":
                query += f" WHERE atanan_kullanici = '{kullanici_adi}'"
            query += " ORDER BY son_tarih ASC"
            
            try:
                df_gorev = pd.read_sql(query, conn)
                df_gorev.columns = df_gorev.columns.str.lower()
                
                if df_gorev.empty:
                    st.info("Şu an bekleyen veya devam eden bir görev bulunmuyor.")
                else:
                    col_b, col_y, col_t = st.columns(3)
                    
                    with col_b:
                        st.markdown("<h5 style='text-align: center; color: #facc15;'>⏳ Bekleyenler</h5>", unsafe_allow_html=True)
                        df_b = df_gorev[df_gorev['durum'] == 'Bekliyor']
                        for _, r in df_b.iterrows():
                            with st.container(border=True):
                                st.markdown(f"**{r['gorev_basligi']}**")
                                st.caption(f"👤 {r['atanan_kullanici']} | ⏰ {r['son_tarih']}")
                                if r['oncelik'] == 'Acil': st.markdown("🔴 **Acil**")
                                elif r['oncelik'] == 'Normal': st.markdown("🔵 **Normal**")
                                else: st.markdown("⚪ **Düşük**")
                                
                                with st.expander("Detay Gör"):
                                    st.write(r['gorev_detayi'])
                                    st.caption(f"Oluşturan: {r['olusturan']} ({r['olusturma_tarihi']})")
                                
                                if kullanici_adi == r['atanan_kullanici'] or rol in ["Admin", "Yönetici"]:
                                    if st.button("▶️ Başla", key=f"basla_{r['id']}", use_container_width=True):
                                        c.execute("UPDATE gorevler SET durum='Yapılıyor' WHERE id=?", (int(r['id']),))
                                        conn.commit(); st.rerun()

                    with col_y:
                        st.markdown("<h5 style='text-align: center; color: #38bdf8;'>🔄 Yapılıyor</h5>", unsafe_allow_html=True)
                        df_y = df_gorev[df_gorev['durum'] == 'Yapılıyor']
                        for _, r in df_y.iterrows():
                            with st.container(border=True):
                                st.markdown(f"**{r['gorev_basligi']}**")
                                st.caption(f"👤 {r['atanan_kullanici']} | ⏰ {r['son_tarih']}")
                                with st.expander("Detay Gör"):
                                    st.write(r['gorev_detayi'])
                                if kullanici_adi == r['atanan_kullanici'] or rol in ["Admin", "Yönetici"]:
                                    cy1, cy2 = st.columns(2)
                                    with cy1:
                                        if st.button("⏪ Geri", key=f"geri_{r['id']}", use_container_width=True):
                                            c.execute("UPDATE gorevler SET durum='Bekliyor' WHERE id=?", (int(r['id']),))
                                            conn.commit(); st.rerun()
                                    with cy2:
                                        if st.button("✅ Bitir", key=f"tamamla_{r['id']}", type="primary", use_container_width=True):
                                            c.execute("UPDATE gorevler SET durum='Tamamlandı' WHERE id=?", (int(r['id']),))
                                            conn.commit()
                                            mesaj_metni = f"✅ GÖREV TAMAMLANDI: {r['gorev_basligi']} adlı görevi {kullanici_adi} tamamladı."
                                            c.execute("INSERT INTO mesajlar (Tarih_Saat, Gonderen, Alici, Mesaj, Okundu) VALUES (?,?,?,?,0)",
                                                      (datetime.now().strftime("%Y-%m-%d %H:%M"), "Sistem", r['olusturan'], mesaj_metni))
                                            conn.commit()
                                            st.rerun()

                    with col_t:
                        st.markdown("<h5 style='text-align: center; color: #34d399;'>✅ Tamamlandı</h5>", unsafe_allow_html=True)
                        df_t = df_gorev[df_gorev['durum'] == 'Tamamlandı'].head(20)
                        for _, r in df_t.iterrows():
                            with st.container(border=True):
                                st.markdown(f"~~{r['gorev_basligi']}~~")
                                st.caption(f"👤 {r['atanan_kullanici']}")
                                if rol in ["Admin", "Yönetici"]:
                                    ct1, ct2 = st.columns(2)
                                    with ct1:
                                        if st.button("⏪ Geri", key=f"geri_t_{r['id']}", use_container_width=True):
                                            c.execute("UPDATE gorevler SET durum='Yapılıyor' WHERE id=?", (int(r['id']),))
                                            conn.commit(); st.rerun()
                                    with ct2:
                                        if st.button("🗑️ Sil", key=f"sil_{r['id']}", use_container_width=True):
                                            c.execute("DELETE FROM gorevler WHERE id=?", (int(r['id']),))
                                            conn.commit(); st.rerun()

            except Exception as e:
                st.error(f"Tablo yüklenirken hata oluştu: {e}")

    elif sayfa == "🤝 Hekim ve Cari Kayıt":
        banner_olustur("🤝", "Hekim ve Klinik Kayıt", "Yeni klinik tanımlayın veya mevcut kliniklerin bakiye ve VIP seviyelerini güncelleyin.")
        
        # 💎 KLASÖR (EXPANDER) İÇİN MAVİ ZIRH CSS YAMASI 💎
        st.markdown("""
<style>
            /* Klasör kapalıyken üzerine gelince (Hover) yazıyı mavi parlat */
            [data-testid="stExpander"] details summary:hover {
                color: #38bdf8 !important;
            }
            /* Klasör açıldığında başlığın arka planını Koyu Lacivert ve yazıyı Mavi yap */
            [data-testid="stExpander"] details[open] summary {
                background-color: #0f172a !important; 
                color: #38bdf8 !important; 
                border-radius: 8px !important;
                font-weight: 800 !important;
            }
            /* 🚨 KLASÖRÜN AÇILAN İÇERİĞİNİ AÇIK MAVİ YAP 🚨 */
            [data-testid="stExpander"] details[open] > div[role="region"] {
                background-color: #e0f2fe !important; 
                border-radius: 0 0 8px 8px !important;
                padding: 15px !important;
            }
            /* İçerideki TÜM yazıların okunması için renklerini Koyu Lacivert yap */
            [data-testid="stExpander"] details[open] > div[role="region"] * {
                color: #0f172a !important;
            }
</style>
        """, unsafe_allow_html=True)

        # 🚨 SİGORTA: Eski tabloya zarar vermeden "Durum" sütunu ekler (Arşivleme için) 🚨
        try: c.execute("ALTER TABLE cariler ADD COLUMN Durum TEXT DEFAULT 'Aktif'")
        except: pass
        conn.commit()

        tab_kayit, tab_liste, tab_crm = st.tabs(["➕ Yeni Klinik Ekle / Güncelle", "📋 Kayıtlı Klinikler", "🌟 CRM & VIP Yönetimi"])
        
        # ... Kodun geri kalanı aynen devam ediyor ...
        
        with tab_kayit:
            with st.form("yeni_klinik"):
                c1, c2 = st.columns(2)
                unvan = c1.text_input("Klinik Adı:")
                yetkili = c2.text_input("Yetkili Kişi")
                tel = c1.text_input("Telefon")
                mail = c2.text_input("Email")
                
                st.markdown("##### 📜 Resmi Fatura ve Lojistik Bilgileri")
                f_unvan = st.text_input("Klinik Ünvanı (Uzun isim)")
                adres = st.text_area("Açık Adres (Kurye ve Rota İçin Gereklidir)")
                
                v1, v2 = st.columns(2)
                v_daire = v1.text_input("Vergi Dairesi")
                v_no = v2.text_input("Vergi Numarası / T.C. Kimlik")
                iban = st.text_input("Banka Hesap Bilgisi (IBAN)")
                
                b1, b2 = st.columns(2)
                bakiye = b1.number_input("Mevcut Bakiye (TL)", value=0.0)
                indirim = b2.number_input("VIP İndirim Oranı (%)", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
                sifre = b1.text_input("Klinik Giriş Şifresi", value="1234")
                
                if st.form_submit_button("Kaydet"):
                    if unvan:
                        # 🚨 ÇİFT KAYIT ENGELLEYİCİ SİGORTA 🚨
                        kontrol = c.execute("SELECT id FROM cariler WHERE Klinik_Unvani=?", (unvan.strip(),)).fetchone()
                        if kontrol:
                            st.error(f"⚠️ '{unvan}' adında bir klinik zaten kayıtlı! Lütfen farklı bir isim girin veya mevcut kaydı güncelleyin.")
                        else:
                            c.execute("INSERT INTO cariler (Klinik_Unvani, Yetkili_Kisi, Telefon, Email, Bakiye, Risk_Limiti, Indirim_Orani, Sifre, Adres, Firma_Unvani, Vergi_Dairesi, Vergi_No, IBAN, VIP_Seviye, Durum) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", 
                                      (unvan.strip(), yetkili, tel, mail, bakiye, 50000.0, indirim, sifre, adres if adres else "-", f_unvan if f_unvan else "-", v_daire if v_daire else "-", v_no if v_no else "-", iban if iban else "-", "Standart", "Aktif"))
                            conn.commit(); st.success("Eklendi!"); st.rerun()
                    else:
                        st.warning("Klinik Adı boş bırakılamaz.")
            
            st.markdown("---")
            st.subheader("Klinik Bilgilerini Güncelle")
            
            # 🚨 Sadece "Aktif" klinikleri listele 🚨
            klinikler = [row[0] for row in c.execute("SELECT Klinik_Unvani FROM cariler WHERE Durum='Aktif'").fetchall()]
            if klinikler:
                g_klinik = st.selectbox("Güncellenecek Klinik", klinikler)
                k_veri = c.execute("SELECT Indirim_Orani, Sifre, Yetkili_Kisi, Telefon, Email, Adres, Firma_Unvani, Vergi_Dairesi, Vergi_No, IBAN, Bakiye FROM cariler WHERE Klinik_Unvani=?", (g_klinik,)).fetchone()
                with st.form("guncelle_klinik"):
                    c1, c2 = st.columns(2)
                    yeni_yetkili = c1.text_input("Yetkili", value=k_veri[2])
                    yeni_tel = c2.text_input("Telefon", value=k_veri[3])
                    yeni_email = c1.text_input("Email", value=k_veri[4])
                    yeni_adres = st.text_area("Açık Adres", value=k_veri[5])
                    yeni_funvan = st.text_input("Klinik Ünvanı (Uzun isim)", value=k_veri[6])
                    
                    v1, v2 = st.columns(2)
                    yeni_vdaire = v1.text_input("Vergi Dairesi", value=k_veri[7])
                    yeni_vno = v2.text_input("Vergi Numarası", value=k_veri[8])
                    yeni_iban = st.text_input("IBAN", value=k_veri[9])

                    b1, b2, b3 = st.columns(3)
                    yeni_bakiye = b1.number_input("Güncel Bakiye (TL)", value=float(k_veri[10]) if k_veri[10] else 0.0, step=100.0)
                    yeni_indirim = b2.number_input("Yeni İndirim Oranı (%)", min_value=0.0, max_value=100.0, value=float(k_veri[0]))
                    yeni_sifre = b3.text_input("Yeni Giriş Şifresi", value=k_veri[1])

                    if st.form_submit_button("Bilgileri Güncelle"):
                        c.execute("UPDATE cariler SET Indirim_Orani=?, Sifre=?, Yetkili_Kisi=?, Telefon=?, Email=?, Adres=?, Firma_Unvani=?, Vergi_Dairesi=?, Vergi_No=?, IBAN=?, Bakiye=? WHERE Klinik_Unvani=?", 
                                  (yeni_indirim, yeni_sifre, yeni_yetkili, yeni_tel, yeni_email, yeni_adres, yeni_funvan, yeni_vdaire, yeni_vno, yeni_iban, yeni_bakiye, g_klinik))
                        conn.commit(); st.success("Güncellendi!"); st.rerun()
        
        with tab_liste:
            # Sadece Aktifleri Listele
            df_c = pd.read_sql("SELECT Klinik_Unvani, Email, Yetkili_Kisi, Telefon, Bakiye, Indirim_Orani FROM cariler WHERE Durum='Aktif'", conn)
            st.dataframe(df_c.style.format({"Bakiye": "{:.2f}", "Indirim_Orani": "%{:.0f}"}), hide_index=True, use_container_width=True)
            
            # 🚨 YENİ ARŞİVLEME ÖZELLİĞİ (Pasife Alma) 🚨
            st.markdown("---")
            with st.expander("⚙️ Klinik Arşivle (Pasife Al)", expanded=False):
                st.warning("Çalışmayı bıraktığınız klinikleri buradan arşive kaldırabilirsiniz. Eski fatura kayıtları silinmez, sadece listelerde görünmezler.")
                p_klinik = st.selectbox("Arşive Kaldırılacak Klinik", klinikler, key="pasif_sec")
                if st.button("🗑️ Kliniği Arşive Kaldır", type="primary"):
                    c.execute("UPDATE cariler SET Durum='Pasif' WHERE Klinik_Unvani=?", (p_klinik,))
                    conn.commit(); st.success(f"{p_klinik} başarıyla arşive kaldırıldı."); st.rerun()

        with tab_crm:
            st.markdown("### 🌟 Klinik Sadakat (Loyalty) Analizi")
            st.info("Laboratuvara en çok kazandıran klinikleri tespit edin ve onları VIP statüsüne yükselterek ödüllendirin.")
            
            df_is_f = pd.read_sql("SELECT Klinik_Unvani, Tutar_TL FROM isler WHERE Bakiye_Durumu='Aktarıldı'", conn)
            if not df_is_f.empty:
                klinik_ciro = df_is_f.groupby("Klinik_Unvani")["Tutar_TL"].sum().reset_index()
                # CRM sadece Aktif klinikleri baz alsın
                klinikler_vip = pd.read_sql("SELECT Klinik_Unvani, VIP_Seviye FROM cariler WHERE Durum='Aktif'", conn)
                df_crm = pd.merge(klinik_ciro, klinikler_vip, on="Klinik_Unvani", how="inner").fillna(0)
                df_crm = df_crm.sort_values(by="Tutar_TL", ascending=False).reset_index(drop=True)
                
                para_birimi = ayar_getir("Para_Birimi", "TL")
                st.dataframe(df_crm.rename(columns={"Klinik_Unvani":"Klinik", "Tutar_TL":f"Toplam Ciro ({para_birimi})", "VIP_Seviye":"Güncel Seviye"}).style.format({f"Toplam Ciro ({para_birimi})": "{:,.2f}"}), hide_index=True, use_container_width=True)
                
                st.markdown("#### 👑 Seviye Güncelle")
                if not df_crm.empty:
                    col_c1, col_c2 = st.columns(2)
                    secilen_crm = col_c1.selectbox("Klinik Seçin", df_crm['Klinik_Unvani'].tolist())
                    yeni_vip = col_c2.selectbox("Yeni Seviye", ["Standart", "Gold", "Platinum"])
                    
                    if st.button("Seviyeyi Uygula", type="primary"):
                        c.execute("UPDATE cariler SET VIP_Seviye=? WHERE Klinik_Unvani=?", (yeni_vip, secilen_crm))
                        conn.commit(); st.success(f"{secilen_crm} kliniğinin seviyesi '{yeni_vip}' olarak güncellendi!"); st.rerun()
            else:
                st.warning("Henüz sistemde analiz edilecek bir üretim/ciro verisi bulunmuyor.")
 

    elif sayfa == "📱 WhatsApp Entegrasyonu":
        banner_olustur("💬", "WhatsApp İletişim Merkezi", "Hekimlere tek tıkla otomatik bildirimler gönderin ve Hekim Botunu test edin.")
        
        tab_bildirim, tab_bot = st.tabs(["🚀 Tek Tıkla Bildirimler", "🤖 Hekim Botu Simülatörü"])
        
        with tab_bildirim:
            st.markdown("### 📲 Kliniğe Hızlı Mesaj Gönder")
            klinikler_wp = pd.read_sql("SELECT Klinik_Unvani, Yetkili_Kisi, Telefon, Bakiye FROM cariler", conn)
            
            if not klinikler_wp.empty:
                secilen_klinik_wp = st.selectbox("İletişim Kurulacak Klinik / Hekim Seçin", klinikler_wp["Klinik_Unvani"] + " | " + klinikler_wp["Yetkili_Kisi"])
                k_ad = secilen_klinik_wp.split("|")[0].strip()
                k_bilgi = klinikler_wp[klinikler_wp["Klinik_Unvani"] == k_ad].iloc[0]
                
                sablon_secim = st.radio("Gönderilecek Mesaj Şablonu", ["💰 Bakiye ve Ekstre Hatırlatması", "🛵 Kurye Yönlendirme Bilgisi", "✍️ Serbest Mesaj"])
                
                if sablon_secim == "💰 Bakiye ve Ekstre Hatırlatması":
                    pb = ayar_getir("Para_Birimi", "TL")
                    mesaj_metni = f"Sayın {k_bilgi['Yetkili_Kisi']},\nOMG Smile Laboratuvarı olarak iyi çalışmalar dileriz. Anlık güncel bakiye borcunuz *{k_bilgi['Bakiye']:,.2f} {pb}* olarak görünmektedir. Ödemenizi sistem üzerinden veya banka hesaplarımıza yapabilirsiniz.\nSağlıklı günler dileriz."
                elif sablon_secim == "🛵 Kurye Yönlendirme Bilgisi":
                    sablon_kurye = ayar_getir("Kurye_Sablonu", "Sayın [Hekim_Adı],\nKurye talebiniz alınmıştır. Kuryemiz en kısa sürede adresinize yönlendirilecektir.\nTeşekkür ederiz.")
                    mesaj_metni = sablon_kurye.replace("[Hekim_Adı]", k_bilgi['Yetkili_Kisi'])
                else:
                    mesaj_metni = st.text_area("Mesajınızı Yazın", "Merhaba, ...")

                st.markdown("---")
                st.markdown("##### 📱 Önizleme")
                st.info(mesaj_metni)
                
                if k_bilgi["Telefon"] and k_bilgi["Telefon"] != "-":
                    wp_link = wp_link_olustur(k_bilgi["Telefon"], mesaj_metni)
                    st.markdown(f"""<a href="{wp_link}" target="_blank" class="wp-btn">✅ WhatsApp Web / Uygulaması İle Gönder</a>""", unsafe_allow_html=True)
                else:
                    st.error("⚠️ Bu kliniğin sistemde kayıtlı geçerli bir telefon numarası bulunmuyor. Lütfen Cari kartından güncelleyin.")
            else:
                st.warning("Sistemde kayıtlı klinik bulunmuyor.")

        with tab_bot:
            st.markdown("### 🤖 OMG AI WhatsApp Hekim Botu (Test Terminali)")
            st.info("İleride laboratuvarınızın WhatsApp hattına bağlayacağımız Yapay Zeka botunun, hekimlerden gelen mesajlara nasıl cevap vereceğini buradan test edebilirsiniz.")
            
            hekim_mesaji = st.text_input("Hekim WhatsApp'tan ne yazdı? (Örn: 'Ahmet Yılmaz vakası ne durumda?', 'Borcum ne kadar?')")
            
            if st.button("🤖 Botun Cevabını Gör", type="primary"):
                msg_lower = hekim_mesaji.lower()
                if "borc" in msg_lower or "bakiye" in msg_lower or "hesap" in msg_lower:
                    st.success("**OMG AI Yanıtlıyor:** Merhaba Hocam! OMG Smile sisteminden kontrol ediyorum... Mevcut güncel bakiyeniz 0.00 TL'dir. Ekstrenizin PDF halini isterseniz gönderebilirim.")
                elif "hasta" in msg_lower or "vaka" in msg_lower or "durum" in msg_lower or "ne durumda" in msg_lower:
                    st.success("**OMG AI Yanıtlıyor:** Merhaba Hocam! İlgili hastanın ismini sistemde aratıyorum... Vakanız şu an 'Seramik/Fırın' aşamasındadır. Planlanan teslim tarihi yarındır.")
                elif "kurye" in msg_lower or "alınacak" in msg_lower or "iş var" in msg_lower:
                    st.success("**OMG AI Yanıtlıyor:** Talebinizi aldım Hocam. Omg Smile lojistik radarına kurye talebinizi 'Bekliyor' olarak işledim. En kısa sürede kliniğinize gelinecektir.")
                else:
                    st.warning("**OMG AI Yanıtlıyor:** Merhaba Hocam! Ben OMG Smile Laboratuvarının dijital asistanıyım. Siparişleriniz, bakiyeniz veya kurye talepleriniz için bana yazabilirsiniz. Size nasıl yardımcı olabilirim?")

    elif sayfa == "⚙️ İş Akışı":
        banner_olustur("⚙️", "Laboratuvar İş Akışı", "Üretim bandını kontrol edin, aşamaları güncelleyin ve fatura kesin.")

        try:
            klinikler = [row[0] for row in c.execute("SELECT Klinik_Unvani FROM cariler WHERE Durum='Aktif' ORDER BY Klinik_Unvani ASC").fetchall()]
        except:
            klinikler = []
            
        aktif_personeller = [row[0] for row in c.execute("SELECT Ad_Soyad FROM personeller WHERE Durum='Aktif'").fetchall()]
        if not aktif_personeller: aktif_personeller = ["Atanmadı"]

        # 💎 GÖRSEL YAMA
        st.markdown("""
<style>
            [data-testid="stDownloadButton"] button { background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%) !important; border: none !important; box-shadow: 0 4px 15px rgba(14, 165, 233, 0.4) !important; border-radius: 10px !important; }
            [data-testid="stDownloadButton"] button p { color: #FFFFFF !important; font-weight: 800 !important; }
            [data-testid="stFileUploader"] button { background: linear-gradient(135deg, #8B5CF6 0%, #6D28D9 100%) !important; color: white !important; border: none !important; border-radius: 8px !important; box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4) !important; font-weight: 800 !important; }
            [data-testid="stFileUploaderDropzone"] { background-color: rgba(30, 41, 59, 0.6) !important; border: 2px dashed rgba(56, 189, 248, 0.5) !important; border-radius: 15px !important; transition: border 0.3s ease; }
            [data-testid="stFileUploaderDropzone"]:hover { border-color: #8B5CF6 !important; background-color: rgba(30, 41, 59, 0.8) !important; }
            .barcode-result-card { background: rgba(15, 23, 42, 0.8); border-left: 5px solid #38bdf8; padding: 20px; border-radius: 12px; box-shadow: 0 0 20px rgba(56, 189, 248, 0.2); margin-bottom: 20px; }
</style>
        """, unsafe_allow_html=True)

        tab_manuel_is, tab_takip, tab_cam, tab_arsiv = st.tabs(["➕ Yeni Manuel İş Kaydı (Laboratuvar)", "🚀 Üretim Takibi & Güncelleme", "💿 CAM Envanteri (Blok & Frez)", "🗄️ İş Arşivi"])
        
        with tab_arsiv:
            st.markdown("### 🗄️ İş Arşivi")
            st.info("Geçmişten bugüne oluşturulan tüm işleri (aktif veya teslim edilmiş) bu alandan filtreleyip inceleyebilirsiniz.")
            
            ar1, ar2 = st.columns(2)
            arsiv_tarih = ar1.date_input("Tarih Aralığı", value=(datetime.now() - timedelta(days=30), datetime.now()), key="arsiv_tarih")
            arsiv_klinik = ar2.selectbox("Klinik Filtresi", ["Tümü"] + klinikler, key="arsiv_klinik_sec")
            
            if isinstance(arsiv_tarih, tuple) and len(arsiv_tarih) == 2:
                bas_tar = arsiv_tarih[0].strftime("%Y-%m-%d")
                bit_tar = (arsiv_tarih[1] + timedelta(days=1)).strftime("%Y-%m-%d")
                
                fat_sorgu = "(SELECT COUNT(*) FROM hesap_ekstreleri e INNER JOIN faturalar f ON f.Ekstre_ID = e.id WHERE e.Klinik_Unvani = isler.Klinik_Unvani AND isler.Tarih >= e.Baslangic_Tarihi AND isler.Tarih <= e.Bitis_Tarihi) as Faturali_Mi"
                if arsiv_klinik == "Tümü":
                    df_arsiv_isler = pd.read_sql(f"SELECT id, Teslim_Tarihi, Hasta_Kodu, Hasta_Adi, Klinik_Unvani, {fat_sorgu} FROM isler WHERE Tarih >= ? AND Tarih < ? ORDER BY Tarih DESC", conn, params=(bas_tar, bit_tar))
                else:
                    df_arsiv_isler = pd.read_sql(f"SELECT id, Teslim_Tarihi, Hasta_Kodu, Hasta_Adi, Klinik_Unvani, {fat_sorgu} FROM isler WHERE Klinik_Unvani=? AND Tarih >= ? AND Tarih < ? ORDER BY Tarih DESC", conn, params=(arsiv_klinik, bas_tar, bit_tar))
                
                if not df_arsiv_isler.empty:
                    df_arsiv_isler['Faturali_Mi'] = df_arsiv_isler.get('Faturali_Mi', df_arsiv_isler.get('faturali_mi', 0)).fillna(0).astype(int)
                    df_grouped = df_arsiv_isler.groupby(['Hasta_Adi', 'Klinik_Unvani'], as_index=False).agg(
                        id=('id', 'first'),
                        Teslim_Tarihi=('Teslim_Tarihi', 'max'),
                        Hasta_Kodu=('Hasta_Kodu', 'first'),
                        Faturali_Mi=('Faturali_Mi', 'sum'),
                        Toplam_Is=('id', 'count')
                    ).sort_values(by='id', ascending=False).reset_index(drop=True)
                    
                    df_grouped.insert(0, 'S.NO', range(1, len(df_grouped) + 1))
                    df_grouped['DURUM'] = ['🔴' if f > 0 else '🟢' for f in df_grouped['Faturali_Mi']]
                    df_goster_ar = df_grouped[['S.NO', 'DURUM', 'Teslim_Tarihi', 'Hasta_Kodu', 'Hasta_Adi', 'Klinik_Unvani', 'Toplam_Is']].rename(columns={
                        "Teslim_Tarihi": "SON İŞLEM",
                        "Hasta_Kodu": "HASTA KODU",
                        "Hasta_Adi": "HASTA ADI",
                        "Klinik_Unvani": "KLİNİK",
                        "Toplam_Is": "İŞ SAYISI"
                    })
                    
                    st.caption("💡 İpucu: Hastanın geçmişini, fatura durumunu ve kullanılan malzemeleri görmek için tablodan satırına tıklayın.")
                    event_ar = st.dataframe(df_goster_ar,  hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row", key="arsiv_tablosu")
                    
                    if event_ar and len(event_ar.selection.rows) > 0:
                        sec_idx_ar = event_ar.selection.rows[0]
                        s_hasta_ar = df_grouped.iloc[sec_idx_ar]["Hasta_Adi"]
                        s_klinik_ar = df_grouped.iloc[sec_idx_ar]["Klinik_Unvani"]
                        
                        if st.session_state.get("son_acilan_hasta_arsiv") != f"{s_hasta_ar}_{s_klinik_ar}":
                            st.session_state.son_acilan_hasta_arsiv = f"{s_hasta_ar}_{s_klinik_ar}"
                            hasta_karti_goster(s_hasta_ar, s_klinik_ar)
                    else:
                        st.session_state.son_acilan_hasta_arsiv = None
                else:
                    st.warning("Belirtilen kriterlerde iş bulunamadı.")
            else:
                st.info("Lütfen bir tarih aralığı seçin.")
        
        with tab_manuel_is:
            st.markdown("### 📝 Laboratuvar İçi Reçete Kaydı")
            st.info("Hekim portalı kullanmayan klinikler için manuel iş girişi bu alandan yapılır.")
            
            # 🚨 FORM YAPISI KALDIRILDI, ALANLAR SIKIŞTIRILDI 🚨
            col_kat, col_kat_bos = st.columns([1.5, 3])
            kat_sec_lab = col_kat.selectbox("İşlem Kategorisi", KATEGORILER, key="lab_kat_sec")
            st.markdown("---")
            
            # 1. SATIR: Çok Daraltılmış ve Kısaltılmış Girdiler
            import random
            c1, c2, c_kodu, c3, c4 = st.columns([2.5, 1.5, 1.5, 1, 1.2])
            k_secim = c1.selectbox("Klinik / Hekim", klinikler) if klinikler else c1.text_input("Klinik Adı (Kayıtlı Değil)")
            ha = c2.text_input("Hasta/Dosya No")
            
            h_kodu = ""
            if ha:
                mevcut_kodlar = [m[0] for m in c.execute("SELECT DISTINCT Hasta_Kodu FROM isler WHERE Hasta_Adi=? AND Hasta_Kodu != '-'", (ha,)).fetchall()]
                if mevcut_kodlar:
                    h_kodu_secim = c_kodu.selectbox("Hasta Kodu (Kayıtlı)", mevcut_kodlar + ["Yeni Kod Oluştur"])
                    if h_kodu_secim == "Yeni Kod Oluştur":
                        h_kodu = f"OMG-HST-{random.randint(100000, 999999)}"
                        st.info(f"Yeni kod oluşturulacak: {h_kodu}")
                    else:
                        h_kodu = h_kodu_secim
                else:
                    h_kodu = f"OMG-HST-{random.randint(100000, 999999)}"
                    c_kodu.text_input("Hasta Kodu", value=h_kodu, disabled=True)
            else:
                c_kodu.text_input("Hasta Kodu", disabled=True)
            renk = c3.text_input("Renk")
            teslim_tarihi = c4.date_input("Teslim").strftime("%Y-%m-%d")
            
            # 2. SATIR: İşlem Seçimi ve Açıklama (TextArea yerine dar Text Input)
            c5, c_adet, c_rpt, c6 = st.columns([2.5, 0.8, 1.2, 2.5])
            hizmetler_lab = c.execute("SELECT Hizmet_Adi, Fiyat, Para_Birimi FROM fiyat_listesi WHERE Kategori=?", (kat_sec_lab,)).fetchall()
            if hizmetler_lab:
                h_dict_lab = {f"{h[0]}": h for h in hizmetler_lab}
                secilen_lab = c5.selectbox("Yapılacak İşlem", list(h_dict_lab.keys()))
            else:
                secilen_lab = "-"
                c5.warning("⚠️ Fiyat listesi yok.")
            
            is_adet_input = c_adet.number_input("Adet", min_value=1, value=1)
            c_rpt.markdown("<br>", unsafe_allow_html=True)
            is_rpt = c_rpt.checkbox("🔄 RPT", help="Yeniden yapım (Bedelsiz)", value=False)
            aciklama = c6.text_input("Açıklama / Özel İstekler")
            
            # 🚨 MANUEL KAYIT İÇİNE ENTEGRE EDİLMİŞ CAM MODÜLÜ 🚨
            st.markdown("#### ⚙️ CAM İstasyonu Üretimi (Opsiyonel)")
            cam_yok = st.checkbox("🚫 Bu işlemde CAM Sarfiyatı YOKTUR", value=False)
            if cam_yok:
                cam_kullan = False
            else:
                cam_kullan = st.checkbox("Bu işi şu an makineye gönderiyorum (Blok ve Frez sarfiyatını şimdi düş)", value=False)
            
            b_kodu = None; harcanan_uye_m = 0; secili_makine_m = None; frez_basina_dk_m = 0; sec_frezler_m = []; harcanan_dk_m = 0
            
            if cam_kullan:
                with st.container(border=True):
                    col_mak_m, col_uye_m, col_mbos_m = st.columns([2, 0.8, 3])
                    secili_makine_m = col_mak_m.selectbox("Kazıma Yapılan Makine", kazima_makinelerini_getir(), key="m_mak")
                    harcanan_uye_m = col_uye_m.number_input("Kazınan Üye", min_value=1, value=int(is_adet_input), key="m_uye")
                    
                    cam_b_m = c.execute("SELECT Blok_Kodu, Urun_Adi, Boyut_Renk, Kalan_Uye FROM cam_bloklar WHERE Durum='Yarım'").fetchall()
                    cam_f_m = c.execute("SELECT frez_kod, frez_adi, yuva_no, toplam_omur_dk, kullanilan_dk FROM aktif_frezler WHERE makine_adi=? AND durum='Aktif'", (secili_makine_m,)).fetchall()
                    
                    if cam_b_m and cam_f_m:
                        c_bm, c_fm = st.columns(2)
                        sec_blok_m = c_bm.selectbox("İşlenen Zirkonyum Blok", [f"{b[0]} | {b[1]} {b[2]} (Kalan: {b[3]} Üye)" for b in cam_b_m], key="m_blok")
                        sec_frezler_m = c_fm.multiselect("Kullanılan Frezler", [f"{f[0]} | {f[2]} - {f[1]} (Kalan: {f[3]-f[4]} Dk)" for f in cam_f_m], key="m_frez")
                        
                        tm1_m, tm2_m, tm_bos_m = st.columns([1.2, 1.2, 4])
                        baslama_saati_str = tm1_m.text_input("Başlama (SS:DD)", value="09:00", key="m_bas")
                        bitis_saati_str = tm2_m.text_input("Bitiş (SS:DD)", value="09:45", key="m_bit")
                        try:
                            baslama_saati_m = datetime.strptime(baslama_saati_str.strip(), "%H:%M").time()
                            bitis_saati_m = datetime.strptime(bitis_saati_str.strip(), "%H:%M").time()
                        except:
                            baslama_saati_m = datetime.strptime("09:00", "%H:%M").time()
                            bitis_saati_m = datetime.strptime("09:45", "%H:%M").time()
                            st.error("Lütfen saati SS:DD formatında giriniz (Örn: 14:30)")
                        tm1_m.caption("💡 Klavyeden yazabilirsiniz.")
                        
                        start_dt_m = datetime.combine(datetime.today(), baslama_saati_m); end_dt_m = datetime.combine(datetime.today(), bitis_saati_m)
                        if end_dt_m < start_dt_m: end_dt_m += timedelta(days=1) 
                        harcanan_dk_m = int((end_dt_m - start_dt_m).total_seconds() / 60)
                        frez_sayisi_m = len(sec_frezler_m) if len(sec_frezler_m) > 0 else 1
                        frez_basina_dk_m = int(harcanan_dk_m / frez_sayisi_m)
                        b_kodu = sec_blok_m.split("|")[0].strip()
                    else:
                        st.warning("Bu makinede aktif frez veya sistemde yarım blok bulunamadı.")
            
            st.markdown("---")
            if st.button("🚀 İşi Kaydet ve Üretime Al", type="primary", use_container_width=True):
                if not ha or not klinikler or not hizmetler_lab:
                    st.error("Klinik, Hasta Adı ve Hizmet seçimi zorunludur.")
                elif cam_kullan and (not sec_frezler_m or harcanan_dk_m <= 0):
                    st.error("CAM Üretimi seçildi ancak frez seçilmedi veya süre hatalı (Bitiş saati başlangıçtan sonra olmalı).")
                else:
                    islem_adi = h_dict_lab[secilen_lab][0] if hizmetler_lab else "-"
                    if is_rpt:
                        islem_adi = f"{islem_adi} (RPT)"
                    tarih_saat = datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    # Eğer CAM seçildiyse sarfiyatları arkadan sessizce düşüyoruz
                    harcanan_m_metni = "-"
                    if cam_kullan and b_kodu:
                        mevcut_uye_m = c.execute("SELECT Kalan_Uye FROM cam_bloklar WHERE Blok_Kodu=?", (b_kodu,)).fetchone()[0]
                        yeni_uye_m = mevcut_uye_m - harcanan_uye_m
                        c.execute("UPDATE cam_bloklar SET Kalan_Uye=?, Durum=? WHERE Blok_Kodu=?", (yeni_uye_m, "Bitti" if yeni_uye_m <= 0 else "Yarım", b_kodu))
                        
                        for fr in sec_frezler_m:
                            f_kodu_m = fr.split("|")[0].strip()
                            mevcut = c.execute("SELECT kullanilan_dk FROM aktif_frezler WHERE frez_kod=?", (f_kodu_m,)).fetchone()
                            c.execute("UPDATE aktif_frezler SET kullanilan_dk=? WHERE frez_kod=?", (mevcut[0] + frez_basina_dk_m, f_kodu_m))
                        
                        frezler_str = ", ".join([fr.split("|")[0].strip() for fr in sec_frezler_m])
                        harcanan_m_metni = f"CAM: {b_kodu} ({harcanan_uye_m} Üye), Makine: {secili_makine_m}, Takımlar: {frezler_str}, Top. {harcanan_dk_m} Dk"

                    # Her şeyi ana tabloya kaydet
                    if cam_yok:
                        harcanan_m_metni = "CAM YOK"
                    
                    is_adet_son = harcanan_uye_m if (cam_kullan and harcanan_uye_m > 0) else int(is_adet_input)
                    c.execute("INSERT INTO isler (Tarih, Klinik_Unvani, Hasta_Adi, Is_Turu, Renk, Asama, Tutar_TL, Sorumlu_Personel, Harcanan_Malzeme, Teslim_Tarihi, Barkod, Lot_Numarasi, Sertifika_No, Aciklama, Hasta_Kodu, Adet) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (tarih_saat, k_secim, ha, islem_adi, renk, "Sipariş Alındı (Hekim Girdi)", 0.0, "-", harcanan_m_metni, teslim_tarihi, "-", "-", "-", aciklama if aciklama else "-", h_kodu, is_adet_son))
                    yeni_id = c.lastrowid
                    onek = ayar_getir("Barkod_Onek", "OMG")
                    yeni_barkod = f"{onek}-{yeni_id:06d}"
                    c.execute("UPDATE isler SET Barkod=? WHERE id=?", (yeni_barkod, yeni_id))
                    
                    # --- ÜRETİM LOGLARINI EKLE (Malzeme Arşivi İçin) ---
                    if cam_kullan and b_kodu:
                        is_adi_tam = f"{k_secim} - {ha}"
                        b_adi = sec_blok_m.split("|")[1].split("(")[0].strip()
                        try:
                            c.execute("INSERT INTO uretim_loglari (is_id, is_adi, malzeme_turu, malzeme_kodu, malzeme_adi, uye_sayisi, tarih, dakika) VALUES (?,?,?,?,?,?,?,?)",
                                      (yeni_id, is_adi_tam, "Blok", b_kodu, b_adi, harcanan_uye_m, tarih_saat, harcanan_dk_m))
                        except:
                            c.execute("INSERT INTO uretim_loglari (is_id, is_adi, malzeme_turu, malzeme_kodu, malzeme_adi, uye_sayisi, tarih) VALUES (?,?,?,?,?,?,?)",
                                      (yeni_id, is_adi_tam, "Blok", b_kodu, b_adi, harcanan_uye_m, tarih_saat))
                        
                        for fr in sec_frezler_m:
                            f_kodu_m = fr.split("|")[0].strip()
                            f_adi = fr.split("|")[1].split("(")[0].strip().replace("-", "").strip()
                            try:
                                c.execute("INSERT INTO uretim_loglari (is_id, is_adi, malzeme_turu, malzeme_kodu, malzeme_adi, uye_sayisi, tarih, dakika) VALUES (?,?,?,?,?,?,?,?)",
                                          (yeni_id, is_adi_tam, "Frez", f_kodu_m, f_adi, harcanan_uye_m, tarih_saat, frez_basina_dk_m))
                            except:
                                c.execute("INSERT INTO uretim_loglari (is_id, is_adi, malzeme_turu, malzeme_kodu, malzeme_adi, uye_sayisi, tarih) VALUES (?,?,?,?,?,?,?)",
                                          (yeni_id, is_adi_tam, "Frez", f_kodu_m, f_adi, harcanan_uye_m, tarih_saat))
                    # ----------------------------------------------------
                    conn.commit()
                    st.success(f"✅ Manuel iş oluşturuldu, malzemeler stoktan düşüldü ve arşive loglandı! Barkod: {yeni_barkod}")

        with tab_takip:
            with st.container(border=True):
                # 🚨 BARKOD TERMİNALİ DARALTILDI 🚨
                c_bar1, c_bar_bos = st.columns([1.5, 3])
                okutulan_barkod = c_bar1.text_input("📷 Barkod Okuyucu Terminali:", placeholder="Örn: OMG-1001", key="barkod_terminal")
                
                if okutulan_barkod:
                    is_bulundu = c.execute("SELECT id, Klinik_Unvani, Hasta_Adi, Is_Turu, Asama, Sorumlu_Personel FROM isler WHERE Barkod=?", (okutulan_barkod.strip(),)).fetchone()
                    if is_bulundu:
                        b_rowid, b_klinik, b_hasta, b_tur, b_asama, b_sorumlu = is_bulundu
                        
                        st.markdown(f"""
                        <div class='barcode-result-card'>
                            <h3 style='margin-top:0; color:#38bdf8;'>Klinik: {b_klinik}</h3>
                            <p style='font-size:18px;'>Hasta: <b>{b_hasta}</b> | İşlem: {b_tur}</p>
                            <p style='color:#9CA3AF;'>Mevcut Aşama: <span style='color:#34d399; font-weight:bold;'>{b_asama}</span></p>
                        </div>
                        """, unsafe_allow_html=True)

                        asama_sirasi = ["Sipariş Alındı (Hekim Girdi)", "Tasarım Bekliyor", "Kazıma/Döküm", "Tesviye", "Seramik/Fırın", "Teslim Edildi"]
                        mevcut_idx = asama_sirasi.index(b_asama) if b_asama in asama_sirasi else 0
                        sonraki_asama = asama_sirasi[mevcut_idx + 1] if mevcut_idx < len(asama_sirasi) - 1 else "Teslim Edildi"
                        c1_b, c2_b = st.columns(2)
                        h_asama = c1_b.selectbox("Aşamayı Güncelle", asama_sirasi, index=asama_sirasi.index(sonraki_asama))
                        h_sorumlu = c2_b.selectbox("Sorumlu", aktif_personeller, index=0)
                        if st.button("🚀 Aşamayı Kaydet", use_container_width=True):
                            c.execute("UPDATE isler SET Asama=?, Sorumlu_Personel=? WHERE id=?", (h_asama, h_sorumlu, b_rowid))
                            conn.commit(); st.rerun()

            df_isler = pd.read_sql('''
                SELECT id, Barkod, Tarih, Teslim_Tarihi, Klinik_Unvani, Hasta_Adi, Hasta_Kodu, Is_Turu, Renk, Adet as "Adet", Asama, Tutar_TL, Sorumlu_Personel, Harcanan_Malzeme, Aciklama, Lot_Numarasi, Sertifika_No 
                FROM isler i 
                WHERE NOT EXISTS (
                    SELECT 1 FROM hesap_ekstreleri h
                    JOIN faturalar f ON h.id = f.Ekstre_ID
                    WHERE i.Klinik_Unvani = h.Klinik_Unvani
                      AND i.Tarih >= h.Baslangic_Tarihi
                      AND i.Tarih <= h.Bitis_Tarihi || ' 23:59:59'
                )
            ''', conn)
            if 'adet' in df_isler.columns: df_isler = df_isler.rename(columns={'adet': 'Adet'})
            
            # İşleri tarihe göre sırala (En yeniler üstte)
            df_isler = df_isler.sort_values(by=["Tarih", "id"], ascending=[False, False]).reset_index(drop=True)
            # Sıra No Sütunu Ekle
            st.subheader("📋 Reçeteler ve Üretim Takibi")
            

            if not df_isler.empty:
                for c_name in ["barkod", "tarih", "teslim_tarihi", "klinik_unvani", "hasta_adi", "hasta_kodu", "is_turu", "renk", "adet", "asama", "sorumlu_personel"]:
                    if c_name in df_isler.columns:
                        correct = "".join(w.capitalize() for w in c_name.split('_')) if '_' in c_name else c_name.capitalize()
                        if c_name == "teslim_tarihi": correct = "Teslim_Tarihi"
                        if c_name == "klinik_unvani": correct = "Klinik_Unvani"
                        if c_name == "hasta_adi": correct = "Hasta_Adi"
                        if c_name == "hasta_kodu": correct = "Hasta_Kodu"
                        if c_name == "is_turu": correct = "Is_Turu"
                        if c_name == "sorumlu_personel": correct = "Sorumlu_Personel"
                        df_isler = df_isler.rename(columns={c_name: correct})
                
                df_isler.insert(0, 'S.NO', range(1, len(df_isler) + 1))
                df_goster = df_isler[["S.NO", "Barkod", "Tarih", "Teslim_Tarihi", "Klinik_Unvani", "Hasta_Adi", "Hasta_Kodu", "Is_Turu", "Renk", "Adet", "Asama", "Sorumlu_Personel"]].copy()
                df_goster = df_goster.rename(columns={
                    "Barkod": "BARKOD NO",
                    "Tarih": "İŞ TARİHİ",
                    "Teslim_Tarihi": "TESLİM TARİHİ",
                    "Klinik_Unvani": "KLİNİK",
                    "Hasta_Adi": "HASTA ADI",
                    "Hasta_Kodu": "HASTA KODU",
                    "Is_Turu": "İŞ TÜRÜ",
                    "Renk": "RENK",
                    "Adet": "ADET",
                    "Asama": "AŞAMA",
                    "Sorumlu_Personel": "SORUMLU PERSONEL"
                })
                st.caption("💡 İpucu: Hastanın geçmişini ve kullanılan malzemeleri görmek için tablodan satırına tıklayın.")
                event = st.dataframe(df_goster,  hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row", key="uretim_tablosu")
                
                if event and len(event.selection.rows) > 0:
                    secili_idx = event.selection.rows[0]
                    s_hasta = df_isler.iloc[secili_idx]["Hasta_Adi"]
                    s_klinik = df_isler.iloc[secili_idx]["Klinik_Unvani"]
                    
                    if st.session_state.get("son_acilan_hasta") != f"{s_hasta}_{s_klinik}":
                        st.session_state.son_acilan_hasta = f"{s_hasta}_{s_klinik}"
                        hasta_karti_goster(s_hasta, s_klinik)
                else:
                    st.session_state.son_acilan_hasta = None

                st.markdown("---")
                is_secin = st.selectbox("İşlem Yapılacak Reçeteyi Seçin", ["-- Seçiniz --"] + [f"{r['Barkod']} | {r['Klinik_Unvani']} - {r['Hasta_Adi']} ({r['Is_Turu']})" for _, r in df_isler.iterrows()])
                if is_secin != "-- Seçiniz --":
                    secilen_index = [f"{r['Barkod']} | {r['Klinik_Unvani']} - {r['Hasta_Adi']} ({r['Is_Turu']})" for _, r in df_isler.iterrows()].index(is_secin)
                    s_rowid = int(df_isler.iloc[secilen_index]["id"])
                    s_barkod = df_isler.iloc[secilen_index]["Barkod"]
                    is_verisi = c.execute("SELECT Asama, Sorumlu_Personel, Lot_Numarasi, Sertifika_No, Klinik_Unvani, Hasta_Adi, Is_Turu, Tarih, Teslim_Tarihi, Renk, Adet, Tutar_TL, Aciklama, Harcanan_Malzeme FROM isler WHERE id=?",(s_rowid,)).fetchone()
                    
                    t1, t_bilgi, t2, t3, t4, t5, t6 = st.tabs(["🔄 Aşama Güncelle", "✏️ Bilgileri Güncelle", "📸 Medya & Arşiv", "📜 Garanti", "⚙️ CAM Sarfiyatı", "🔥 Sinter Sarfiyatı", "💧 Reçine Sarfiyatı"])
                    
                    with t1:
                        col_a, col_b = st.columns(2)
                        y_asama = col_a.selectbox("Yeni Aşama", ["Sipariş Alındı (Hekim Girdi)", "Tasarım Bekliyor", "Kazıma/Döküm", "Tesviye", "Seramik/Fırın", "Teslim Edildi"], index=["Sipariş Alındı (Hekim Girdi)", "Tasarım Bekliyor", "Kazıma/Döküm", "Tesviye", "Seramik/Fırın", "Teslim Edildi"].index(is_verisi[0]) if is_verisi[0] in ["Sipariş Alındı (Hekim Girdi)", "Tasarım Bekliyor", "Kazıma/Döküm", "Tesviye", "Seramik/Fırın", "Teslim Edildi"] else 1)
                        y_sorumlu = col_b.selectbox("Sorumlu Teknisyen", aktif_personeller, index=0)
                        c_btn1, c_btn2 = st.columns(2)
                        if c_btn1.button("Güncelle", use_container_width=True):
                            c.execute("UPDATE isler SET Asama=?, Sorumlu_Personel=? WHERE id=?", (y_asama, y_sorumlu, s_rowid))
                            conn.commit(); st.rerun()
                            
                        if c_btn2.button("🗑️ İşi Tamamen Sil", type="primary", use_container_width=True, key=f"is_sil_t1_{s_rowid}"):
                            # --- STOK VE FREZ İADE İŞLEMİ (Otomatik) ---
                            uretimler = c.execute("SELECT malzeme_turu, malzeme_kodu, uye_sayisi, dakika FROM uretim_loglari WHERE is_id=?", (s_rowid,)).fetchall()
                            for u in uretimler:
                                m_turu, m_kodu, m_uye, m_dk = u
                                if m_turu == 'Blok':
                                    mevcut_blok = c.execute("SELECT Kalan_Uye FROM cam_bloklar WHERE Blok_Kodu=?", (m_kodu,)).fetchone()
                                    if mevcut_blok:
                                        yeni_iade_uye = mevcut_blok[0] + m_uye
                                        c.execute("UPDATE cam_bloklar SET Kalan_Uye=?, Durum='Yarım' WHERE Blok_Kodu=?", (yeni_iade_uye, m_kodu))
                                elif m_turu == 'Frez':
                                    mevcut_frez = c.execute("SELECT kullanilan_dk FROM aktif_frezler WHERE frez_kod=? AND durum!='Kırıldı' AND durum!='Ömrü Doldu'", (m_kodu,)).fetchone()
                                    if mevcut_frez:
                                        yeni_kullanilan = max(0, mevcut_frez[0] - m_dk)
                                        c.execute("UPDATE aktif_frezler SET kullanilan_dk=? WHERE frez_kod=? AND durum!='Kırıldı' AND durum!='Ömrü Doldu'", (yeni_kullanilan, m_kodu))
                            c.execute("DELETE FROM uretim_loglari WHERE is_id=?", (s_rowid,))
                            # --------------------------------------------
                            c.execute("DELETE FROM is_fotograflari WHERE Is_ID=?", (s_rowid,))
                            c.execute("DELETE FROM is_3d_modelleri WHERE Is_ID=?", (s_rowid,))
                            # MAKİNE PARKULU: İŞ SİLİNİRSE ÇALIŞMA SÜRELERİNİ GERİ AL
                            d_sinter_row = c.execute("SELECT Sinter_Sarfiyati, Harcanan_Malzeme FROM isler WHERE id=?", (s_rowid,)).fetchone()
                            if d_sinter_row:
                                d_sinter = d_sinter_row[0]
                                d_cam = d_sinter_row[1]
                                if d_sinter and d_sinter != "-" and d_sinter.startswith("{"):
                                    try:
                                        import json
                                        ds_data = json.loads(d_sinter)
                                        df1 = ds_data.get("f1", "-- Seçiniz --"); ds1 = ds_data.get("s1", 0)
                                        df2 = ds_data.get("f2", "-- Seçiniz --"); ds2 = ds_data.get("s2", 0)
                                        if df1 != "-- Seçiniz --" and ds1 > 0: c.execute("UPDATE cihazlar SET Calisma_Saati = GREATEST(0, Calisma_Saati - ?) WHERE Cihaz_Adi=?", (ds1 / 60.0, df1))
                                        if df2 != "-- Seçiniz --" and ds2 > 0: c.execute("UPDATE cihazlar SET Calisma_Saati = GREATEST(0, Calisma_Saati - ?) WHERE Cihaz_Adi=?", (ds2 / 60.0, df2))
                                    except: pass
                                if d_cam and "Makine:" in d_cam:
                                    import re
                                    d_match = re.search(r'Makine:\s*(.*?),\s*Frezler.*?Top\.\s*(\d+)\s*Dk', d_cam)
                                    if d_match:
                                        dm_makine = d_match.group(1).strip()
                                        dm_dk = int(d_match.group(2))
                                        c.execute("UPDATE cihazlar SET Calisma_Saati = GREATEST(0, Calisma_Saati - ?) WHERE Cihaz_Adi=?", (dm_dk / 60.0, dm_makine))
                            c.execute("DELETE FROM isler WHERE id=?", (s_rowid,))
                            log_mesaji = f"[{s_barkod}] Numaralı iş kalıcı olarak silindi. ({is_verisi[4]} - {is_verisi[5]})"
                            c.execute("INSERT INTO sistem_loglari (Tarih_Saat, Kullanici, Aksiyon, Goruldu) VALUES (?,?,?,0)", 
                                      (datetime.now().strftime("%Y-%m-%d %H:%M"), st.session_state.get('kullanici_adi', 'Bilinmeyen'), log_mesaji))
                            conn.commit()
                            st.success("İş başarıyla silindi!")
                            st.rerun()
                            

                    with t_bilgi:
                        st.markdown("### ✏️ Reçete Bilgilerini Güncelle")
                        with st.form(key=f"guncelle_form_{s_rowid}"):
                            y_is_rpt = st.checkbox("🔄 Bu işi RPT (Yeniden Yapım - Bedelsiz) olarak işaretle", value="(RPT)" in is_verisi[6])
                            st.markdown("---")
                            
                            b_k1, b_k2 = st.columns(2)
                            # Klinik listesi yukarıda 'klinikler' olarak tanımlı
                            secili_k_index = klinikler.index(is_verisi[4]) if is_verisi[4] in klinikler else 0
                            y_klinik = b_k1.selectbox("Klinik", klinikler if klinikler else [is_verisi[4]], index=secili_k_index)
                            y_hasta = b_k2.text_input("Hasta Adı", value=is_verisi[5])
                            
                            b_k3, b_k4, b_k5 = st.columns(3)
                            try:
                                h_liste = [row[0] for row in c.execute("SELECT Hizmet_Adi FROM fiyat_listesi").fetchall()]
                            except: h_liste = []
                            if not h_liste: h_liste = [is_verisi[6]]
                            elif is_verisi[6] not in h_liste: h_liste.append(is_verisi[6])
                                
                            y_is = b_k3.selectbox("İş Türü", h_liste, index=h_liste.index(is_verisi[6]))
                            y_renk = b_k4.text_input("Renk", value=is_verisi[9])
                            y_adet = b_k5.number_input("Adet", min_value=1, value=int(is_verisi[10]) if is_verisi[10] else 1)
                            
                            b_k6, b_k7 = st.columns(2)
                            y_tarih = b_k6.text_input("İş Tarihi (YYYY-AA-GG SS:DD)", value=is_verisi[7])
                            y_teslim = b_k7.text_input("Teslim Tarihi", value=is_verisi[8])
                            
                            b_k8, b_k9 = st.columns(2)
                            y_lot = b_k8.text_input("Lot Numarası", value=is_verisi[2])
                            y_sertifika = b_k9.text_input("Sertifika No", value=is_verisi[3])
                            
                            y_aciklama = st.text_area("Açıklama", value=is_verisi[12])
                            y_malzeme = st.text_area("Sarfiyat (Harcanan Malzeme)", value=is_verisi[13], disabled=True)
                            
                            if st.form_submit_button("💾 Bilgileri Kaydet", type="primary", use_container_width=True):
                                if y_is_rpt and "(RPT)" not in y_is:
                                    y_is = f"{y_is} (RPT)"
                                elif not y_is_rpt and "(RPT)" in y_is:
                                    y_is = y_is.replace(" (RPT)", "").replace("(RPT)", "").strip()
                                
                                tutar_sql = ", Tutar_TL=0.0" if y_is_rpt else ""
                                
                                c.execute(f'''UPDATE isler SET 
                                    Klinik_Unvani=?, Hasta_Adi=?, Is_Turu=?, Renk=?, Adet=?, 
                                    Tarih=?, Teslim_Tarihi=?, Lot_Numarasi=?, Sertifika_No=?, Aciklama=?{tutar_sql} 
                                    WHERE id=?''', 
                                    (y_klinik, y_hasta, y_is, y_renk, y_adet, y_tarih, y_teslim, y_lot, y_sertifika, y_aciklama, s_rowid))
                                conn.commit()
                                st.success("Bilgiler başarıyla güncellendi!")
                                st.rerun()
                    
                    with t2:
                        q1, q2 = st.columns([1, 2])
                        with q1:
                            st.markdown(f"**Barkod: {s_barkod}**")
                            st.image(qr_kod_olustur(s_barkod), width=150)
                        with q2:
                            mt1, mt2 = st.tabs(["📸 Fotoğraflar", "🦷 STL Modeller"])
                            with mt1:
                                yuklenen_foto = st.file_uploader("Fotoğraf Yükle", type=["jpg", "jpeg", "png"])
                                if yuklenen_foto:
                                    if st.button("Arşive Kaydet"):
                                        h_klasor = akilli_klasor_yolu(is_verisi[4], is_verisi[5])
                                        dosya_yolu = os.path.join(h_klasor, f"FOTO_{s_rowid}_{yuklenen_foto.name}")
                                        dosya_yolu = storage_utils.dosya_kaydet(os.path.dirname(dosya_yolu), os.path.basename(dosya_yolu), yuklenen_foto)
                                        c.execute("INSERT INTO is_fotograflari (Is_ID, Dosya_Yolu) VALUES (?, ?)", (s_rowid, dosya_yolu))
                                        conn.commit(); st.success("Kaydedildi!"); st.rerun()
                                fotolar = c.execute("SELECT Dosya_Yolu FROM is_fotograflari WHERE Is_ID=?", (s_rowid,)).fetchall()
                                if fotolar:
                                    gorseller = st.columns(3)
                                    for i, foto in enumerate(fotolar):
                                        try: gorseller[i % 3].image(foto[0], use_container_width=True)
                                        except: pass
                            with mt2:
                                yuklenen_stl_lab = st.file_uploader("STL Ekle", type=["stl"], key="lab_stl")
                                if yuklenen_stl_lab:
                                    if st.button("STL Arşive Ekle"):
                                        h_klasor = akilli_klasor_yolu(is_verisi[4], is_verisi[5])
                                        dosya_yolu_stl = os.path.join(h_klasor, f"STL_{s_rowid}_{yuklenen_stl_lab.name}")
                                        dosya_yolu_stl = storage_utils.dosya_kaydet(os.path.dirname(dosya_yolu_stl), os.path.basename(dosya_yolu_stl), yuklenen_stl_lab)
                                        c.execute("INSERT INTO is_3d_modelleri (Is_ID, Dosya_Yolu) VALUES (?, ?)", (s_rowid, dosya_yolu_stl))
                                        conn.commit(); st.success("Eklendi!"); st.rerun()
                                modeller = c.execute("SELECT Dosya_Yolu FROM is_3d_modelleri WHERE Is_ID=?", (s_rowid,)).fetchall()
                                if modeller:
                                    secilen_model = st.selectbox("Görüntülenecek Model", [m[0] for m in modeller])
                                    with st.spinner("Render Ediliyor..."): stl_ciz(secilen_model)
                                    with open(secilen_model, "rb") as f: st.download_button("📥 STL İndir", f, file_name=os.path.basename(secilen_model), mime="application/octet-stream")

                    with t3:
                        st.subheader("🏅 OMG Smile Orijinallik ve Garanti Sertifikası")
                        if is_verisi[0] != "Teslim Edildi": st.warning("⚠️ Sertifika oluşturabilmek için işin '**Teslim Edildi**' aşamasına getirilmesi gerekmektedir.")
                        else:
                            mevcut_lot = is_verisi[2]; mevcut_cert = is_verisi[3]
                            with st.form("sertifika_formu"):
                                lot_giris = st.text_input("Materyal Lot Numarası", value="" if mevcut_lot == "-" else mevcut_lot)
                                if st.form_submit_button("Sertifika Üret"):
                                    if lot_giris:
                                        onek = ayar_getir("Barkod_Onek", "OMG")
                                        yeni_cert = mevcut_cert if mevcut_cert != "-" else f"{onek}-CERT-{s_rowid}{datetime.now().strftime('%M%S')}"
                                        c.execute("UPDATE isler SET Lot_Numarasi=?, Sertifika_No=? WHERE id=?", (lot_giris, yeni_cert, s_rowid))
                                        conn.commit(); st.success(f"Oluşturuldu: {yeni_cert}"); st.rerun()
                            if mevcut_cert != "-":
                                pdf_data = garanti_sertifikasi_uret(is_verisi[5], is_verisi[4], is_verisi[6], is_verisi[7], mevcut_lot, mevcut_cert)
                                st.download_button("📄 Dijital Sertifikayı İndir", data=pdf_data, file_name=f"{mevcut_cert}_Sertifika.pdf", mime="application/pdf", use_container_width=True)

                    with t4:
                        mevcut_malzeme_row = c.execute("SELECT Harcanan_Malzeme FROM isler WHERE id=?", (s_rowid,)).fetchone()
                        mevcut_malzeme = mevcut_malzeme_row[0] if mevcut_malzeme_row and mevcut_malzeme_row[0] != "-" else ""

                        if mevcut_malzeme == "CAM YOK":
                            st.info("🚫 Bu iş, başlangıçta 'CAM Sarfiyatı YOKTUR' olarak işaretlenmiştir.")
                            st.warning("Bu alana sonradan sarfiyat eklenemez. Eğer yanlış girildiyse, işi silip tekrar doğru şekilde girmelisiniz.")
                        else:
                            # 🚨 NORMAL STOK SİLİNDİ, SADECE HEKİM İŞLERİ İÇİN CAM SARFİYATI BIRAKILDI 🚨
                        
                        
                            eski_b_kodu = ""
                            eski_uye = 1
                            eski_makine = ""
                            eski_dk = 0
                            eski_frez_basina = 0
                            eski_frezler_str = ""
                        
                            import re
                            if mevcut_malzeme:
                                # Önceki kayıtlı metni ayrıştır
                                match = re.search(r"CAM:\s*(.*?)\s*\((\d+)\s*Üye\),\s*Makine:\s*(.*?),\s*(?:(?:Takımlar|Frezler):\s*(.*?),\s*)?Top\.\s*(\d+)\s*Dk(?:\s*\(Takım başı (\d+)\s*Dk\))?", mevcut_malzeme)
                                if match:
                                    eski_b_kodu = match.group(1).strip()
                                    eski_uye = int(match.group(2))
                                    eski_makine = match.group(3).strip()
                                    eski_frezler_str = match.group(4) if match.group(4) else ""
                                    eski_dk = int(match.group(5))
                                    eski_frez_basina = int(match.group(6)) if match.group(6) else 0
                                else:
                                    # Eski formatsız veriyi kurtarmaya çalış
                                    match2 = re.search(r"CAM: (.*?) \((\d+) Üye\), Makine: (.*?), Top\. (\d+) Dk", mevcut_malzeme)
                                    if match2:
                                        eski_b_kodu = match2.group(1).strip()
                                        eski_uye = int(match2.group(2))
                                        eski_makine = match2.group(3).strip()
                                        eski_dk = int(match2.group(4))
                                
                            makineler_list = kazima_makinelerini_getir()
                            def_makine_idx = makineler_list.index(eski_makine) if eski_makine in makineler_list else 0
                        
                            col_mak, col_uye, col_mbos = st.columns([2, 0.8, 3])
                            secili_makine = col_mak.selectbox("Kazıma Yapılan Makine", makineler_list, index=def_makine_idx, key=f"t4_mak_{s_rowid}")
                            harcanan_uye = col_uye.number_input("Kazınan Üye", min_value=1, value=eski_uye, key=f"t4_uye_{s_rowid}")
                        
                            cam_b = c.execute("SELECT Blok_Kodu, Urun_Adi, Boyut_Renk, Kalan_Uye FROM cam_bloklar WHERE Durum='Yarım' OR Blok_Kodu=?", (eski_b_kodu,)).fetchall()
                            cam_f = c.execute("SELECT frez_kod, frez_adi, yuva_no, toplam_omur_dk, kullanilan_dk FROM aktif_frezler WHERE makine_adi=? AND durum='Aktif'", (secili_makine,)).fetchall()
                        
                            def_blok_idx = 0
                            sec_blok_list = [f"{b[0]} | {b[1]} {b[2]} (Kalan: {b[3]} Üye)" for b in cam_b]
                            if eski_b_kodu:
                                for idx, b_str in enumerate(sec_blok_list):
                                    if b_str.startswith(eski_b_kodu):
                                        def_blok_idx = idx
                                        break
                                    
                            sec_frez_list = [f"{f[0]} | {f[2]} - {f[1]} (Kalan: {f[3]-f[4]} Dk)" for f in cam_f]
                            def_frezler = []
                            if eski_frezler_str:
                                eski_frezler = [x.strip() for x in eski_frezler_str.split(",")]
                                for f_str in sec_frez_list:
                                    if f_str.split("|")[0].strip() in eski_frezler:
                                        def_frezler.append(f_str)
                        
                            if cam_b and cam_f:
                                c_b, c_f = st.columns(2)
                                sec_blok = c_b.selectbox("İşlenen Zirkonyum Blok", sec_blok_list, index=def_blok_idx, key=f"t4_blok_{s_rowid}")
                                sec_frezler = c_f.multiselect("Kullanılan Frezler (Çoklu Seçim)", sec_frez_list, default=def_frezler, key=f"t4_frez_{s_rowid}")
                            
                                tm1, tm2, tm_bos = st.columns([1.2, 1.2, 4])
                            
                                b_time = datetime.strptime("09:00", "%H:%M").time()
                                bt_time = datetime.strptime("09:45", "%H:%M").time()
                                if eski_dk > 0:
                                    bt_time = (datetime.combine(datetime.today(), b_time) + timedelta(minutes=eski_dk)).time()
                                
                                baslama_saati_str = tm1.text_input("Başlama (SS:DD)", value=b_time.strftime("%H:%M"), key=f"t4_bas_{s_rowid}")
                                bitis_saati_str = tm2.text_input("Bitiş (SS:DD)", value=bt_time.strftime("%H:%M"), key=f"t4_bit_{s_rowid}")
                                try:
                                    baslama_saati = datetime.strptime(baslama_saati_str.strip(), "%H:%M").time()
                                    bitis_saati = datetime.strptime(bitis_saati_str.strip(), "%H:%M").time()
                                except:
                                    baslama_saati = b_time
                                    bitis_saati = bt_time
                                    st.error("Lütfen saatleri geçerli SS:DD formatında giriniz (Örn: 14:30)")
                                tm1.caption("💡 Klavyeden yazabilirsiniz.")
                            
                                start_dt = datetime.combine(datetime.today(), baslama_saati); end_dt = datetime.combine(datetime.today(), bitis_saati)
                                if end_dt < start_dt: end_dt += timedelta(days=1) 
                                harcanan_dk = int((end_dt - start_dt).total_seconds() / 60)
                                frez_sayisi = len(sec_frezler) if len(sec_frezler) > 0 else 1
                                frez_basina_dk = int(harcanan_dk / frez_sayisi)
                            
                                btn_text = "⚙️ CAM Sarfiyatını Güncelle" if mevcut_malzeme else "⚙️ CAM Sarfiyatını Kaydet"
                                
                                is_rpt_sarfiyat = False

                                if st.button(btn_text, type="primary"):
                                    if sec_frezler and harcanan_dk > 0:
                                        if mevcut_malzeme and eski_b_kodu and not is_rpt_sarfiyat:
                                            c.execute("UPDATE cam_bloklar SET Kalan_Uye = Kalan_Uye + ?, Durum='Yarım' WHERE Blok_Kodu=?", (eski_uye, eski_b_kodu))
                                            if eski_frezler_str:
                                                eski_frezler_list = [x.strip() for x in eski_frezler_str.split(",")]
                                                for f_kod in eski_frezler_list:
                                                    c.execute("UPDATE aktif_frezler SET kullanilan_dk = GREATEST(0, kullanilan_dk - ?) WHERE frez_kod=?", (eski_frez_basina, f_kod))

                                        b_kodu = sec_blok.split("|")[0].strip()
                                        mevcut_uye = c.execute("SELECT Kalan_Uye FROM cam_bloklar WHERE Blok_Kodu=?", (b_kodu,)).fetchone()[0]
                                        yeni_uye = mevcut_uye - harcanan_uye
                                        c.execute("UPDATE cam_bloklar SET Kalan_Uye=?, Durum=? WHERE Blok_Kodu=?", (yeni_uye, "Bitti" if yeni_uye <= 0 else "Yarım", b_kodu))

                                        frez_isimleri = []
                                        for fr in sec_frezler:
                                            f_kodu = fr.split("|")[0].strip()
                                            frez_isimleri.append(f_kodu)
                                            mevcut = c.execute("SELECT toplam_omur_dk, kullanilan_dk FROM aktif_frezler WHERE frez_kod=?", (f_kodu,)).fetchone()
                                            c.execute("UPDATE aktif_frezler SET kullanilan_dk=? WHERE frez_kod=?", (mevcut[1] + frez_basina_dk, f_kodu))

                                        yeni_cam_m = f"CAM: {b_kodu} ({harcanan_uye} Üye), Makine: {secili_makine}, Frezler: {','.join(frez_isimleri)}, Top. {harcanan_dk} Dk (Takım başı {frez_basina_dk} Dk)"
                                        
                                        if is_rpt_sarfiyat:
                                            yeni_cam_m = f"{mevcut_malzeme} | RPT: {yeni_cam_m}"
                                            
                                        c.execute("UPDATE isler SET Harcanan_Malzeme=? WHERE id=?", (yeni_cam_m, s_rowid))
                                        # MAKİNE PARKULU: ÇALIŞMA SÜRESİNİ OTOMATİK EKLİYORUZ (CAM)
                                        if mevcut_malzeme and eski_makine and eski_dk > 0 and not is_rpt_sarfiyat:
                                            c.execute("UPDATE cihazlar SET Calisma_Saati = GREATEST(0, Calisma_Saati - ?) WHERE Cihaz_Adi=?", (eski_dk / 60.0, eski_makine))
                                        if harcanan_dk > 0:
                                            c.execute("UPDATE cihazlar SET Calisma_Saati = Calisma_Saati + ? WHERE Cihaz_Adi=?", (harcanan_dk / 60.0, secili_makine))

                                        # 🔒 KRİTİK KABURGA: ESKİ LOG KAYITLARINI SİL, YENİSİNİ YAZ
                                        # Eğer RPT değilse eski kaydı siliyoruz ki çift log olmasın. RPT ise silmeyip yenisini de ekliyoruz.
                                        if not is_rpt_sarfiyat:
                                            c.execute("DELETE FROM uretim_loglari WHERE is_id=?", (s_rowid,))
                                    
                                        is_adi_gunc = f"{is_verisi[4]} - {is_verisi[5]}"
                                        b_adi_gunc = sec_blok.split("|")[1].split("(")[0].strip() if "|" in sec_blok else b_kodu
                                        tarih_gunc = datetime.now().strftime("%Y-%m-%d %H:%M")
                                        try:
                                            c.execute("INSERT INTO uretim_loglari (is_id, is_adi, malzeme_turu, malzeme_kodu, malzeme_adi, uye_sayisi, tarih, dakika) VALUES (?,?,?,?,?,?,?,?)",
                                                      (s_rowid, is_adi_gunc, "Blok", b_kodu, b_adi_gunc, harcanan_uye, tarih_gunc, harcanan_dk))
                                        except:
                                            c.execute("INSERT INTO uretim_loglari (is_id, is_adi, malzeme_turu, malzeme_kodu, malzeme_adi, uye_sayisi, tarih) VALUES (?,?,?,?,?,?,?)",
                                                      (s_rowid, is_adi_gunc, "Blok", b_kodu, b_adi_gunc, harcanan_uye, tarih_gunc))
                                    
                                        for fr_log in sec_frezler:
                                            f_kodu_log = fr_log.split("|")[0].strip()
                                            f_adi_log = fr_log.split("|")[1].split("(")[0].strip().replace("-", "").strip() if "|" in fr_log else f_kodu_log
                                            try:
                                                c.execute("INSERT INTO uretim_loglari (is_id, is_adi, malzeme_turu, malzeme_kodu, malzeme_adi, uye_sayisi, tarih, dakika) VALUES (?,?,?,?,?,?,?,?)",
                                                          (s_rowid, is_adi_gunc, "Frez", f_kodu_log, f_adi_log, harcanan_uye, tarih_gunc, frez_basina_dk))
                                            except:
                                                c.execute("INSERT INTO uretim_loglari (is_id, is_adi, malzeme_turu, malzeme_kodu, malzeme_adi, uye_sayisi, tarih) VALUES (?,?,?,?,?,?,?)",
                                                          (s_rowid, is_adi_gunc, "Frez", f_kodu_log, f_adi_log, harcanan_uye, tarih_gunc))
                                        # -----------------------------------------------------------
                                        conn.commit(); st.success("CAM Sarfiyatı Güncellendi!"); st.rerun()
                                    else:
                                        st.error("Lütfen en az bir frez seçin ve bitiş saatinin başlangıçtan sonra olduğundan emin olun.")
                            else:
                                st.warning("Seçilen makinede aktif frez veya sistemde yarım zirkonyum blok bulunamadı.")
                    with t5:
                        st.markdown("#### 🔥 Sinter Sarfiyatı Kaydı")
                        st.caption("İşin geçtiği sinter fırınlarını ve kalma sürelerini (dakika) seçiniz.")
                        
                        sinter_firinlari_raw = c.execute("SELECT Cihaz_Adi FROM cihazlar WHERE Kategori='Fırın (Sinter/Porselen)' AND Durum='Aktif'").fetchall()
                        sinter_firinlari = ["-- Seçiniz --"] + [f[0] for f in sinter_firinlari_raw]
                        
                        mevcut_sinter_row = c.execute("SELECT Sinter_Sarfiyati FROM isler WHERE id=?", (s_rowid,)).fetchone()
                        mevcut_sinter = mevcut_sinter_row[0] if mevcut_sinter_row and mevcut_sinter_row[0] != "-" else ""
                        
                        eski_f1 = "-- Seçiniz --"
                        eski_f2 = "-- Seçiniz --"
                        eski_s1 = 0
                        eski_s2 = 0
                        
                        import json
                        if mevcut_sinter and mevcut_sinter.startswith("{"):
                            try:
                                s_data = json.loads(mevcut_sinter)
                                eski_f1 = s_data.get("f1", "-- Seçiniz --")
                                eski_s1 = s_data.get("s1", 0)
                                eski_f2 = s_data.get("f2", "-- Seçiniz --")
                                eski_s2 = s_data.get("s2", 0)
                            except: pass
                            
                        c_f1, c_s1 = st.columns(2)
                        idx_f1 = sinter_firinlari.index(eski_f1) if eski_f1 in sinter_firinlari else 0
                        f1_val = c_f1.selectbox("1. Sinter Fırını", sinter_firinlari, index=idx_f1, key=f"t5_f1_{s_rowid}")
                        s1_val = c_s1.number_input("1. Fırın Süresi (Dk)", min_value=0, value=eski_s1, key=f"t5_s1_{s_rowid}")
                        
                        st.markdown("---")
                        
                        c_f2, c_s2 = st.columns(2)
                        idx_f2 = sinter_firinlari.index(eski_f2) if eski_f2 in sinter_firinlari else 0
                        f2_val = c_f2.selectbox("2. Sinter Fırını (Opsiyonel)", sinter_firinlari, index=idx_f2, key=f"t5_f2_{s_rowid}")
                        s2_val = c_s2.number_input("2. Fırın Süresi (Dk)", min_value=0, value=eski_s2, key=f"t5_s2_{s_rowid}")
                        
                        btn_txt = "🔥 Sinter Sarfiyatını Güncelle" if mevcut_sinter else "🔥 Sinter Sarfiyatını Kaydet"
                        if st.button(btn_txt, type="primary"):
                            yeni_sinter_json = json.dumps({"f1": f1_val, "s1": s1_val, "f2": f2_val, "s2": s2_val})
                            c.execute("UPDATE isler SET Sinter_Sarfiyati=? WHERE id=?", (yeni_sinter_json, s_rowid))
                            # MAKİNE PARKULU: ÇALIŞMA SÜRESİNİ OTOMATİK EKLİYORUZ (SİNTER)
                            if mevcut_sinter:
                                if eski_f1 != "-- Seçiniz --" and eski_s1 > 0:
                                    c.execute("UPDATE cihazlar SET Calisma_Saati = GREATEST(0, Calisma_Saati - ?) WHERE Cihaz_Adi=?", (eski_s1 / 60.0, eski_f1))
                                if eski_f2 != "-- Seçiniz --" and eski_s2 > 0:
                                    c.execute("UPDATE cihazlar SET Calisma_Saati = GREATEST(0, Calisma_Saati - ?) WHERE Cihaz_Adi=?", (eski_s2 / 60.0, eski_f2))
                            if f1_val != "-- Seçiniz --" and s1_val > 0:
                                c.execute("UPDATE cihazlar SET Calisma_Saati = Calisma_Saati + ? WHERE Cihaz_Adi=?", (s1_val / 60.0, f1_val))
                            if f2_val != "-- Seçiniz --" and s2_val > 0:
                                c.execute("UPDATE cihazlar SET Calisma_Saati = Calisma_Saati + ? WHERE Cihaz_Adi=?", (s2_val / 60.0, f2_val))
                            conn.commit()
                            st.success("Sinter Sarfiyatı başarıyla işlendi!")
                            st.rerun()

                    with t6:
                        st.markdown("#### 💧 Reçine Sarfiyatı Kaydı")
                        st.caption("İşin geçtiği 3D yazıcıyı ve reçine detaylarını seçiniz. Stoktan gram olarak düşülecektir.")
                        
                        y_list_raw = c.execute("SELECT Cihaz_Adi FROM cihazlar WHERE Kategori='3D Yazıcı' AND Durum='Aktif'").fetchall()
                        y_list = ["-- Seçiniz --"] + [f[0] for f in y_list_raw]
                        if len(y_list) == 1:
                            y_list_raw = c.execute("SELECT Cihaz_Adi FROM cihazlar WHERE Durum='Aktif'").fetchall()
                            y_list = ["-- Seçiniz --"] + [f[0] for f in y_list_raw]
                            
                        r_list_raw = c.execute("SELECT Urun_Kodu, Urun_Adi, Marka, Renk FROM stok WHERE Kategori='Reçine' AND Durum='Aktif'").fetchall()
                        r_list = ["-- Seçiniz --"]
                        for row in r_list_raw:
                            kod, adi, marka, renk = row
                            r_list.append(f"{kod} | {adi}/{marka}/{renk}")
                            
                        mevcut_recine_row = c.execute("SELECT Recine_Sarfiyati FROM isler WHERE id=?", (s_rowid,)).fetchone()
                        mevcut_recine = mevcut_recine_row[0] if mevcut_recine_row and mevcut_recine_row[0] != "-" else ""
                        
                        eski_y = "-- Seçiniz --"
                        eski_r = "-- Seçiniz --"
                        eski_s = 0
                        eski_m = 0.0
                        eski_b = "Model"
                        eski_tuketim_gr = 0.0
                        eski_model_gr = 8.0
                        eski_uye_gr = 2.0
                        
                        import json
                        if mevcut_recine and mevcut_recine.startswith("{"):
                            try:
                                r_data = json.loads(mevcut_recine)
                                eski_y = r_data.get("yazici", "-- Seçiniz --")
                                eski_r = r_data.get("recine", "-- Seçiniz --")
                                eski_s = r_data.get("sure", 0)
                                eski_m = float(r_data.get("miktar", 0.0))
                                eski_b = r_data.get("birim", "Model")
                                eski_tuketim_gr = float(r_data.get("tuketim_gr", 0.0))
                                eski_model_gr = float(r_data.get("model_gr", 8.0))
                                eski_uye_gr = float(r_data.get("uye_gr", 2.0))
                            except: pass
                        
                        r_col1, r_col2 = st.columns(2)
                        idx_y = y_list.index(eski_y) if eski_y in y_list else 0
                        y_val = r_col1.selectbox("3D Yazıcı Seçimi", y_list, index=idx_y, key=f"t6_y_{s_rowid}")
                        
                        idx_r = r_list.index(eski_r) if eski_r in r_list else 0
                        r_val = r_col2.selectbox("Reçine Seçimi (Ürün/Marka/Renk)", r_list, index=idx_r, key=f"t6_r_{s_rowid}")
                        
                        st.markdown("##### Sarfiyat Parametreleri")
                        p_col1, p_col2 = st.columns(2)
                        model_tuketim = p_col1.number_input("Model Başına (gr)", min_value=0.0, value=eski_model_gr, step=0.1, key=f"t6_mgr_{s_rowid}")
                        uye_tuketim = p_col2.number_input("Üye Başına (gr)", min_value=0.0, value=eski_uye_gr, step=0.1, key=f"t6_ugr_{s_rowid}")
                        
                        st.markdown("##### Kayıt")
                        r_col3, r_col4, r_col5 = st.columns(3)
                        s_val = r_col3.number_input("Üretim Süresi (Dk)", min_value=0, value=int(eski_s), key=f"t6_s_{s_rowid}")
                        m_val = r_col4.number_input("Miktar", min_value=0.0, value=float(eski_m), step=1.0, key=f"t6_m_{s_rowid}")
                        
                        b_list = ["Model", "Üye"]
                        idx_b = b_list.index(eski_b) if eski_b in b_list else 0
                        b_val = r_col5.selectbox("Birim", b_list, index=idx_b, key=f"t6_b_{s_rowid}")
                        
                        btn_txt_r = "💧 Reçine Sarfiyatını Güncelle" if mevcut_recine else "💧 Reçine Sarfiyatını Kaydet"
                        if st.button(btn_txt_r, type="primary", key=f"btn_rec_{s_rowid}"):
                            yeni_tuketim_gr = float(m_val * model_tuketim) if b_val == "Model" else float(m_val * uye_tuketim)
                            yeni_recine_json = json.dumps({"yazici": y_val, "recine": r_val, "sure": s_val, "miktar": m_val, "birim": b_val, "tuketim_gr": yeni_tuketim_gr, "model_gr": model_tuketim, "uye_gr": uye_tuketim})
                            c.execute("UPDATE isler SET Recine_Sarfiyati=? WHERE id=?", (yeni_recine_json, s_rowid))
                            
                            if mevcut_recine:
                                c.execute("DELETE FROM uretim_loglari WHERE is_id=? AND malzeme_turu='Reçine'", (s_rowid,))
                                if eski_y != "-- Seçiniz --" and eski_s > 0:
                                    c.execute("UPDATE cihazlar SET Calisma_Saati = GREATEST(0, Calisma_Saati - ?) WHERE Cihaz_Adi=?", (eski_s / 60.0, eski_y))
                                if eski_r != "-- Seçiniz --" and eski_tuketim_gr > 0:
                                    if " | " in eski_r:
                                        e_kod = eski_r.split(" | ")[0].strip()
                                        c.execute("UPDATE stok SET Mevcut_Miktar = Mevcut_Miktar + ? WHERE Urun_Kodu=?", (eski_tuketim_gr, e_kod))
                                    else:
                                        c.execute("UPDATE stok SET Mevcut_Miktar = Mevcut_Miktar + ? WHERE Urun_Adi=?", (eski_tuketim_gr, eski_r))
                                    
                            if y_val != "-- Seçiniz --" and s_val > 0:
                                c.execute("UPDATE cihazlar SET Calisma_Saati = Calisma_Saati + ? WHERE Cihaz_Adi=?", (s_val / 60.0, y_val))
                            if r_val != "-- Seçiniz --" and yeni_tuketim_gr > 0:
                                r_kod = r_val.split(" | ")[0].strip() if " | " in r_val else r_val
                                r_adi = r_val.split(" | ")[1].split("/")[0].strip() if " | " in r_val else r_val
                                c.execute("UPDATE stok SET Mevcut_Miktar = GREATEST(0, Mevcut_Miktar - ?) WHERE Urun_Kodu=?", (yeni_tuketim_gr, r_kod))
                                is_adi_veri = is_verisi[6] if len(is_verisi) > 6 else "-"
                                c.execute("INSERT INTO uretim_loglari (is_id, is_adi, tarih, malzeme_turu, malzeme_kodu, malzeme_adi, uye_sayisi, dakika) VALUES (?,?,?,?,?,?,?,?)", (s_rowid, is_adi_veri, datetime.now().strftime("%Y-%m-%d %H:%M"), "Reçine", r_kod, r_adi, yeni_tuketim_gr, s_val))
                                
                            conn.commit()
                            st.success("Reçine Sarfiyatı başarıyla işlendi!")
                            st.rerun()
                            st.rerun()
        with tab_cam:
            # 🚨 SİGORTA VE YENİ SÜTUN (İSİM) EKLENTİSİ 🚨
            c.execute('''CREATE TABLE IF NOT EXISTS aktif_frezler (
                id SERIAL PRIMARY KEY, makine_adi TEXT, yuva_no TEXT,
                frez_kod TEXT, toplam_omur_dk INTEGER, kullanilan_dk INTEGER,
                birim_fiyat_euro REAL, durum TEXT
            )''')
            # Eski kayıtlarda isim sütunu yoksa hata vermeden ekler
            try: c.execute("ALTER TABLE aktif_frezler ADD COLUMN frez_adi TEXT")
            except: pass
            conn.commit()

            st.markdown("### 💿 CAM İstasyonu Envanteri")

            # 💎 İŞTE YENİ CSS ZIRHINI TAM BURAYA, SEKMENİN BAŞINA KOYUYORUZ 💎
            st.markdown("""
<style>
                /* Klasör kapalıyken üzerine gelince (Hover) yazıyı mavi parlat */
                [data-testid="stExpander"] details summary:hover {
                    color: #38bdf8 !important;
                }
                /* Klasör açıldığında başlığın arka planını Koyu Lacivert ve yazıyı Mavi yap */
                [data-testid="stExpander"] details[open] summary {
                    background-color: #0f172a !important; 
                    color: #38bdf8 !important; 
                    border-radius: 8px !important;
                    font-weight: 800 !important;
                }
                /* 🚨 KLASÖRÜN (EXPANDER) AÇILAN İÇERİĞİNİ AÇIK MAVİ YAP 🚨 */
                [data-testid="stExpander"] details[open] > div[role="region"] {
                    background-color: #e0f2fe !important; /* Tatlı Açık Mavi (Sky 100) */
                    border-radius: 0 0 8px 8px !important;
                    padding: 15px !important;
                }
                /* İçerideki yazıların okunması için renklerini Koyu Lacivert yap */
                [data-testid="stExpander"] details[open] > div[role="region"] p,
                [data-testid="stExpander"] details[open] > div[role="region"] span {
                    color: #0f172a !important;
                }
</style>
            """, unsafe_allow_html=True)
            
            # --- CSS BİTTİ, NORMAL SEKMELERİMİZ BAŞLIYOR ---
            tab_frez, tab_blok = st.tabs(["⚙️ Frez (Takım) Kokpiti", "🧱 Zirkon Blok Takibi"])
            
            # ==========================================
            # 1. YENİ SİSTEM: DİNAMİK MAGAZİN KOKPİTİ
            # (Buradan aşağısı sende zaten var, oraya dokunmuyoruz)
            # ==========================================

            with tab_frez:
                # SESSİZ GÜNCELLEME: Senin eski taktığın T1, T2 kayıtlarını otomatik M1, M2 yapar
                c.execute("UPDATE aktif_frezler SET yuva_no = REPLACE(yuva_no, 'T', 'M') WHERE yuva_no LIKE 'T%'")
                conn.commit()

                # --- SIFIR FREZ TAKMA BÖLÜMÜ ---
                with st.expander("➕ Ana Stoktan SIFIR Frez Tak", expanded=False):
                    frez_stok = c.execute("SELECT Urun_Kodu, Urun_Adi, Malzeme FROM stok WHERE Kategori='Frez' AND Mevcut_Miktar > 0 AND Durum='Aktif'").fetchall()
                    
                    if frez_stok:
                        c1, c2, c3 = st.columns(3)
                        f_sec = c1.selectbox("Ana Stoktan Frez Seç", [f"{f[0]} / {f[1]} / {f[2]}" for f in frez_stok])
                        
                        makine = c2.selectbox("Makine Seç", kazima_makinelerini_getir())
                        
                        # AKILLI MAGAZİN FİLTRESİ
                        dolu_yuvalar = c.execute("SELECT yuva_no FROM aktif_frezler WHERE makine_adi=? AND durum='Aktif'", (makine,)).fetchall()
                        dolu_yuvalar_listesi = [y[0] for y in dolu_yuvalar]
                        tum_yuvalar = [f"M{i}" for i in range(1, 16)]
                        bos_yuvalar = [y for y in tum_yuvalar if y not in dolu_yuvalar_listesi] 
                        
                        if bos_yuvalar:
                            yuva = c3.selectbox("Boş Magazinler", bos_yuvalar)
                            
                            # 🚨 BARKOD SİSTEMİ DİNAMİKLEŞTİ (FRZ-T1-0634) 🚨
                            # Seçilen "M1" magazin numarasını alıp barkodda "T1" olarak gösteriyoruz.
                            # Zaman damgasını da (Örn: 0634) sonuna ekliyoruz.
                            oto_barkod = f"FRZ-{yuva.replace('M', 'T')}-{datetime.now().strftime('%H%M%S')}"
                            
                            c4, c5, c_bos = st.columns([1, 1, 1])
                            frez_kod = c4.text_input("Frez Takip Kodu", value=oto_barkod)
                            omur = c5.number_input("Beklenen Toplam Ömür (Dakika)", min_value=1, value=1500, step=100)
                            
                            st.markdown("---")
                            if st.button("🚀 SIFIR Frezi Tak ve Stoğu Düş", type="primary", use_container_width=True):
                                f_kod_stok = f_sec.split("/")[0].strip()
                                f_ad_stok = f_sec.split("/")[1].strip() 
                                
                                try:
                                    f_fiyat_tl = float(c.execute("SELECT Satis_Fiyati FROM stok WHERE Urun_Kodu=?", (f_kod_stok,)).fetchone()[0])
                                    f_fiyat_euro = f_fiyat_tl / guncel_euro_kuru_getir()
                                except:
                                    f_fiyat_euro = 0.0
                                
                                c.execute("INSERT INTO aktif_frezler (makine_adi, yuva_no, frez_kod, toplam_omur_dk, kullanilan_dk, birim_fiyat_euro, durum, frez_adi) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                                          (makine, yuva, frez_kod, omur, 0, f_fiyat_euro, "Aktif", f_ad_stok))
                                c.execute("UPDATE stok SET Mevcut_Miktar = Mevcut_Miktar - 1, Guncelleme_Tarihi=? WHERE Urun_Kodu=?", (datetime.now().strftime('%Y-%m-%d %H:%M'), f_kod_stok))
                                conn.commit()
                                st.success(f"✅ {f_ad_stok} frezi {makine} makinesinin {yuva} magazinine {frez_kod} koduyla takıldı.")
                                st.rerun()
                        else:
                            st.warning(f"⚠️ {makine} makinesinde boş magazin kalmadı!")
                    else:
                        st.error("⚠️ Ana stokta kullanıma hazır Frez bulunmuyor.")

                # --- AKTİF TAKIMLAR BÖLÜMÜ (MAKİNE BAZLI GRUPLANDIRILDI) ---
                st.markdown("#### 🟢 Magazinlerdeki Aktif Takımlar")
                
                try: 
                    df_aktif = pd.read_sql("SELECT * FROM aktif_frezler WHERE durum='Aktif' ORDER BY frez_kod ASC", conn)
                except: 
                    df_aktif = pd.DataFrame()

                if not df_aktif.empty:
                    # 🚨 SİHİR BURADA: Önce makineleri (GTR, Hybrid vb.) benzersiz olarak çekiyoruz 🚨
                    makineler = df_aktif['makine_adi'].unique()
                    
                    for makine_adi in makineler:
                        # Her makine için şık bir açılır menü (Expander) oluşturuyoruz
                        with st.expander(f"🖥️ {makine_adi} MAGAZİNİ", expanded=True):
                            # Sadece bu makineye ait olan frezleri filtrele
                            makine_frezleri = df_aktif[df_aktif['makine_adi'] == makine_adi]
                            
                            for _, r in makine_frezleri.iterrows():
                                kalan_dk = r['toplam_omur_dk'] - r['kullanilan_dk']
                                yuzde = int((r['kullanilan_dk'] / r['toplam_omur_dk']) * 100) if r['toplam_omur_dk'] > 0 else 0
                                if yuzde > 100: yuzde = 100
                                
                                f_adi_goster = r['frez_adi'] if pd.notna(r.get('frez_adi')) and r.get('frez_adi') else "Bilinmeyen Frez"
                                
                                with st.container(border=True):
                                    col_f1, col_f2, col_f3 = st.columns([2.5, 2.5, 1])
                                    
                                    # Magazin (M1, M2...) bilgisini ve frez ismini öne çıkarıyoruz
                                    col_f1.markdown(f"⚙️ **{r['yuva_no']}** | 🏷️ :green[{f_adi_goster}]")
                                    col_f1.caption(f"Barkod: `{r['frez_kod']}`")
                                    
                                    if yuzde < 80: 
                                        col_f2.progress(yuzde / 100.0, text=f"Kullanım: %{yuzde} ({r['kullanilan_dk']} / {r['toplam_omur_dk']} dk)")
                                    else: 
                                        col_f2.progress(yuzde / 100.0, text=f"⚠️ Ömür Bitiyor! Kalan: {kalan_dk} dk")
                                    
                                    with col_f3:
                                        if st.button("⏸️ Yedeğe Al", use_container_width=True, key=f"btn_park_{r['id']}"):
                                            c.execute("UPDATE aktif_frezler SET durum='Yedekte', yuva_no='-' WHERE id=?", (r['id'],))
                                            conn.commit(); st.rerun()
                                            
                                        with st.expander("⚙️ İşlemler", expanded=False):
                                            frez_unique_key = str(r['id'])
                                            yeni_dk = st.number_input("Dk Ekle", min_value=1, step=15, value=15, key=f"dk_{frez_unique_key}")
                                            if st.button("⏱️ İşle", key=f"btn_dk_{frez_unique_key}"):
                                                c.execute("UPDATE aktif_frezler SET kullanilan_dk = kullanilan_dk + ? WHERE id=?", (int(yeni_dk), int(r['id'])))
                                                conn.commit(); st.rerun()
                                            st.markdown("---")
                                            if st.button("💥 Kırıldı", type="primary", use_container_width=True, key=f"btn_kirildi_{r['id']}"):
                                                c.execute("UPDATE aktif_frezler SET durum='Kırıldı' WHERE id=?", (r['id'],))
                                                k_omur = str(r['toplam_omur_dk'] - r['kullanilan_dk']) + ' dk'
                                                c.execute("INSERT INTO fire_kayitlari (Tarih, Urun_Kodu, Urun_Adi, Miktar, Neden, Kullanici, Kalan_Omur) VALUES (?,?,?,?,?,?,?)",
                                                         (datetime.now().strftime("%Y-%m-%d %H:%M"), r['frez_kod'], r['frez_adi'], 1.0, f"CAM makinesinde ({r['makine_adi']}) kırıldı", st.session_state.get('kullanici_adi', 'Bilinmeyen'), k_omur))
                                                conn.commit(); st.rerun()
                                            if st.button("✅ Arşive Kaldır", use_container_width=True, key=f"btn_doldu_{r['id']}"):
                                                c.execute("UPDATE aktif_frezler SET durum='Ömrü Doldu' WHERE id=?", (r['id'],))
                                                c.execute("INSERT INTO malzeme_arsivi (Tarih, Urun_Kodu, Urun_Adi, Miktar, Islem_Turu, Aciklama, Kullanici) VALUES (?,?,?,?,?,?,?)",
                                                          (datetime.now().strftime("%Y-%m-%d %H:%M"), r['frez_kod'], r['frez_adi'], 1.0, "Ömrü Doldu", f"{r['makine_adi']} {r['yuva_no']} yuvasından arşive alındı.", st.session_state.get('kullanici_adi', 'Bilinmeyen')))
                                                conn.commit(); st.rerun()
                else:
                    st.info("Magazinlerde tanımlı aktif frez yok.")

                st.markdown("---")
                
                # --- 🚨 YEDEKTE BEKLEYEN (KULLANILMIŞ) FREZLER İSTASYONU 🚨 ---
                st.markdown("---")
                st.markdown("#### ⏸️ Yedekte Bekleyen (Kullanılmış) Frezler")
                st.caption("Daha önce magazinden çıkardığınız yarı-ömürlü frezler burada bekler. Bunları tekrar herhangi bir makineye atayabilirsiniz.")
                
                try: 
                    df_yedek = pd.read_sql("SELECT * FROM aktif_frezler WHERE durum='Yedekte' ORDER BY frez_kod ASC", conn)
                except: 
                    df_yedek = pd.DataFrame()
                
                if not df_yedek.empty:
                    for _, r in df_yedek.iterrows():
                        k_dk = r['toplam_omur_dk'] - r['kullanilan_dk']
                        f_adi_yedek = r['frez_adi'] if pd.notna(r.get('frez_adi')) and r.get('frez_adi') else "Bilinmeyen Frez"
                        
                        with st.container(border=True):
                            col_y1, col_y2, col_y3 = st.columns([2.5, 2.5, 2])
                            
                            col_y1.markdown(f"🏷️ **{f_adi_yedek}**")
                            col_y1.caption(f"Barkod: `{r['frez_kod']}` | Son Makinesi: {r['makine_adi']}")
                            
                            # Kalan ömre göre durum bilgisi
                            col_y2.warning(f"⏳ **Kalan:** {k_dk} Dk (Kullanım: %{int((r['kullanilan_dk']/r['toplam_omur_dk'])*100)})")
                            
                            with col_y3:
                                # 🚨 MAGAZİNE GERİ TAKMA SİSTEMİ 🚨
                                with st.expander("🔄 Magazine Geri Tak", expanded=False):
                                    makine_geri = st.selectbox("Hedef Makine", kazima_makinelerini_getir(), key=f"mak_geri_{r['id']}")
                                    
                                    # SEÇİLEN MAKİNEDEKİ BOŞ MAGAZİNLERİ BUL
                                    d_yuv = c.execute("SELECT yuva_no FROM aktif_frezler WHERE makine_adi=? AND durum='Aktif' ORDER BY yuva_no ASC", (makine_geri,)).fetchall()
                                    d_list = [y[0] for y in d_yuv]
                                    b_yuv = [f"M{i}" for i in range(1, 16) if f"M{i}" not in d_list]
                                    
                                    if b_yuv:
                                        yuva_geri = st.selectbox("Boş Magazin Seç", b_yuv, key=f"yuv_geri_{r['id']}")
                                        if st.button("🚀 Magazine Yerleştir", key=f"btn_akt_{r['id']}", type="primary", use_container_width=True):
                                            c.execute("UPDATE aktif_frezler SET durum='Aktif', makine_adi=?, yuva_no=? WHERE id=?", (makine_geri, yuva_geri, r['id']))
                                            conn.commit()
                                            st.success(f"✅ {r['frez_kod']} başarıyla {makine_geri} - {yuva_geri} magazinine takıldı!")
                                            st.rerun()
                                    else:
                                        st.error("Bu makinede boş magazin yok!")
                                    
                                    st.markdown("---")
                                    # Eğer yedekteki frez artık işe yaramayacaksa çöpe atma seçeneği
                                    if st.button("🗑️ Arşive Kaldır (Kullanma)", key=f"btn_arsiv_{r['id']}", use_container_width=True):
                                        c.execute("UPDATE aktif_frezler SET durum='Ömrü Doldu' WHERE id=?", (r['id'],))
                                        c.execute("INSERT INTO malzeme_arsivi (Tarih, Urun_Kodu, Urun_Adi, Miktar, Islem_Turu, Aciklama, Kullanici) VALUES (?,?,?,?,?,?,?)",
                                                  (datetime.now().strftime("%Y-%m-%d %H:%M"), r['frez_kod'], r['frez_adi'], 1.0, "Ömrü Doldu (Yedekten)", "Yedek deposundan arşive atıldı.", st.session_state.get('kullanici_adi', 'Bilinmeyen')))
                                        conn.commit(); st.rerun()
                else:
                    st.info("Şu an yedekte bekleyen yarı-ömürlü freziniz bulunmamaktadır.")
            # ==========================================
            # 2. ESKİ SİSTEM: ZİRKON BLOK TAKİBİ
            # ==========================================
            with tab_blok:
                st.info("Açılan Zirkonyum blokların üye takiplerini buradan yapabilirsiniz.")
                
                # 🚨 YENİ BLOK AÇMA FORMU DARALTILDI VE YAN YANA ALINDI 🚨
                with st.container(border=True):
                    c_blok1, c_blok2, c_blok3 = st.columns([2.5, 1.5, 1.5])
                    
                    zirkon_stok = c.execute("SELECT Urun_Kodu, Urun_Adi FROM stok WHERE (Kategori='Blok' OR Kategori='Zirkonyum Blok') AND Mevcut_Miktar > 0 AND Durum='Aktif'").fetchall()
                    if zirkon_stok:
                        z_sec = c_blok1.selectbox("Açılacak Blok (Stoktan Düşer)", [f"{z[0]} | {z[1]}" for z in zirkon_stok])
                        
                        try:
                            z_kod_sec = z_sec.split("|")[0].strip()
                            z_bilgi = c.execute("SELECT Renk, Kalinlik FROM stok WHERE Urun_Kodu=?", (z_kod_sec,)).fetchone()
                            varsayilan_r = ""
                            if z_bilgi:
                                r_val, k_val = z_bilgi
                                r_s = str(r_val) if r_val and r_val not in ['-', 'None'] else ""
                                k_s = str(k_val) if k_val and k_val not in ['-', 'None'] else ""
                                if r_s and k_s: varsayilan_r = f"{r_s} - {k_s}mm"
                                elif r_s: varsayilan_r = r_s
                                elif k_s: varsayilan_r = f"{k_s}mm"
                        except:
                            varsayilan_r = ""

                        b_renk = c_blok2.text_input("Renk ve Boyut", value=varsayilan_r)
                        
                        c_blok3.markdown("<br>", unsafe_allow_html=True) # Butonu hizalamak için boşluk
                        if c_blok3.button("🚀 Aç ve CAM'e Ekle", type="primary", use_container_width=True):
                            z_kod = z_sec.split("|")[0].strip()
                            z_ad = z_sec.split("|")[1].strip()
                            yeni_b_kod = f"BLK-{datetime.now().strftime('%H%M%S')}"
                            
                            try: v_kap = int(float(ayar_getir("Blok_Kapasitesi", "22")))
                            except: v_kap = 22
                            
                            c.execute("INSERT INTO cam_bloklar (Blok_Kodu, Urun_Adi, Boyut_Renk, Kapasite_Uye, Kalan_Uye, Durum) VALUES (?,?,?,?,?,?)", (yeni_b_kod, z_ad, b_renk, v_kap, v_kap, "Yarım"))
                            c.execute("UPDATE stok SET Mevcut_Miktar = Mevcut_Miktar - 1, Guncelleme_Tarihi=? WHERE Urun_Kodu=?", (datetime.now().strftime('%Y-%m-%d %H:%M'), z_kod))
                            conn.commit(); st.success(f"Blok Açıldı: {yeni_b_kod}"); st.rerun()
                    else: 
                        st.warning("Ana stokta kullanıma hazır Aktif Zirkonyum Blok kalmamış.")

                st.markdown("---")
                
                # 🚨 FİLTRE DARALTILDI 🚨
                col_filtre, col_fbos = st.columns([2, 3])
                filtre_uygula = col_filtre.checkbox("📊 Kalan Üyeye Göre Filtrele", value=False)
                if filtre_uygula:
                    min_uye_filtre = col_filtre.number_input("🔍 Min Kalan Üye:", min_value=1, max_value=22, value=1)
                else:
                    min_uye_filtre = -9999

                # 🚨 TABLO YERİNE DİNAMİK YÖNETİM KARTLARI (İLAVE/ÇÖPE AT) 🚨
                df_bloklar = pd.read_sql("SELECT id, Blok_Kodu, Urun_Adi, Boyut_Renk, Kapasite_Uye, Kalan_Uye, Durum FROM cam_bloklar WHERE Durum IN ('Yarım', 'Aktif') ORDER BY Blok_Kodu ASC", conn)
                
                if not df_bloklar.empty: 
                    gosterilecekler = df_bloklar[df_bloklar['Kalan_Uye'] >= min_uye_filtre]
                    for _, r in gosterilecekler.iterrows():
                        with st.container(border=True):
                            cb1, cb2, cb3 = st.columns([2, 1.5, 2])
                            cb1.markdown(f"🧱 **{r['Blok_Kodu']}** | 🏷️ {r['Boyut_Renk']}")
                            cb1.caption(f"Ürün: {r['Urun_Adi']}")
                            
                            gercek_kullanim = c.execute("SELECT SUM(uye_sayisi) FROM uretim_loglari WHERE malzeme_kodu=?", (r['Blok_Kodu'],)).fetchone()[0]
                            kullanilan = int(gercek_kullanim) if gercek_kullanim else 0
                            kalan = int(r['Kalan_Uye'])
                            toplam = kullanilan + kalan
                            if toplam <= 0: toplam = 22
                            
                            kullanilan_yuzde = (kullanilan / float(toplam)) * 100
                            kalan_yuzde = (kalan / float(toplam)) * 100
                            
                            bar_html = f"""
                            <div style='display: flex; justify-content: space-between; font-size: 13px; font-weight: bold; margin-bottom: 4px;'>
                                <span style='color: #ef4444;'>Kullanılan: {kullanilan}</span>
                                <span style='color: #10b981;'>Kalan: {kalan} / {toplam}</span>
                            </div>
                            <div style='width: 100%; background-color: #334155; border-radius: 8px; height: 14px; display: flex; overflow: hidden;'>
                                <div style='width: {kullanilan_yuzde}%; background-color: #ef4444; height: 100%;' title='Kullanılan: {kullanilan}'></div>
                                <div style='width: {kalan_yuzde}%; background-color: #10b981; height: 100%;' title='Kalan: {kalan}'></div>
                            </div>
                            """
                            cb2.markdown(bar_html, unsafe_allow_html=True)
                            
                            with cb3:
                                with st.expander("⚙️ Blok Yönetimi"):
                                    st.caption("Tahmininizden fazla/az üye sığdıysa buradan düzeltebilirsiniz.")
                                    
                                    # Üye ekleme / çıkarma (Mesela +2 yazıp güncelleyebilirsin)
                                    col_y1, col_y2 = st.columns([1.5, 1.5])
                                    # Benzersiz key oluşturuyoruz ki aynı blok kodu olsa bile UI karışmasın
                                    blok_unique_key = f"{r.get('id', 'tmp')}_{r['Blok_Kodu']}"
                                    ekle_cikar = col_y1.number_input("Miktar Ekle/Çıkar", value=0, step=1, key=f"uye_ayar_{blok_unique_key}")
                                    
                                    if col_y2.button("💾 Kalanı Güncelle", key=f"btn_uye_{blok_unique_key}"):
                                        yeni_uye = r['Kalan_Uye'] + ekle_cikar
                                        efektif_fark = ekle_cikar if yeni_uye > 0 else -r['Kalan_Uye']
                                        target_id = r.get('id')
                                        if yeni_uye <= 0:
                                            if target_id is not None:
                                                c.execute("UPDATE cam_bloklar SET Kalan_Uye=0, Durum='Bitti' WHERE id=?", (int(target_id),))
                                            else:
                                                c.execute("UPDATE cam_bloklar SET Kalan_Uye=0, Durum='Bitti' WHERE Blok_Kodu=?", (str(r['Blok_Kodu']),))
                                            c.execute("INSERT INTO malzeme_arsivi (Tarih, Urun_Kodu, Urun_Adi, Miktar, Islem_Turu, Aciklama, Kullanici) VALUES (?,?,?,?,?,?,?)",
                                                      (datetime.now().strftime("%Y-%m-%d %H:%M"), str(r['Blok_Kodu']), str(r['Urun_Adi']), 1.0, "Tükendi (Blok)", "Blok üyesi sıfırlandığı için otomatik arşive alındı.", st.session_state.get('kullanici_adi', 'Bilinmeyen')))
                                        else:
                                            if target_id is not None:
                                                c.execute("UPDATE cam_bloklar SET Kalan_Uye=? WHERE id=?", (int(yeni_uye), int(target_id)))
                                            else:
                                                c.execute("UPDATE cam_bloklar SET Kalan_Uye=? WHERE Blok_Kodu=?", (int(yeni_uye), str(r['Blok_Kodu'])))
                                        conn.commit(); st.rerun()
                                    
                                    st.markdown("---")
                                    # Direkt çöpe atma butonu
                                    cop_neden = st.text_input("Çöpe Atma Nedeni (Açıklama):", key=f"cop_neden_{r['Blok_Kodu']}")
                                    if st.button("🗑️ Çöpe At (Arşive Kaldır)", type="primary", use_container_width=True, key=f"btn_cop_{r['Blok_Kodu']}"):
                                        c.execute("UPDATE cam_bloklar SET Durum='Bitti', Kalan_Uye=0 WHERE Blok_Kodu=?", (r['Blok_Kodu'],))
                                        c.execute("INSERT INTO malzeme_arsivi (Tarih, Urun_Kodu, Urun_Adi, Miktar, Islem_Turu, Aciklama, Kullanici) VALUES (?,?,?,?,?,?,?)",
                                                  (datetime.now().strftime("%Y-%m-%d %H:%M"), r['Blok_Kodu'], r['Urun_Adi'], 1.0, "Çöpe Atıldı (Blok)", cop_neden if cop_neden.strip() else "Manuel çöpe atıldı.", st.session_state.get('kullanici_adi', 'Bilinmeyen')))
                                        conn.commit(); st.success("Blok çöpe atıldı/arşive kaldırıldı!"); st.rerun()
                else:
                    st.info("Kriterlere uygun aktif yarım blok bulunmuyor.")
    elif sayfa == "📱 Teknisyen Terminali":
        banner_olustur("📱", "Teknisyen Terminali", "Tablet üzerinden barkod okutun, üretime hız katın.")
        okutulan = st.text_input("📷 Barkod Okuyucu İle Taramak İçin Tıklayın:", placeholder="Barkod Numarası...", key="tablet_barkod")
        
        if okutulan:
            is_bulundu = c.execute("SELECT id, Klinik_Unvani, Hasta_Adi, Is_Turu, Asama, Sorumlu_Personel FROM isler WHERE Barkod=?", (okutulan.strip(),)).fetchone()
            if is_bulundu:
                b_rowid, b_klinik, b_hasta, b_tur, b_asama, b_sorumlu = is_bulundu
                st.markdown(f"<div class='glass-card' style='border-color:#34d399; text-align:center;'><h2 class='neon-text-green'>✅ İş Bulundu: {b_hasta}</h2><h4>Klinik: {b_klinik} | İşlem: {b_tur}</h4><p>Mevcut Durum: <b>{b_asama}</b></p></div><br>", unsafe_allow_html=True)
                
                asama_sirasi = ["Sipariş Alındı (Hekim Girdi)", "Tasarım Bekliyor", "Kazıma/Döküm", "Tesviye", "Seramik/Fırın", "Teslim Edildi"]
                mevcut_idx = asama_sirasi.index(b_asama) if b_asama in asama_sirasi else 0
                sonraki_asama = asama_sirasi[mevcut_idx + 1] if mevcut_idx < len(asama_sirasi) - 1 else "Teslim Edildi"
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    st.markdown("<div class='tablet-btn'>", unsafe_allow_html=True)
                    if st.button(f"➡️ İLERİ: {sonraki_asama}", use_container_width=True, key="btn_ileri"):
                        c.execute("UPDATE isler SET Asama=? WHERE id=?", (sonraki_asama, b_rowid))
                        conn.commit(); st.success("İşlem Başarılı!"); st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
                with col_btn2:
                    st.markdown("<div class='tablet-btn'>", unsafe_allow_html=True)
                    if st.button("📦 STOK DÜŞ / SARFİYAT", use_container_width=True, key="btn_stokdus"):
                        st.info("Bu özellik için 'İş Akışı' paneline gidiniz.")
                    st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='glass-card' style='border-color:#f87171; text-align:center;'><h2 class='neon-text-red'>❌ HATA</h2><h4>Barkod Sistemde Bulunamadı!</h4></div>", unsafe_allow_html=True)

    elif sayfa == "👥 Personel Yönetimi":
        banner_olustur("👥", "İnsan Kaynakları & Personel", "Ekibinizin özlük dosyalarını, mesailerini, avanslarını ve yıllık izinlerini kurumsal bir yapıda yönetin.")
        
        # 💎 DOSYA YÜKLEME (UPLOADER) İÇİN NÜKLEER SİBER ZIRH 💎
        st.markdown("""
<style>
            /* 1. Tüm Uploader Kasasını Şeffaf Yap */
            div[data-testid="stFileUploader"] {
                background-color: transparent !important;
            }
            
            /* 2. Sürükle Bırak Kutusunun Kendisi (Lacivert/Saydam) */
            div[data-testid="stFileUploaderDropzone"] {
                background-color: rgba(30, 41, 59, 0.6) !important;
                border: 2px dashed rgba(56, 189, 248, 0.5) !important;
                border-radius: 12px !important;
            }
            div[data-testid="stFileUploaderDropzone"]:hover {
                border-color: #38bdf8 !important;
                background-color: rgba(15, 23, 42, 0.9) !important;
            }

            /* 3. İNATÇI BEYAZ BUTON (En agresif hedefleme) */
            div[data-testid="stFileUploaderDropzone"] button,
            div[data-testid="stFileUploader"] button {
                background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%) !important;
                color: #ffffff !important;
                border: none !important;
                border-radius: 8px !important;
                box-shadow: 0 4px 15px rgba(14, 165, 233, 0.4) !important;
            }
            
            /* Butonun içindeki yazıyı da zorla beyaz yap */
            div[data-testid="stFileUploaderDropzone"] button span,
            div[data-testid="stFileUploaderDropzone"] button p {
                color: #ffffff !important;
                font-weight: 800 !important;
            }

            /* 4. "Drag and drop file here" yazısı (Açık Gri) */
            div[data-testid="stFileUploaderDropzone"] div {
                color: #cbd5e1 !important;
            }

            /* 5. "Limit 200MB per file" yazısı (Senin istediğin o silik/koyu gri) */
            div[data-testid="stFileUploaderDropzone"] small {
                color: #475569 !important; /* Koyu füme rengi */
                font-weight: 700 !important;
                font-size: 13px !important;
                opacity: 0.8 !important;
            }
            
            /* 6. Yüklendikten sonra çıkan dosya adı (Neon Yeşil) */
            div[data-testid="stFileUploaderFileName"] {
                color: #34d399 !important;
                font-weight: 800 !important;
            }
            
            /* 7. Silme İkonu (Neon Kırmızı) */
            div[data-testid="stFileUploaderDeleteBtn"] svg {
                fill: #f87171 !important;
            }
</style>
        """, unsafe_allow_html=True)

        # Sekmeleri Güncelledik: Profil Kartı eklendi!
        t_ekle, t_liste, t_profil, t_guncelle, t_finans, t_izin, t_bordro = st.tabs([
            "➕ Yeni Personel", "🗄️ Personel (GÜNCEL)", "📇 Profil Kartları", "✏️ Bilgi Güncelleme", "💸 Finans", "🏖️ İzin", "📊 Bordro"
        ])

        with t_ekle:
            col_form, col_bos = st.columns([2, 1.5])
            with col_form:
                with st.form("per_form", clear_on_submit=True):
                    st.markdown("#### 👤 Temel ve İletişim Bilgileri")
                    ad = st.text_input("Ad Soyad")
                    c1, c2 = st.columns(2)
                    tc_no = c1.text_input("T.C. Kimlik Numarası", max_chars=11)
                    gor = c2.selectbox("Birim / Görev", GOREVLER) # Önceden tanımlı listeyi kullanıyoruz
                    tel = c1.text_input("Telefon")
                    email = c2.text_input("E-Posta Adresi")
                    adres = st.text_area("İkametgah Adresi", height=80)
                    
                    st.markdown("#### 📄 Dosya ve Belgeler")
                    f1, f2 = st.columns(2)
                    foto_file = f1.file_uploader("Vesikalık Fotoğraf", type=["jpg", "png", "jpeg"])
                    cv_file = f2.file_uploader("Özgeçmiş (CV - PDF)", type=["pdf"])

                    st.markdown("#### 💰 Maaş ve Finans")
                    c3, c4 = st.columns(2)
                    maas = c3.number_input("Net Maaş (TL)", value=28075.0, step=1000.0)
                    izin_hakki = c4.number_input("Yıllık İzin Hakkı (Gün)", min_value=0, value=14, step=1)
                    iban = st.text_input("Banka IBAN Numarası")
                    
                    if st.form_submit_button("Kaydet ve Sistem Erişimi Ver", type="primary") and ad:
                        foto_yolu = "-"
                        if foto_file:
                            os.makedirs("uploads/personel/fotolar", exist_ok=True)
                            foto_yolu = os.path.join("uploads/personel/fotolar", f"{ad.replace(' ','_')}_{foto_file.name}")
                            foto_yolu = storage_utils.dosya_kaydet(os.path.dirname(foto_yolu), os.path.basename(foto_yolu), foto_file)
                        
                        cv_yolu = "-"
                        if cv_file:
                            os.makedirs("uploads/personel/cvler", exist_ok=True)
                            cv_yolu = os.path.join("uploads/personel/cvler", f"{ad.replace(' ','_')}_CV.pdf")
                            cv_yolu = storage_utils.dosya_kaydet(os.path.dirname(cv_yolu), os.path.basename(cv_yolu), cv_file)

                        c.execute("INSERT INTO personeller (Ad_Soyad, TC_No, Gorevi, Telefon, Maas, Baslama_Tarihi, Ayrilma_Tarihi, Durum, Email, Adres, IBAN, Kalan_Izin, Foto_Yolu, CV_Yolu) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", 
                                  (ad, tc_no if tc_no else "-", gor, tel, maas, datetime.now().strftime("%Y-%m-%d"), "-", "Aktif", email if email else "-", adres if adres else "-", iban if iban else "-", izin_hakki, foto_yolu, cv_yolu))
                        
                        conn.commit(); st.success(f"✅ {ad} başarıyla kaydedildi!"); st.rerun()

                        
        with t_guncelle:
            st.markdown("### ✏️ Personel Özlük Dosyası Güncelleme")
            st.info("Bilgilerini güncellemek istediğiniz personeli seçin. Mevcut bilgiler forma otomatik yüklenecektir.")
            
            # Güncellenecek personeli seçiyoruz
            personel_adlari = [row[0] for row in c.execute("SELECT Ad_Soyad FROM personeller WHERE Durum='Aktif'").fetchall()]
            
            if personel_adlari:
                secilen_g = st.selectbox("Güncellenecek Personel:", ["-- Seçiniz --"] + personel_adlari, key="guncelle_kisi_sec")
                
                if secilen_g != "-- Seçiniz --":
                    # Mevcut verileri çekiyoruz
                    p_curr = pd.read_sql(f"SELECT * FROM personeller WHERE Ad_Soyad='{secilen_g}'", conn).iloc[0]
                    
                    # Güncelleme Formu (Sola Yaslı Şık Tasarım)
                    col_form_g, col_bos_g = st.columns([2, 1.5])
                    
                    with col_form_g:
                        with st.form("per_guncelle_form"):
                            st.markdown(f"#### 🛠️ {secilen_g} - Kayıt Düzenleme")
                            
                            c1, c2 = st.columns(2)
                            yeni_tc = c1.text_input("T.C. Kimlik Numarası", value=p_curr['TC_No'], max_chars=11)
                            yeni_gor = c2.selectbox("Birim / Görev", GOREVLER, index=GOREVLER.index(p_curr['Gorevi']) if p_curr['Gorevi'] in GOREVLER else 0)
                            
                            yeni_tel = c1.text_input("Telefon", value=p_curr['Telefon'])
                            yeni_email = c2.text_input("E-Posta Adresi", value=p_curr['Email'])
                            
                            yeni_adres = st.text_area("İkametgah Adresi", value=p_curr['Adres'], height=80)
                            
                            st.markdown("#### 📄 Dosya Güncelleme (Değiştirmek istemiyorsanız boş bırakın)")
                            f1, f2 = st.columns(2)
                            yeni_foto_file = f1.file_uploader("Yeni Fotoğraf Yükle", type=["jpg", "png", "jpeg"])
                            yeni_cv_file = f2.file_uploader("Yeni CV Yükle (PDF)", type=["pdf"])
                            
                            st.markdown("#### 💰 Maaş ve Finansal Detaylar")
                            m1, m2 = st.columns(2)
                            yeni_maas = m1.number_input("Net Maaş (TL)", value=float(p_curr['Maas']), step=1000.0)
                            yeni_izin = m2.number_input("Kalan İzin Hakkı", value=int(p_curr['Kalan_Izin']), step=1)
                            yeni_iban = st.text_input("Banka IBAN Numarası", value=p_curr['IBAN'])
                            
                            if st.form_submit_button("💾 Değişiklikleri Kaydet ve Dosyaları Yenile", type="primary"):
                                # Fotoğraf İşleme
                                foto_yolu = p_curr['Foto_Yolu']
                                if yeni_foto_file:
                                    os.makedirs("uploads/personel/fotolar", exist_ok=True)
                                    foto_yolu = os.path.join("uploads/personel/fotolar", f"{secilen_g.replace(' ','_')}_{yeni_foto_file.name}")
                                    foto_yolu = storage_utils.dosya_kaydet(os.path.dirname(foto_yolu), os.path.basename(foto_yolu), yeni_foto_file)
                                
                                # CV İşleme
                                cv_yolu = p_curr['CV_Yolu']
                                if yeni_cv_file:
                                    os.makedirs("uploads/personel/cvler", exist_ok=True)
                                    cv_yolu = os.path.join("uploads/personel/cvler", f"{secilen_g.replace(' ','_')}_YENI_CV.pdf")
                                    cv_yolu = storage_utils.dosya_kaydet(os.path.dirname(cv_yolu), os.path.basename(cv_yolu), yeni_cv_file)
                                
                                # Veritabanını Güncelle
                                c.execute("""UPDATE personeller SET 
                                          TC_No=?, Gorevi=?, Telefon=?, Maas=?, Email=?, 
                                          Adres=?, IBAN=?, Kalan_Izin=?, Foto_Yolu=?, CV_Yolu=? 
                                          WHERE Ad_Soyad=?""", 
                                          (yeni_tc, yeni_gor, yeni_tel, yeni_maas, yeni_email, 
                                           yeni_adres, yeni_iban, yeni_izin, foto_yolu, cv_yolu, secilen_g))
                                
                                conn.commit()
                                st.success(f"✅ {secilen_g} isimli personelin özlük dosyası başarıyla güncellendi!")
                                st.balloons()
                                st.rerun()
            else:
                st.warning("Güncellenecek aktif personel bulunamadı.")

        with t_profil:
            st.markdown("### 📇 Personel Dijital Kimlik Kartları")
            aktif_personeller = [row[0] for row in c.execute("SELECT Ad_Soyad FROM personeller WHERE Durum='Aktif'").fetchall()]
            
            if aktif_personeller:
                secilen_p = st.selectbox("Görüntülenecek Personeli Seçin:", ["-- Seçiniz --"] + aktif_personeller)
                
                if secilen_p != "-- Seçiniz --":
                    df_p_detay = pd.read_sql(f"SELECT * FROM personeller WHERE Ad_Soyad='{secilen_p}'", conn)
                    r = df_p_detay.iloc[0]

                    st.markdown("---")
                    col_p1, col_p2 = st.columns([1, 2])
                    
                    with col_p1:
                        if r['Foto_Yolu'] != '-' and os.path.exists(r['Foto_Yolu']):
                            st.image(r['Foto_Yolu'], use_container_width=True)
                        else:
                            st.markdown("<div style='background:#334155; padding:80px; border-radius:15px; text-align:center;'>👤<br>Fotoğraf Yok</div>", unsafe_allow_html=True)
                        
                        if r['CV_Yolu'] != '-' and os.path.exists(r['CV_Yolu']):
                            with open(r['CV_Yolu'], "rb") as f:
                                st.download_button("📥 CV / Özgeçmiş İndir (PDF)", f, file_name=f"{secilen_p}_CV.pdf", use_container_width=True, type="primary")
                        else:
                            st.button("📄 CV Kayıtlı Değil", disabled=True, use_container_width=True)

                    with col_p2:
                        st.markdown(f"""
                        <div class="glass-card" style="padding:25px;">
                            <h2 style="color:#38bdf8; margin:0;">{r['Ad_Soyad']}</h2>
                            <p style="color:#94a3b8; font-weight:bold; letter-spacing:2px;">{r['Gorevi'].upper()}</p>
                            <hr style="border-color:rgba(56,189,248,0.2);">
                            <p><b>T.C. Kimlik:</b> {r['TC_No']}</p>
                            <p><b>Telefon:</b> {r['Telefon']}</p>
                            <p><b>E-Posta:</b> {r['Email']}</p>
                            <p><b>Adres:</b> {r['Adres']}</p>
                            <p><b>İşe Giriş:</b> {r['Baslama_Tarihi']}</p>
                            <p><b>Kalan İzin:</b> {r['Kalan_Izin']} Gün</p>
                            <p><b>IBAN:</b> <code style="color:#34d399;">{r['IBAN']}</code></p>
                        </div>
                        """, unsafe_allow_html=True)
            else:
                st.info("Profilini görüntülemek için önce personel kaydı yapmalısınız.")

        with t_liste:
            # 🚨 TAKVİM ZIRHI: BEYAZLIKLARI KOMPLE SİLEN VE PASİF GRİ RAKAMLARI GETİREN BAŞYAPIT 🚨
            st.markdown("""
<style>
                div[data-baseweb="calendar"] div { background-color: transparent !important; }
                div[data-baseweb="calendar"] { 
                    background-color: #1e293b !important; 
                    border-radius: 10px !important; 
                    border: 1px solid #38bdf8 !important; 
                    padding: 10px !important;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.6) !important;
                }
                div[data-baseweb="calendar"] button,
                div[data-baseweb="calendar"] [data-baseweb="select"] > div {
                    background-color: #0f172a !important; 
                    border: 1px solid #38bdf8 !important; 
                    border-radius: 6px !important;
                }
                div[data-baseweb="calendar"] [data-baseweb="select"] *,
                div[data-baseweb="calendar"] svg { color: #38bdf8 !important; fill: #38bdf8 !important; font-weight: 800 !important; }
                div[data-baseweb="calendar"] [role="columnheader"] { color: #ffffff !important; font-weight: 900 !important; font-size: 1rem !important; }
                div[data-baseweb="calendar"] [role="gridcell"] { color: #94A3B8 !important; font-weight: 700 !important; }
                div[data-baseweb="calendar"] [role="gridcell"][aria-disabled="false"] { color: #F8FAFC !important; }
                div[data-baseweb="calendar"] [role="gridcell"][aria-selected="true"],
                div[data-baseweb="calendar"] [role="gridcell"][aria-selected="true"] * { 
                    background-color: #38bdf8 !important; color: #000000 !important; font-weight: 900 !important; border-radius: 8px !important; 
                }
                div[data-baseweb="calendar"] [role="gridcell"]:hover { background-color: rgba(56,189,248,0.2) !important; border-radius: 8px !important; }
</style>
            """, unsafe_allow_html=True)

            listeleme_tipi = st.radio("Görünüm Seçiniz:", ["🟢 Aktif Personeller", "🗄️ Arşiv (Ayrılanlar)"], horizontal=True)
            
            df_p = pd.read_sql("SELECT Ad_Soyad, TC_No, Gorevi, Telefon, Maas, Kalan_Izin, Durum FROM personeller", conn)
            
            df_p.rename(columns={
                "Ad_Soyad": "Ad Soyad", 
                "TC_No": "T.C. Kimlik",
                "Gorevi": "Görev / Birim", 
                "Maas": "Net Maaş (TL)", 
                "Kalan_Izin": "Kalan İzin",
                "Durum": "Kayıt Durumu"
            }, inplace=True)
            
            def personel_stil(row):
                if row['Kayıt Durumu'] == 'Ayrıldı': 
                    return ['background-color: #F1F5F9; color: #64748B; font-weight: 700; font-style: italic;'] * len(row)
                else: 
                    return ['color: white;'] * len(row)

            if "Aktif" in listeleme_tipi:
                aktif_df = df_p[df_p["Kayıt Durumu"] == "Aktif"].copy()
                aktif_df["Net Maaş (TL)"] = aktif_df["Net Maaş (TL)"].apply(lambda x: f"{x:,.2f} ₺" if pd.notnull(x) else x)
                aktif_html = aktif_df.to_html(index=False, classes='per-table')
                st.markdown(f"<style>.per-table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }} .per-table th, .per-table td {{ color: #ffffff !important; font-weight: 800 !important; border-bottom: 1px solid rgba(56, 189, 248, 0.3); padding: 10px 8px; text-align: left; }} .per-table th {{ background-color: rgba(15, 23, 42, 0.8); color: #38bdf8 !important; }} .per-table tr:hover {{ background-color: rgba(56, 189, 248, 0.1); }}</style>", unsafe_allow_html=True)
                st.markdown(aktif_html, unsafe_allow_html=True)
                
                st.markdown("---")
                st.markdown("#### 🗑️ Personeli Arşive Kaldır (İşten Çıkış)")
                aktif_personeller = aktif_df["Ad Soyad"].tolist()
                
                if aktif_personeller:
                    col_arsiv1, col_arsiv2, col_arsiv_bos = st.columns([1.5, 1, 3.5])
                    
                    with col_arsiv1:
                        ayrilacak = st.selectbox("Arşive Gönderilecek Personel", ["-- Seçiniz --"] + aktif_personeller)
                    with col_arsiv2:
                        ayrilma_tarihi = st.date_input("Ayrılma Tarihi", format="DD/MM/YYYY").strftime("%Y-%m-%d")
                    
                    if st.button("Arşive Gönder", type="primary") and ayrilacak != "-- Seçiniz --": 
                        c.execute("UPDATE personeller SET Durum='Ayrıldı', Ayrilma_Tarihi=? WHERE Ad_Soyad=?", (ayrilma_tarihi, ayrilacak))
                        conn.commit(); st.success("Personel başarıyla arşive kaldırıldı."); st.rerun()
            else:
                arsiv_df = df_p[df_p["Kayıt Durumu"] == "Ayrıldı"].copy()
                arsiv_df["Net Maaş (TL)"] = arsiv_df["Net Maaş (TL)"].apply(lambda x: f"{x:,.2f} ₺" if pd.notnull(x) else x)
                arsiv_html = arsiv_df.to_html(index=False, classes='per-table-arsiv')
                st.markdown(f"<style>.per-table-arsiv {{ width: 100%; border-collapse: collapse; margin-top: 10px; }} .per-table-arsiv th, .per-table-arsiv td {{ color: #ffffff !important; border-bottom: 1px solid rgba(255, 255, 255, 0.1); padding: 10px 8px; text-align: left; opacity: 0.8; }} .per-table-arsiv th {{ background-color: rgba(15, 23, 42, 0.8); color: #9ca3af !important; }}</style>", unsafe_allow_html=True)
                st.markdown(arsiv_html, unsafe_allow_html=True)
                
        with t_finans:
            st.markdown("### 💸 Avans, Mesai ve Kesinti İşlemleri")
            st.info("Personelin ay içindeki tüm finansal hareketlerini buradan işleyin. Ay sonu bordrosuna otomatik yansıyacaktır.")
            aktif_personeller = [row[0] for row in c.execute("SELECT Ad_Soyad FROM personeller WHERE Durum='Aktif'").fetchall()]
            
            if aktif_personeller:
                with st.form("per_finans_form"):
                    f1, f2 = st.columns(2)
                    sec_per_fin = f1.selectbox("İşlem Yapılacak Personel", aktif_personeller)
                    islem_turu = f2.selectbox("İşlem Türü", ["Avans Verildi (-)", "Kesinti / Ceza (-)", "Fazla Mesai Ücreti (+)", "Özel Prim (+)"])
                    tutar = f1.number_input("Tutar (TL)", min_value=0.0, step=100.0)
                    aciklama = f2.text_input("Açıklama (Hangi ayın avansı, neyin mesaisi?)")
                    
                    if st.form_submit_button("Finansal Hareketi Kaydet") and tutar > 0:
                        bugun = datetime.now().strftime("%Y-%m-%d")
                        c.execute("INSERT INTO personel_finans (Tarih, Personel_Adi, Islem_Turu, Tutar, Aciklama) VALUES (?,?,?,?,?)", (bugun, sec_per_fin, islem_turu, tutar, aciklama))
                        conn.commit(); st.success(f"{sec_per_fin} için {tutar} TL {islem_turu} başarıyla işlendi!"); st.rerun()
                
                st.markdown("#### 📋 Son Hareketler")
                df_hareket = pd.read_sql("SELECT Tarih, Personel_Adi, Islem_Turu, Tutar, Aciklama FROM personel_finans ORDER BY Tarih DESC LIMIT 10", conn)
                st.dataframe(df_hareket.style.format({"Tutar": "{:,.2f} TL"}), hide_index=True, use_container_width=True)
            else: st.warning("Sistemde aktif personel bulunmuyor.")

        with t_izin:
            st.markdown("### 🏖️ Yıllık İzin Yönetimi")
            if aktif_personeller:
                with st.form("izin_form"):
                    i1, i2 = st.columns(2)
                    sec_per_izin = i1.selectbox("İzne Çıkacak Personel", aktif_personeller)
                    kullanilan_gun = i2.number_input("Kullanılacak İzin Günü (Düşülecek Miktar)", min_value=1, value=1)
                    bas_tar = i1.date_input("İzin Başlangıç")
                    bit_tar = i2.date_input("İzin Bitiş")
                    izin_notu = st.text_input("Açıklama / İzin Türü (Yıllık İzin, Rapor vb.)")
                    
                    if st.form_submit_button("İzni Onayla ve Bakiye Düş"):
                        mevcut_izin = c.execute("SELECT Kalan_Izin FROM personeller WHERE Ad_Soyad=?", (sec_per_izin,)).fetchone()[0]
                        if mevcut_izin >= kullanilan_gun:
                            yeni_izin = mevcut_izin - kullanilan_gun
                            c.execute("UPDATE personeller SET Kalan_Izin=? WHERE Ad_Soyad=?", (yeni_izin, sec_per_izin))
                            c.execute("INSERT INTO personel_izinler (Tarih, Personel_Adi, Baslangic_Tarihi, Bitis_Tarihi, Gun_Sayisi, Aciklama) VALUES (?,?,?,?,?,?)", (datetime.now().strftime("%Y-%m-%d"), sec_per_izin, bas_tar.strftime("%Y-%m-%d"), bit_tar.strftime("%Y-%m-%d"), kullanilan_gun, izin_notu))
                            conn.commit(); st.success(f"İzin onaylandı. Kalan izin hakkı: {yeni_izin} gün."); st.rerun()
                        else: st.error(f"Yetersiz izin hakkı! Personelin mevcut izni: {mevcut_izin} gün.")
                        
                st.markdown("#### 📋 İzin Geçmişi")
                df_izinler = pd.read_sql("SELECT Personel_Adi, Baslangic_Tarihi, Bitis_Tarihi, Gun_Sayisi, Aciklama FROM personel_izinler ORDER BY Baslangic_Tarihi DESC", conn)
                st.dataframe(df_izinler, hide_index=True, use_container_width=True)

        with t_bordro:
            st.markdown("### 📊 Dijital Maaş Bordrosu (Aylık Kesin Hesap)")
            st.info("Ay sonu geldiğinde personelin maaşını, avanslarını ve primlerini tek ekranda toplayıp net ödenecek tutarı hesaplayın.")
            if aktif_personeller:
                b_per = st.selectbox("Bordrosu Çıkarılacak Personel", aktif_personeller)
                
                # Personel Bilgileri
                per_bilgi = c.execute("SELECT Maas, Kalan_Izin, IBAN FROM personeller WHERE Ad_Soyad=?", (b_per,)).fetchone()
                sabit_maas = per_bilgi[0]
                
                # Bu ayın finansal hareketleri
                bu_ay_str = datetime.now().strftime("%Y-%m")
                df_finans = pd.read_sql(f"SELECT Islem_Turu, Tutar FROM personel_finans WHERE Personel_Adi='{b_per}' AND Tarih LIKE '{bu_ay_str}%'", conn)
                
                toplam_avans = df_finans[df_finans['Islem_Turu'] == 'Avans Verildi (-)']['Tutar'].sum() if not df_finans.empty else 0
                toplam_kesinti = df_finans[df_finans['Islem_Turu'] == 'Kesinti / Ceza (-)']['Tutar'].sum() if not df_finans.empty else 0
                toplam_mesai = df_finans[df_finans['Islem_Turu'] == 'Fazla Mesai Ücreti (+)']['Tutar'].sum() if not df_finans.empty else 0
                toplam_prim = df_finans[df_finans['Islem_Turu'] == 'Özel Prim (+)']['Tutar'].sum() if not df_finans.empty else 0
                
                net_odenecek = sabit_maas + toplam_mesai + toplam_prim - toplam_avans - toplam_kesinti
                para_birimi = ayar_getir("Para_Birimi", "TL")
                
                st.markdown(f"""
                <div class="glass-card" style="margin-top:20px;">
                    <h3 style="color:#38bdf8; border-bottom:1px solid #38bdf8; padding-bottom:10px;">{b_per.upper()} - {datetime.now().strftime("%B %Y")} BORDROSU</h3>
                    <div style="display:flex; justify-content:space-between; margin-bottom:10px;"><span><b>Sabit Net Maaş:</b></span> <span>{sabit_maas:,.2f} {para_birimi}</span></div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:10px; color:#34d399;"><span><b>(+) Mesai ve Primler:</b></span> <span>+ {toplam_mesai + toplam_prim:,.2f} {para_birimi}</span></div>
                    <div style="display:flex; justify-content:space-between; margin-bottom:10px; color:#f87171;"><span><b>(-) Avans ve Kesintiler:</b></span> <span>- {toplam_avans + toplam_kesinti:,.2f} {para_birimi}</span></div>
                    <hr style="border-color:rgba(255,255,255,0.2);">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size:20px; font-weight:bold;">Net Ödenecek Tutar:</span> 
                        <span class="neon-text-blue" style="font-size:32px;">{net_odenecek:,.2f} {para_birimi}</span>
                    </div>
                    <div style="margin-top:15px; font-size:12px; color:#9CA3AF;"><b>Banka (IBAN):</b> {per_bilgi[2]} | <b>Kalan Yıllık İzin:</b> {per_bilgi[1]} Gün</div>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("💸 Maaşı Öde ve Kasadan (Giderlere) İşle", type="primary", use_container_width=True):
                    gider_notu = f"{b_per} - {datetime.now().strftime('%B %Y')} Net Maaş Ödemesi (Avanslar Düşüldü)"
                    c.execute("INSERT INTO giderler (Tarih, Kategori, Aciklama, Tutar) VALUES (?,?,?,?)", (datetime.now().strftime("%Y-%m-%d"), "Maaş", gider_notu, net_odenecek))
                    c.execute("INSERT INTO personel_finans (Tarih, Personel_Adi, Islem_Turu, Tutar, Aciklama) VALUES (?,?,?,?,?)", (datetime.now().strftime("%Y-%m-%d"), b_per, "Maaş Ödemesi", net_odenecek, "Ay Sonu Kapanışı"))
                    conn.commit(); st.success(f"{net_odenecek:,.2f} {para_birimi} Maaş ödemesi başarıyla Finans (Giderler) modülüne işlendi!"); st.balloons()
    elif sayfa == "🏢 Varlık Yönetimi":
        banner_olustur("🏢", "Varlık ve Demirbaş Yönetimi", "Laboratuvarınızdaki demirbaşları, cihazları ve varlıkları yönetin.")
        
        
        # Tablo yoksa oluştur
        c.execute("CREATE TABLE IF NOT EXISTS varlik_satislari (Tarih TEXT, Varlik_Kodu TEXT, Varlik_Adi TEXT, Alinan_Fiyat REAL, Satis_Fiyati REAL, Alan_Kisi TEXT, Aciklama TEXT)")
        conn.commit()
        
        t1, t2, t3 = st.tabs(["➕ Yeni Varlık Ekle", "📊 Mevcut Varlıklar", "🗄️ Varlık Arşivi"])
        with t1:
            with st.form("yeni_varlik_formu"):
                c1, c2, c3 = st.columns(3)
                kod = c1.text_input("Varlık Kodu", value=f"VAR-{datetime.now().strftime('%H%M%S')}")
                ad = c2.text_input("Varlık Adı")
                marka = c3.text_input("Marka", value="-")
                
                kat = "Demirbaşlar"
                durum = c1.selectbox("Durum", ["Aktif", "Pasif"])
                fiy = c2.number_input("Değeri (TL)", value=0.0)
                mik = c3.number_input("Miktar", value=1.0)
                
                bir = "Adet"
                sinir = 0.0
                renk = "-"
                
                if st.form_submit_button("Sisteme Kaydet") and kod and ad:
                    c.execute("INSERT INTO stok (Urun_Kodu, Urun_Adi, Kategori, Mevcut_Miktar, Birim, Kritik_Sinir, Satis_Fiyati, Durum, Renk, Guncelleme_Tarihi, Marka) VALUES (?,?,?,?,?,?,?,?,?,?,?)", 
                              (kod, ad, kat, mik, bir, sinir, fiy, durum, renk, datetime.now().strftime('%Y-%m-%d %H:%M'), marka))
                    conn.commit(); st.success("Varlık Başarıyla Eklendi!"); st.rerun()
        
        with t2:
            df_varlik = pd.read_sql("SELECT * FROM stok WHERE Kategori='Demirbaşlar' AND Durum != 'Satıldı' ORDER BY Urun_Kodu ASC", conn)
            st.markdown("<h4 style='color: #38bdf8; margin-top:-10px;'>🔍 Varlık Envanteri</h4>", unsafe_allow_html=True)
            if df_varlik.empty:
                st.info("Kayıtlı varlık / demirbaş bulunmamaktadır.")
            else:
                isim_haritasi_varlik = {
                    "id": "id", "Urun_Kodu": "Varlık Kodu", "Urun_Adi": "Varlık Adı", 
                    "Kategori": "Kategori", "Mevcut_Miktar": "Miktar", "Birim": "Birim", 
                    "Kritik_Sinir": "Kritik Sınır", "Satis_Fiyati": "Değeri (TL)", "Durum": "Durum", 
                    "Renk": "Renk", "Guncelleme_Tarihi": "Güncelleme Tarihi", "Marka": "Marka",
                    "urun_kodu": "Varlık Kodu", "urun_adi": "Varlık Adı", 
                    "kategori": "Kategori", "mevcut_miktar": "Miktar", "birim": "Birim", 
                    "kritik_sinir": "Kritik Sınır", "satis_fiyati": "Değeri (TL)", "durum": "Durum", 
                    "renk": "Renk", "guncelleme_tarihi": "Güncelleme Tarihi", "marka": "Marka"
                }
                df_varlik.rename(columns=isim_haritasi_varlik, inplace=True)
                
                silinecekler = [k for k in ["id", "Kategori", "Birim", "Kritik Sınır", "Renk", "Barkod", "Lot_Numarasi", "Sertifika_No", "barkod", "lot_numarasi", "sertifika_no"] if k in df_varlik.columns]
                df_gorsel = df_varlik.drop(columns=silinecekler)
                
                col_tablo, col_islemler = st.columns([3.5, 1.5])
                with col_tablo:
                    st.dataframe(df_gorsel, hide_index=True, use_container_width=True)
                with col_islemler:
                    st.markdown("<h5 style='color:#38bdf8;'>⚡ İşlemler</h5>", unsafe_allow_html=True)
                    with st.container():
                        v_secenekler = [f"{r['Varlık Kodu']} | {r['Varlık Adı']}" for _, r in df_varlik.iterrows()]
                        secilen_v = st.selectbox("İşlem Yapılacak Varlık", ["— Seçiniz —"] + v_secenekler)
                        if secilen_v != "— Seçiniz —":
                            v_kod = secilen_v.split("|")[0].strip()
                            v_isim = secilen_v.split("|")[1].strip()
                            mevcut_v = c.execute("SELECT Mevcut_Miktar, Durum, Satis_Fiyati FROM stok WHERE Urun_Kodu=?", (v_kod,)).fetchone()
                            
                            with st.expander("📝 Düzenle / Güncelle", expanded=False):
                                yeni_mik = st.number_input("Yeni Miktar", value=float(mevcut_v[0]))
                                yeni_deger = st.number_input("Yeni Değer (TL)", value=float(mevcut_v[2]))
                                yeni_durum = st.selectbox("Yeni Durum", ["Aktif", "Pasif"], index=0 if mevcut_v[1]=="Aktif" else 1)
                                if st.button("💾 Güncelle", use_container_width=True):
                                    c.execute("UPDATE stok SET Mevcut_Miktar=?, Satis_Fiyati=?, Durum=?, Guncelleme_Tarihi=? WHERE Urun_Kodu=?", (yeni_mik, yeni_deger, yeni_durum, datetime.now().strftime('%Y-%m-%d %H:%M'), v_kod))
                                    conn.commit(); st.rerun()
                                
                                st.markdown("---")
                                if st.button("🗑️ Sistemden Kaldır", type="primary", use_container_width=True):
                                    c.execute("DELETE FROM stok WHERE Urun_Kodu=?", (v_kod,))
                                    conn.commit(); st.rerun()

                            with st.expander("🤝 Varlık Satışı Yap", expanded=False):
                                st.info("Bu varlığı sattığınızda sistemden düşülecek ve arşive taşınacaktır.")
                                satis_fiyat = st.number_input("Satış Fiyatı (TL)", min_value=0.0, value=float(mevcut_v[2]))
                                alan_kisi = st.text_input("Alan Kişi/Kurum")
                                s_aciklama = st.text_input("Açıklama/Not")
                                if st.button("Satışı Tamamla", type="primary", use_container_width=True) and alan_kisi:
                                    c.execute("INSERT INTO varlik_satislari (Tarih, Varlik_Kodu, Varlik_Adi, Alinan_Fiyat, Satis_Fiyati, Alan_Kisi, Aciklama) VALUES (?,?,?,?,?,?,?)",
                                              (datetime.now().strftime('%Y-%m-%d %H:%M'), v_kod, v_isim, mevcut_v[2], satis_fiyat, alan_kisi, s_aciklama))
                                    c.execute("UPDATE stok SET Durum='Satıldı', Guncelleme_Tarihi=? WHERE Urun_Kodu=?", (datetime.now().strftime('%Y-%m-%d %H:%M'), v_kod))
                                    conn.commit(); st.success("Satış işlemi başarıyla kaydedildi!"); st.rerun()

        with t3:
            df_arsiv = pd.read_sql("SELECT * FROM varlik_satislari ORDER BY Tarih DESC", conn)
            st.markdown("<h4 style='color: #38bdf8; margin-top:-10px;'>🗄️ Satış Arşivi</h4>", unsafe_allow_html=True)
            if df_arsiv.empty:
                st.info("Henüz satışı yapılmış bir varlık bulunmuyor.")
            else:
                df_arsiv_gorsel = df_arsiv.copy()
                df_arsiv_gorsel.columns = ["Tarih", "Varlık Kodu", "Varlık Adı", "Alış/Değer (TL)", "Satış Fiyatı (TL)", "Alan Kişi/Kurum", "Açıklama"]
                
                # Kar / Zarar Hesaplama Sütunu
                df_arsiv_gorsel['Fark (TL)'] = df_arsiv_gorsel['Satış Fiyatı (TL)'] - df_arsiv_gorsel['Alış/Değer (TL)']
                
                def color_fark(val):
                    color = '#10b981' if val > 0 else '#ef4444' if val < 0 else '#f59e0b'
                    return f'color: {color}'
                
                col_tablo, col_islemler = st.columns([3.5, 1.5])
                with col_tablo:
                    st.dataframe(df_arsiv_gorsel.style.map(color_fark, subset=['Fark (TL)']), hide_index=True, use_container_width=True)
                    
                with col_islemler:
                    st.markdown("<h5 style='color:#38bdf8;'>⚡ Arşiv İşlemleri</h5>", unsafe_allow_html=True)
                    with st.container():
                        arsiv_secenekler = [f"{r['Tarih']} | {r['Varlık Kodu']} - {r['Alan Kişi/Kurum']}" for _, r in df_arsiv_gorsel.iterrows()]
                        secilen_arsiv = st.selectbox("İşlem Yapılacak Kayıt", ["— Seçiniz —"] + arsiv_secenekler)
                        if secilen_arsiv != "— Seçiniz —":
                            s_tarih = secilen_arsiv.split("|")[0].strip()
                            s_vkod = secilen_arsiv.split("|")[1].split(" - ")[0].strip()
                            s_kayit = c.execute("SELECT Satis_Fiyati, Alan_Kisi, Aciklama FROM varlik_satislari WHERE Tarih=? AND Varlik_Kodu=?", (s_tarih, s_vkod)).fetchone()
                            
                            with st.expander("📝 Satışı Güncelle", expanded=False):
                                yeni_satis_fiyati = st.number_input("Yeni Satış Fiyatı (TL)", value=float(s_kayit[0]))
                                yeni_alan = st.text_input("Yeni Alan Kişi/Kurum", value=s_kayit[1])
                                yeni_aciklama = st.text_input("Yeni Açıklama", value=s_kayit[2])
                                if st.button("💾 Satışı Güncelle", use_container_width=True):
                                    c.execute("UPDATE varlik_satislari SET Satis_Fiyati=?, Alan_Kisi=?, Aciklama=? WHERE Tarih=? AND Varlik_Kodu=?", (yeni_satis_fiyati, yeni_alan, yeni_aciklama, s_tarih, s_vkod))
                                    conn.commit(); st.rerun()
                                    
                            with st.expander("↩️ Satışı İptal Et (Geri Al)", expanded=False):
                                st.warning("Bu işlem satışı arşivden siler ve varlığı tekrar envantere (Aktif olarak) ekler.")
                                if st.button("Satışı İptal Et", type="primary", use_container_width=True):
                                    c.execute("DELETE FROM varlik_satislari WHERE Tarih=? AND Varlik_Kodu=?", (s_tarih, s_vkod))
                                    c.execute("UPDATE stok SET Durum='Aktif', Guncelleme_Tarihi=? WHERE Urun_Kodu=?", (datetime.now().strftime('%Y-%m-%d %H:%M'), s_vkod))
                                    conn.commit(); st.success("Satış iptal edildi, varlık stoka döndü!"); st.rerun()


    elif sayfa == "📦 Stok Yönetimi":
        banner_olustur("📦", "Depo ve Stok Yönetimi", "Kritik envanteri takip edin, aktif/pasif ürünleri belirleyin ve akıllı tedarik siparişleri oluşturun.")
        # 💎 GÖRSEL YAMA: Stok Modülü Yükleme/İndirme Butonları 💎
        st.markdown("""
<style>
            [data-testid="stDownloadButton"] button { background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%) !important; border: none !important; box-shadow: 0 4px 15px rgba(14, 165, 233, 0.4) !important; border-radius: 10px !important; }
            [data-testid="stDownloadButton"] button p { color: #FFFFFF !important; font-weight: 800 !important; }
            [data-testid="stFileUploader"] button { background: linear-gradient(135deg, #8B5CF6 0%, #6D28D9 100%) !important; color: white !important; border: none !important; border-radius: 8px !important; box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4) !important; font-weight: 800 !important; }
            [data-testid="stFileUploaderDropzone"] { background-color: rgba(30, 41, 59, 0.6) !important; border: 2px dashed rgba(56, 189, 248, 0.5) !important; border-radius: 15px !important; transition: border 0.3s ease; }
            [data-testid="stFileUploaderDropzone"]:hover { border-color: #8B5CF6 !important; background-color: rgba(30, 41, 59, 0.8) !important; }
</style>
        """, unsafe_allow_html=True)
        t1, t2, t3, t4 = st.tabs(["➕ Yeni Ürün Ekle", "📊 Mevcut Envanter (Aktif/Pasif)", "📥 Excel/CSV Yükle", "🤖 Akıllı Tedarik & AI"])
        with t1:
            st.markdown("### Sisteme Ürün Tanımla / Güncelle")
            
            
            kat_liste = ["-- Seçiniz --"] + STOK_KATEGORILER
            kat = st.selectbox("Kategori Seçimi", kat_liste)
            if kat == "-- Seçiniz --":
                st.info("👆 Lütfen ürün eklemek veya güncellemek için bir kategori seçiniz.")
            else:

                try:
                    df_kat = pd.read_sql("SELECT * FROM stok WHERE Kategori=?", conn, params=(kat,))
                    df_kat.rename(columns=db_baglanti.case_map, inplace=True)
                except Exception:
                    df_kat = pd.DataFrame()

                secenekler = ["-- Yeni Ürün Ekle --"]
                if not df_kat.empty:
                    for k in df_kat['Urun_Kodu'].unique():
                        u_adi = df_kat[df_kat['Urun_Kodu'] == k].iloc[0].get('Urun_Adi', '')
                        s = f"{k} | {u_adi}" if u_adi else str(k)
                        if s not in secenekler: secenekler.append(s)

                sec_kod_display = st.selectbox("İşlem Yapılacak Ürün Seçin", secenekler)

                if sec_kod_display == "-- Yeni Ürün Ekle --":
                    sec_kod = sec_kod_display
                else:
                    sec_kod = sec_kod_display.split(" | ")[0].strip()

                sec_renk = "-"  # Renk ayrımı ürün kataloğu/formu düzeyinde kalktı

                # Default values for new form
                d_kod = ""
                d_ad = ""
                d_toz_boyutu = ""
                d_alasim = "Nikelsiz"
                d_malzeme = ""
                d_kalinlik = ""
                d_fiyat = 0.0
                d_para_birimi = "TL"
                d_birim = "Adet"
                d_sinir = 5.0
                d_marka = "-"
                mevcut_mik = 0.0

                if sec_kod_display != "-- Yeni Ürün Ekle --":
                    satir = df_kat[(df_kat['Urun_Kodu'] == sec_kod)].iloc[0]
                    d_kod = satir['Urun_Kodu']

                    ham_ad = str(satir['Urun_Adi'])
                    if kat == "Metal Tozu":
                        if "Boyut:" in ham_ad:
                            try: d_toz_boyutu = ham_ad.split("Boyut:")[1].split("-")[0].replace(")", "").strip()
                            except: pass
                        if "Nikelli" in ham_ad: d_alasim = "Nikelli"
                        if "Nikelsiz" in ham_ad: d_alasim = "Nikelsiz"
                        d_ad = ham_ad.split("(")[0].strip()
                    else:
                        d_ad = ham_ad

                    d_malzeme = satir.get('Malzeme', '')
                    if str(d_malzeme) == "nan": d_malzeme = ""

                    d_kalinlik = satir.get('Kalinlik', '')
                    if str(d_kalinlik) == "nan": d_kalinlik = ""

                    d_fiyat = float(satir.get('Satis_Fiyati', 0.0))
                    d_para_birimi = satir.get('Para_Birimi', 'TL')
                    if not d_para_birimi or str(d_para_birimi) == "nan": d_para_birimi = "TL"

                    d_birim = satir.get('Birim', 'Adet')
                    d_sinir = float(satir.get('Kritik_Sinir', 5.0))
                    d_marka = satir.get('Marka', '-')
                    if not d_marka or str(d_marka) == "nan": d_marka = "-"

                    mevcut_mik = float(df_kat[df_kat['Urun_Kodu'] == sec_kod]['Mevcut_Miktar'].sum())

                with st.form("yeni_stok_formu"):
                    c1, c2, c3 = st.columns(3)

                    kod = c1.text_input("Ürün Kodu", value=d_kod, key=f"kod_{sec_kod_display}")
                    ad = c2.text_input("Ürün Adı", value=d_ad, key=f"ad_{sec_kod_display}")

                    toz_boyutu = ""
                    alasim = "Nikelsiz"
                    malzeme = ""
                    kalinlik = ""

                    if kat in ["Blok", "Zirkonyum Blok"]:
                        malzeme = c3.text_input("Malzeme", value=d_malzeme, key=f"malz_{sec_kod_display}")
                        kalinlik = c1.text_input("Kalınlık (mm)", value=d_kalinlik, key=f"kal_{sec_kod_display}")
                        fiy = c2.number_input("Alış Fiyatı", value=d_fiyat, key=f"fiy_{sec_kod_display}")
                        para_birimi = c3.selectbox("Para Birimi", ["TL", "Euro"], index=0 if d_para_birimi=="TL" else 1, key=f"pb_{sec_kod_display}")
                        bir = c1.selectbox("Miktar Birimi", ["Adet", "Gram", "Litre", "Kutu"], index=["Adet", "Gram", "Litre", "Kutu"].index(d_birim) if d_birim in ["Adet", "Gram", "Litre", "Kutu"] else 0, key=f"bir_{sec_kod_display}")
                        sinir = c2.number_input("Kritik Sınır", value=d_sinir, key=f"sinir_{sec_kod_display}")
                        marka = c3.text_input("Marka", value=d_marka, key=f"marka_{sec_kod_display}")
                    elif kat == "Metal Tozu":
                        toz_boyutu = c3.text_input("Toz Boyutu (Örn: 10µm)", value=d_toz_boyutu, key=f"toz_{sec_kod_display}")
                        alasim = c1.selectbox("Alaşım Türü", ["Nikelli", "Nikelsiz"], index=0 if d_alasim=="Nikelli" else 1, key=f"alasim_{sec_kod_display}")
                        fiy = c2.number_input("Alış Fiyatı", value=d_fiyat, key=f"fiy_{sec_kod_display}")
                        para_birimi = c3.selectbox("Para Birimi", ["TL", "Euro"], index=0 if d_para_birimi=="TL" else 1, key=f"pb_{sec_kod_display}")
                        bir = c1.selectbox("Miktar Birimi", ["Adet", "Gram", "Litre", "Kutu"], index=["Adet", "Gram", "Litre", "Kutu"].index(d_birim) if d_birim in ["Adet", "Gram", "Litre", "Kutu"] else 0, key=f"bir_{sec_kod_display}")
                        sinir = c2.number_input("Kritik Sınır", value=d_sinir, key=f"sinir_{sec_kod_display}")
                        marka = c3.text_input("Marka", value=d_marka, key=f"marka_{sec_kod_display}")
                    elif kat == "Reçine":
                        malzeme = c3.text_input("Malzeme", value=d_malzeme, key=f"malz_{sec_kod_display}")
                        fiy = c1.number_input("Alış Fiyatı", value=d_fiyat, key=f"fiy_{sec_kod_display}")
                        para_birimi = c2.selectbox("Para Birimi", ["TL", "Euro"], index=0 if d_para_birimi=="TL" else 1, key=f"pb_{sec_kod_display}")
                        bir = c3.selectbox("Miktar Birimi", ["Adet", "Gram", "Litre", "Kutu"], index=["Adet", "Gram", "Litre", "Kutu"].index(d_birim) if d_birim in ["Adet", "Gram", "Litre", "Kutu"] else 0, key=f"bir_{sec_kod_display}")
                        sinir = c1.number_input("Kritik Sınır", value=d_sinir, key=f"sinir_{sec_kod_display}")
                        marka = c2.text_input("Marka", value=d_marka, key=f"marka_{sec_kod_display}")
                    elif kat == "Frez":
                        marka = c3.text_input("Marka", value=d_marka, key=f"marka_{sec_kod_display}")
                        malzeme = c1.text_input("Tipi", value=d_malzeme, key=f"tipi_{sec_kod_display}")
                        fiy = c2.number_input("Alış Fiyatı", value=d_fiyat, key=f"fiy_{sec_kod_display}")
                        para_birimi = c3.selectbox("Para Birimi", ["TL", "Euro"], index=0 if d_para_birimi=="TL" else 1, key=f"pb_{sec_kod_display}")
                        bir = c1.selectbox("Miktar Birimi", ["Adet", "Gram", "Litre", "Kutu"], index=["Adet", "Gram", "Litre", "Kutu"].index(d_birim) if d_birim in ["Adet", "Gram", "Litre", "Kutu"] else 0, key=f"bir_{sec_kod_display}")
                        sinir = c2.number_input("Kritik Sınır", value=d_sinir, key=f"sinir_{sec_kod_display}")
                    else:
                        fiy = c3.number_input("Alış Fiyatı", value=d_fiyat, key=f"fiy_{sec_kod_display}")
                        para_birimi = c1.selectbox("Para Birimi", ["TL", "Euro"], index=0 if d_para_birimi=="TL" else 1, key=f"pb_{sec_kod_display}")
                        bir = c2.selectbox("Miktar Birimi", ["Adet", "Gram", "Litre", "Kutu"], index=["Adet", "Gram", "Litre", "Kutu"].index(d_birim) if d_birim in ["Adet", "Gram", "Litre", "Kutu"] else 0, key=f"bir_{sec_kod_display}")
                        sinir = c3.number_input("Kritik Sınır", value=d_sinir, key=f"sinir_{sec_kod_display}")
                        marka = c1.text_input("Marka", value=d_marka, key=f"marka_{sec_kod_display}")

                    st.markdown("---")

                    if sec_kod_display == "-- Yeni Ürün Ekle --":
                        kayit_btn = False
                        if kat in ["Blok", "Zirkonyum Blok"]:
                            c_btn, c_cap = st.columns([1, 1])
                            with c_btn:
                                kayit_btn = st.form_submit_button("💾 Yeni Ürün Tanımla (Stoğu '0' olarak ekler)", type="primary")
                            with c_cap:
                                cap_kayit = st.form_submit_button("⚙️ Blok Kapasitesini Kaydet")
                                varsayilan_uye = st.number_input("Tahmini Üye Kapasitesi", min_value=1, value=int(float(ayar_getir("Blok_Kapasitesi", "22"))), key="blok_kap_set")
                            
                            if cap_kayit:
                                ayar_kaydet("Blok_Kapasitesi", str(varsayilan_uye))
                                st.success("Blok kapasitesi güncellendi!")
                                st.rerun()
                        else:
                            kayit_btn = st.form_submit_button("💾 Yeni Ürün Tanımla (Stoğu '0' olarak ekler)", type="primary")
                            
                        if kayit_btn and kod and ad:
                            son_ad = ad
                            if kat == "Metal Tozu":
                                ekler = []
                                if toz_boyutu.strip(): ekler.append(f"Boyut: {toz_boyutu.strip()}")
                                if alasim: ekler.append(alasim)
                                if ekler: son_ad = f"{ad} ({' - '.join(ekler)})"

                            # ⚠️ AYNI KODLU ÜRÜN ZATEN VARSA UYAR
                            kod_zaten_var = c.execute(
                                "SELECT COUNT(*) FROM stok WHERE Urun_Kodu=? AND Kategori=?", (kod, kat)
                            ).fetchone()[0]

                            if kod_zaten_var > 0:
                                st.warning(f"⚠️ **'{kod}'** kodu bu kategoride zaten kayıtlı! Güncelleme yapmak için yukarıdaki listeden bu ürünü seçin.")
                            else:
                                for col_query in [
                                    "ALTER TABLE stok ADD COLUMN Para_Birimi TEXT DEFAULT 'TL'",
                                    "ALTER TABLE stok ADD COLUMN Malzeme TEXT DEFAULT '-'",
                                    "ALTER TABLE stok ADD COLUMN Kalinlik TEXT DEFAULT '-'"
                                ]:
                                    try:
                                        c.execute(col_query)
                                        conn.commit()
                                    except:
                                        try: conn.rollback()
                                        except: pass

                                try:
                                    c.execute("INSERT INTO stok (Urun_Kodu, Urun_Adi, Kategori, Mevcut_Miktar, Birim, Kritik_Sinir, Satis_Fiyati, Durum, Renk, Guncelleme_Tarihi, Marka, Para_Birimi, Malzeme, Kalinlik) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", 
                                              (kod, son_ad, kat, 0.0, bir, sinir, fiy, "Aktif", "-", datetime.now().strftime('%Y-%m-%d %H:%M'), marka, para_birimi, malzeme if malzeme else "-", kalinlik if kalinlik else "-"))
                                    conn.commit(); st.success("Yeni ürün tanımlandı! Artık 'Stok Ekle' ile miktar ve renk ekleyebilirsiniz."); st.rerun()
                                except Exception as e:
                                    try:
                                        conn.rollback()
                                        c.execute("INSERT INTO stok (Urun_Kodu, Urun_Adi, Kategori, Mevcut_Miktar, Birim, Kritik_Sinir, Satis_Fiyati, Durum, Renk, Guncelleme_Tarihi, Marka) VALUES (?,?,?,?,?,?,?,?,?,?,?)", 
                                                  (kod, son_ad, kat, 0.0, bir, sinir, fiy, "Aktif", "-", datetime.now().strftime('%Y-%m-%d %H:%M'), marka))
                                        conn.commit(); st.success("Eklendi (Eski veritabanı şeması kullanıldı)!"); st.rerun()
                                    except Exception as e2: st.error(f"Hata: {e2}")
                    else:
                        onay_sil = False
                        if mevcut_mik > 0:
                            st.info(f"**Güncel Stok (Tüm Renkler Toplamı):** {mevcut_mik:g} {d_birim}")
                            onay_sil = st.checkbox("⚠️ Bu ürün stokta mevcut. Silmeye devam ederseniz stoktan da kalıcı olarak kaldırılacaktır. Onaylıyorum.")

                        cg, cs = st.columns(2)
                        btn_guncelle = cg.form_submit_button("🔄 Güncelle", type="primary")
                        btn_sil = cs.form_submit_button("🗑️ Sil")

                        if btn_guncelle and kod and ad:
                            son_ad = ad
                            if kat == "Metal Tozu":
                                ekler = []
                                if toz_boyutu.strip(): ekler.append(f"Boyut: {toz_boyutu.strip()}")
                                if alasim: ekler.append(alasim)
                                if ekler: son_ad = f"{ad} ({' - '.join(ekler)})"

                            for col_query in [
                                "ALTER TABLE stok ADD COLUMN Para_Birimi TEXT DEFAULT 'TL'",
                                "ALTER TABLE stok ADD COLUMN Malzeme TEXT DEFAULT '-'",
                                "ALTER TABLE stok ADD COLUMN Kalinlik TEXT DEFAULT '-'"
                            ]:
                                try:
                                    c.execute(col_query)
                                    conn.commit()
                                except:
                                    try: conn.rollback()
                                    except: pass

                            try:
                                c.execute("UPDATE stok SET Urun_Kodu=?, Urun_Adi=?, Birim=?, Kritik_Sinir=?, Satis_Fiyati=?, Marka=?, Para_Birimi=?, Malzeme=?, Kalinlik=?, Guncelleme_Tarihi=? WHERE Urun_Kodu=?",
                                          (kod, son_ad, bir, sinir, fiy, marka, para_birimi, malzeme if malzeme else "-", kalinlik if kalinlik else "-", datetime.now().strftime('%Y-%m-%d %H:%M'), sec_kod))
                                conn.commit(); st.success("Başarıyla Güncellendi!"); st.rerun()
                            except Exception as e:
                                try:
                                    conn.rollback()
                                    c.execute("UPDATE stok SET Urun_Kodu=?, Urun_Adi=?, Birim=?, Kritik_Sinir=?, Satis_Fiyati=?, Marka=?, Guncelleme_Tarihi=? WHERE Urun_Kodu=?",
                                              (kod, son_ad, bir, sinir, fiy, marka, datetime.now().strftime('%Y-%m-%d %H:%M'), sec_kod))
                                    conn.commit(); st.success("Güncellendi (Eski Şema)!"); st.rerun()
                                except Exception as e2: st.error(f"Hata: {e2}")

                        if btn_sil:
                            if mevcut_mik > 0 and not onay_sil:
                                st.error("Ürünü silmek için lütfen yukarıdaki stok uyarı kutusunu işaretleyin.")
                            else:
                                c.execute("DELETE FROM stok WHERE Urun_Kodu=?", (sec_kod,))
                                conn.commit(); st.success("Tüm renk varyasyonlarıyla birlikte sistemden silindi!"); st.rerun()

                # --- Stok Ekle Bölümü ---
                if sec_kod_display != "-- Yeni Ürün Ekle --":
                    st.markdown("#### 📦 Stoğa Ekle (Renk ve Miktar)")
                    with st.form("stok_ekle_formu"):
                        se_c1, se_c2, se_c3 = st.columns(3)
                        ekle_adet = se_c1.number_input("Adet / Miktar", min_value=1.0, value=1.0, step=1.0)
                        ekle_renk = se_c2.text_input("Renk", value="-", help="Örn: A1, A2. Rengi yoksa '-' bırakın")
                        btn_stok_ekle = se_c3.form_submit_button("➕ Stok Ekle", type="primary", use_container_width=True)

                        if btn_stok_ekle:
                            renk_temiz = ekle_renk.strip().upper() if ekle_renk.strip() != "" else "-"

                            # Bu kod ve renk ile eşleşen var mı?
                            c.execute("SELECT Mevcut_Miktar FROM stok WHERE Urun_Kodu=? AND Renk=?", (sec_kod, renk_temiz))
                            sonuc = c.fetchone()

                            if sonuc:
                                # Aynı renk zaten var, miktarını arttır.
                                yeni_miktar = float(sonuc[0]) + ekle_adet
                                c.execute("UPDATE stok SET Mevcut_Miktar=? WHERE Urun_Kodu=? AND Renk=?", (yeni_miktar, sec_kod, renk_temiz))
                            else:
                                # Yoksa yeni bir satır oluştur (diğer bilgiler aynı)
                                for col_query in [
                                    "ALTER TABLE stok ADD COLUMN Para_Birimi TEXT DEFAULT 'TL'",
                                    "ALTER TABLE stok ADD COLUMN Malzeme TEXT DEFAULT '-'",
                                    "ALTER TABLE stok ADD COLUMN Kalinlik TEXT DEFAULT '-'"
                                ]:
                                    try:
                                        c.execute(col_query)
                                        conn.commit()
                                    except:
                                        try: conn.rollback()
                                        except: pass

                                try:
                                    c.execute("INSERT INTO stok (Urun_Kodu, Urun_Adi, Kategori, Mevcut_Miktar, Birim, Kritik_Sinir, Satis_Fiyati, Durum, Renk, Guncelleme_Tarihi, Marka, Para_Birimi, Malzeme, Kalinlik) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                              (sec_kod, d_ad, kat, ekle_adet, d_birim, d_sinir, d_fiyat, "Aktif", renk_temiz, datetime.now().strftime('%Y-%m-%d %H:%M'), d_marka, d_para_birimi, d_malzeme if d_malzeme else "-", d_kalinlik if d_kalinlik else "-"))
                                except:
                                    try: conn.rollback()
                                    except: pass
                                    c.execute("INSERT INTO stok (Urun_Kodu, Urun_Adi, Kategori, Mevcut_Miktar, Birim, Kritik_Sinir, Satis_Fiyati, Durum, Renk, Guncelleme_Tarihi, Marka) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                              (sec_kod, d_ad, kat, ekle_adet, d_birim, d_sinir, d_fiyat, "Aktif", renk_temiz, datetime.now().strftime('%Y-%m-%d %H:%M'), d_marka))
                            conn.commit()
                            st.success(f"{ekle_adet} {d_birim} '{sec_kod}' (Renk: {renk_temiz}) stoğa başarıyla eklendi!")
                            st.rerun()

                st.markdown("---")
                st.markdown(f"#### 📋 {kat} Kategorisindeki Tanımlı Ürünler")
                try:
                    if not df_kat.empty:
                        df_goster = df_kat.copy()
                        if 'Para_Birimi' not in df_goster.columns: df_goster['Para_Birimi'] = 'TL'
                        if 'Malzeme' not in df_goster.columns: df_goster['Malzeme'] = '-'
                        if 'Kalinlik' not in df_goster.columns: df_goster['Kalinlik'] = '-'

                        # 🔑 AYNI ÜRÜN KODUNA SAHİP SATIRLARI BİRLEŞTİR (renk farklı olsa da tek satır)
                        df_goster = df_goster.sort_values('Urun_Kodu')
                        df_goster = df_goster.drop_duplicates(subset=['Urun_Kodu'], keep='first').reset_index(drop=True)

                        df_goster['Alış Fiyatı ve Birimi'] = df_goster['Satis_Fiyati'].astype(str) + " " + df_goster['Para_Birimi']

                        if kat in ["Blok", "Zirkonyum Blok"]:
                            mevcut_kolonlar = ['Urun_Kodu', 'Urun_Adi', 'Malzeme', 'Kalinlik', 'Kritik_Sinir', 'Marka', 'Alış Fiyatı ve Birimi']
                        elif kat == "Frez":
                            mevcut_kolonlar = ['Urun_Kodu', 'Urun_Adi', 'Malzeme', 'Marka', 'Birim', 'Kritik_Sinir', 'Alış Fiyatı ve Birimi']
                        else:
                            mevcut_kolonlar = ['Urun_Kodu', 'Urun_Adi', 'Marka', 'Birim', 'Kritik_Sinir', 'Alış Fiyatı ve Birimi']

                        final_cols = [k for k in mevcut_kolonlar if k in df_goster.columns]
                        df_goster = df_goster[final_cols]

                        isim_map = {
                            'Urun_Kodu': 'Ürün Kodu', 'Urun_Adi': 'Ürün Adı', 'Marka': 'Marka', 
                            'Birim': 'Miktar Birimi', 'Kritik_Sinir': 'Kritik Sınır', 
                            'Malzeme': 'Tipi' if kat == "Frez" else 'Malzeme', 'Kalinlik': 'Kalınlık'
                        }
                        df_goster.rename(columns=isim_map, inplace=True)

                        st.dataframe(df_goster, hide_index=True, use_container_width=True)
                    else:
                        st.info("Bu kategoride henüz tanımlı ürün bulunmuyor.")
                except Exception as e:
                    st.error(f"Liste yüklenemedi: {e}")
        with t2:
            df_stok = pd.read_sql("SELECT * FROM stok ORDER BY Urun_Kodu ASC", conn)
            df_stok.rename(columns=db_baglanti.case_map, inplace=True)

            


            # Dinamik Kolon Yeniden Adlandırma (Eski / Yeni sistem uyumu için)
            isim_haritasi = {
                "id": "id", "Urun_Kodu": "Ürün Kodu", "Urun_Adi": "Ürün Adı", 
                "Kategori": "Kategori", "Mevcut_Miktar": "Mevcut Miktar", "Birim": "Birim", 
                "Kritik_Sinir": "Kritik Sınır", "Satis_Fiyati": "Satış Fiyatı", "Durum": "Durum", 
                "Renk": "Renk", "Guncelleme_Tarihi": "Güncelleme Tarihi", "Marka": "Marka", "Para_Birimi": "Para Birimi",
                "Malzeme": "Malzeme", "Kalinlik": "Kalınlık"
            }
            df_stok.rename(columns=isim_haritasi, inplace=True)
            
            silinecek_kolonlar = [k for k in ["id", "Satış Fiyatı", "Durum"] if k in df_stok.columns]
            df_stok_gorsel = df_stok.drop(columns=silinecek_kolonlar)
            
            # SADECE STOKTA VAR OLANLARI GÖSTER (Mevcut Miktar > 0)
            df_stok_gorsel = df_stok_gorsel[df_stok_gorsel['Mevcut Miktar'] > 0]
            
            # HER RENGİ AYRI SATIRDA GÖSTER - Ürün Kodu + Renk'e göre sırala
            if not df_stok_gorsel.empty:
                sort_cols = ['Ürün Kodu']
                if 'Renk' in df_stok_gorsel.columns:
                    sort_cols.append('Renk')
                df_stok_gorsel = df_stok_gorsel.sort_values(by=sort_cols).reset_index(drop=True)
            


            stok_sekmeleri = STOK_KATEGORILER + ["🔥 Fire (Zayi)", "📦 Malzeme Arşivi"]
            alt_sekmeler = st.tabs(stok_sekmeleri)
            for i, kat_adi in enumerate(STOK_KATEGORILER):
                with alt_sekmeler[i]:
                    st.markdown(f"<h5 style='color:#38bdf8; margin-top:-10px;'>🔍 {kat_adi} Radarı</h5>", unsafe_allow_html=True)
                    col_a, _ = st.columns([2, 4])
                    stok_arama = col_a.text_input("Arama", label_visibility="collapsed", placeholder="Tüm sütunlarda ara...", key=f"ara_stok_{kat_adi}")
                    
                    df_filtre = df_stok_gorsel[df_stok_gorsel["Kategori"] == kat_adi].copy()
                    if stok_arama:
                        mask = df_filtre.astype(str).apply(lambda x: x.str.contains(stok_arama, case=False, na=False)).any(axis=1)
                        df_filtre = df_filtre[mask]
                    if not df_filtre.empty:
                        # 💎 AKILLI SIRALAMA (ÜRÜN ADI -> ÜRÜN KODU) 💎
                        df_filtre = df_filtre.sort_values(by=['Ürün Adı', 'Ürün Kodu'], ascending=[True, True])
                        
                        df_goster = df_filtre.copy()
                        if 'Malzeme' not in df_goster.columns: df_goster['Malzeme'] = '-'
                        if 'Kalınlık' not in df_goster.columns: df_goster['Kalınlık'] = '-'
                        if 'Marka' not in df_goster.columns: df_goster['Marka'] = '-'
                        
                        if kat_adi in ["Blok", "Zirkonyum Blok"]:
                            df_goster["Adet"] = df_goster["Mevcut Miktar"].astype(float).astype(int).astype(str)
                            istenen_sira = ["Ürün Kodu", "Ürün Adı", "Malzeme", "Marka", "Kalınlık", "Renk", "Adet", "Güncelleme Tarihi"]
                            mevcut_kolonlar = [k for k in istenen_sira if k in df_goster.columns]
                            df_goster = df_goster[mevcut_kolonlar]
                        elif kat_adi == "Frez":
                            df_goster["Adet"] = df_goster["Mevcut Miktar"].astype(float).astype(int).astype(str)
                            df_goster = df_goster.rename(columns={"Malzeme": "Tip"})
                            istenen_sira = ["Ürün Kodu", "Ürün Adı", "Marka", "Tip", "Adet"]
                            mevcut_kolonlar = [k for k in istenen_sira if k in df_goster.columns]
                            df_goster = df_goster[mevcut_kolonlar]
                        elif kat_adi == "Reçine":
                            istenen_sira = ["Ürün Kodu", "Ürün Adı", "Marka", "Renk", "Malzeme", "Kritik Sınır", "Mevcut Miktar"]
                            mevcut_kolonlar = [k for k in istenen_sira if k in df_goster.columns]
                            df_goster = df_goster[mevcut_kolonlar]
                        
                        # 🚨 ZARİF MAT GÜMÜŞ ZIRH 🚨
                        def satir_renk(row):
                            idx = row.name
                            mevcut = df_filtre.at[idx, 'Mevcut Miktar']
                            sinir = df_filtre.at[idx, 'Kritik Sınır']
                            if mevcut <= sinir: return ['background-color: rgba(248, 113, 113, 0.2)'] * len(row) 
                            else: return [''] * len(row)
                            
                        col_tablo, col_islemler = st.columns([3.5, 1.5])
                        
                        with col_tablo:
                            format_dict = {}
                            if "Mevcut Miktar" in df_goster.columns: format_dict["Mevcut Miktar"] = "{:.0f}"
                            if "Kritik Sınır" in df_goster.columns: format_dict["Kritik Sınır"] = "{:.0f}"
                            
                            st.dataframe(df_goster.style.format(format_dict).apply(satir_renk, axis=1), hide_index=True, use_container_width=True)

                        with col_islemler:
                            # ✏️ İŞLEMLER PANELİ (Güncelle / Sil)
                            st.markdown("<h5 style='color:#38bdf8;margin-bottom:8px;'>⚡ İşlemler</h5>", unsafe_allow_html=True)
                            
                            islem_urun_secenekleri = []
                            islem_renk_map = {}
                            for _, r in df_filtre.iterrows():
                                r_renk = r['Renk'] if pd.notna(r.get('Renk')) and str(r.get('Renk')).strip() not in ['-', ''] else "-"
                                renk_str = f" (Renk: {r_renk})" if r_renk != "-" else ""
                                opt = f"{r['Ürün Kodu']} | {r['Ürün Adı']}{renk_str} — Mevcut: {int(r['Mevcut Miktar'])}"
                                islem_urun_secenekleri.append(opt)
                                islem_renk_map[opt] = r_renk
                            
                            secilen_islem_urun = st.selectbox(
                                "İşlem Yapılacak Ürünü Seçin", 
                                ["— Seçiniz —"] + islem_urun_secenekleri,
                                key=f"islem_urun_{kat_adi}"
                            )
                            
                            if secilen_islem_urun != "— Seçiniz —":
                                secilen_kod = secilen_islem_urun.split("|")[0].strip()
                                secilen_renk = islem_renk_map.get(secilen_islem_urun, "-")
                                
                                mevcut_kayit = c.execute("SELECT Urun_Adi, Mevcut_Miktar, Renk FROM stok WHERE Urun_Kodu=? AND Renk=?", (secilen_kod, secilen_renk)).fetchone()
                                
                                if mevcut_kayit:
                                    with st.form(f"guncelle_form_{kat_adi}_{secilen_kod}_{secilen_renk}"):
                                        st.markdown(f"**✏️ Güncelle:** `{secilen_kod}`" + (f" (Renk: {secilen_renk})" if secilen_renk != "-" else ""))
                                        
                                        g_col1, g_col2 = st.columns([2, 1.5])
                                        yeni_miktar = g_col1.number_input(
                                            "Miktar", 
                                            min_value=0.0, 
                                            value=float(mevcut_kayit[1]) if mevcut_kayit[1] else 0.0,
                                            step=1.0,
                                            key=f"yeni_mik_{kat_adi}_{secilen_kod}_{secilen_renk}",
                                            label_visibility="collapsed"
                                        )
                                        
                                        submit_btn = g_col2.form_submit_button("💾 Güncelle", use_container_width=True)
                                        
                                        if submit_btn:
                                            try:
                                                c.execute("UPDATE stok SET Mevcut_Miktar=?, Guncelleme_Tarihi=? WHERE Urun_Kodu=? AND Renk=?",
                                                         (yeni_miktar, datetime.now().strftime('%Y-%m-%d %H:%M'), secilen_kod, secilen_renk))
                                                conn.commit()
                                                st.success(f"✅ Güncellendi!")
                                            except Exception as e:
                                                st.error(f"Hata: {e}")
                                                
                                    st.markdown("**📉 Stoktan Düş (Sarfiyat / Fire)**")
                                    with st.form(f"stok_dus_form_{kat_adi}_{secilen_kod}_{secilen_renk}"):
                                        islem_turu = st.radio("İşlem Türü", ["Sarfiyat (Kullanım)", "Fire (Zayi)"], horizontal=True, key=f"islem_{secilen_kod}_{secilen_renk}")
                                        d_col1, d_col2 = st.columns([1, 2])
                                        dusulecek_miktar = d_col1.number_input("Düşülecek Miktar", min_value=1.0, max_value=float(mevcut_kayit[1]) if mevcut_kayit[1] > 0 else 1.0, step=1.0, key=f"dus_mik_{secilen_kod}_{secilen_renk}")
                                        dusme_nedeni = d_col2.text_input("Açıklama", key=f"dus_neden_{secilen_kod}_{secilen_renk}")
                                        dus_btn = st.form_submit_button("📉 Stoktan Düş", use_container_width=True)

                                        if dus_btn:
                                            if dusulecek_miktar > mevcut_kayit[1]:
                                                st.error("Mevcut stoktan fazlasını düşemezsiniz!")
                                            elif not dusme_nedeni.strip():
                                                st.error("Lütfen bir açıklama giriniz!")
                                            else:
                                                try:
                                                    yeni_mevcut = mevcut_kayit[1] - dusulecek_miktar
                                                    c.execute("UPDATE stok SET Mevcut_Miktar=?, Guncelleme_Tarihi=? WHERE Urun_Kodu=? AND Renk=?",
                                                             (yeni_mevcut, datetime.now().strftime('%Y-%m-%d %H:%M'), secilen_kod, secilen_renk))
                                                    
                                                    log_mesaji = f"[{secilen_kod}] stoktan düşüldü ({islem_turu}). Miktar: {dusulecek_miktar}. Açıklama: {dusme_nedeni}"
                                                    c.execute("INSERT INTO sistem_loglari (Tarih_Saat, Kullanici, Aksiyon, Goruldu) VALUES (?,?,?,0)", 
                                                             (datetime.now().strftime("%Y-%m-%d %H:%M"), st.session_state.get('kullanici_adi', 'Bilinmeyen'), log_mesaji))
                                                    
                                                    if islem_turu == "Fire (Zayi)":
                                                        c.execute("INSERT INTO fire_kayitlari (Tarih, Urun_Kodu, Urun_Adi, Miktar, Neden, Kullanici) VALUES (?,?,?,?,?,?)",
                                                                 (datetime.now().strftime("%Y-%m-%d %H:%M"), secilen_kod, mevcut_kayit[0], dusulecek_miktar, dusme_nedeni, st.session_state.get('kullanici_adi', 'Bilinmeyen')))
                                                    else:
                                                        c.execute("INSERT INTO malzeme_arsivi (Tarih, Urun_Kodu, Urun_Adi, Miktar, Islem_Turu, Aciklama, Kullanici) VALUES (?,?,?,?,?,?,?)",
                                                                 (datetime.now().strftime("%Y-%m-%d %H:%M"), secilen_kod, mevcut_kayit[0], dusulecek_miktar, islem_turu, dusme_nedeni, st.session_state.get('kullanici_adi', 'Bilinmeyen')))
                                                    conn.commit()
                                                    st.success(f"✅ Stoktan düşüldü! Yeni Miktar: {yeni_mevcut}")
                                                except Exception as e:
                                                    st.error(f"Hata: {e}")
                                                    

                    else:
                        if stok_arama:
                            st.info(f"Arama sonucunda '{kat_adi}' kategorisinde '{stok_arama}' ile eşleşen bir ürün bulunamadı.")
                        else:
                            st.info(f"Bu kategoride henüz kayıtlı ürün bulunmuyor.")
            
            with alt_sekmeler[-2]:
                st.markdown("<h4 style='color: #f87171;'>📉 Fire ve Zayi Kayıtları</h4>", unsafe_allow_html=True)
                try:
                    df_fire = pd.read_sql('SELECT id, Tarih, Urun_Kodu as "Stok Kodu", Urun_Adi as "Ürün Adı", Miktar, Kalan_Omur as "Kalan Ömür", Neden as "Açıklama", Kullanici as "Kullanıcı" FROM fire_kayitlari ORDER BY id DESC', conn)
                    if df_fire.empty:
                        st.info("Kayıtlı fire/zayi işlemi bulunmamaktadır.")
                    else:
                        col_fa, _ = st.columns([2, 4])
                        fire_arama = col_fa.text_input("🔍 Fire/Zayi Ara", placeholder="Tüm sütunlarda ara...", key="ara_fire")
                        if fire_arama:
                            mask = df_fire.astype(str).apply(lambda x: x.str.contains(fire_arama, case=False, na=False)).any(axis=1)
                            df_fire = df_fire[mask]
                        
                        f_col1, f_col2 = st.columns([3.5, 1.5])
                        with f_col1:
                            st.dataframe(df_fire.drop(columns=["id"]), hide_index=True, use_container_width=True)
                        with f_col2:
                            st.markdown("<h5 style='color:#f87171;'>⚡ İşlemler</h5>", unsafe_allow_html=True)
                            f_secenekler = [f"{r['id']} | {r['Stok Kodu']} - {r['Ürün Adı']}" for _, r in df_fire.iterrows()]
                            secilen_fire = st.selectbox("İşlem Yapılacak Kaydı Seçin", ["— Seçiniz —"] + f_secenekler, key="fire_secim")
                            
                            if secilen_fire != "— Seçiniz —":
                                f_id = secilen_fire.split("|")[0].strip()
                                mevcut_f = c.execute("SELECT Miktar, Neden, Urun_Kodu FROM fire_kayitlari WHERE id=?", (f_id,)).fetchone()
                                if mevcut_f:
                                    with st.form("fire_guncelle_form"):
                                        st.markdown(f"**✏️ Güncelle:**")
                                        y_mik = st.number_input("Miktar", min_value=0.0, value=float(mevcut_f[0]), step=1.0)
                                        y_neden = st.text_input("Açıklama", value=mevcut_f[1])
                                        if st.form_submit_button("💾 Güncelle", type="primary", use_container_width=True):
                                            fark = y_mik - mevcut_f[0]
                                            c.execute("UPDATE fire_kayitlari SET Miktar=?, Neden=? WHERE id=?", (y_mik, y_neden, f_id))
                                            c.execute("UPDATE stok SET Mevcut_Miktar = Mevcut_Miktar - ? WHERE Urun_Kodu=?", (fark, mevcut_f[2]))
                                            conn.commit()
                                            st.success("✅ Güncellendi!")
                                            st.rerun()
                                    
                                    st.markdown("**🗑️ Sil**")
                                    if st.button("🗑️ Sil", key="fire_sil_btn", type="primary", use_container_width=True):
                                        c.execute("UPDATE stok SET Mevcut_Miktar = Mevcut_Miktar + ? WHERE Urun_Kodu=?", (mevcut_f[0], mevcut_f[2]))
                                        c.execute("DELETE FROM fire_kayitlari WHERE id=?", (f_id,))
                                        conn.commit()
                                        st.success("✅ Silindi ve stok iade edildi!")
                                        st.rerun()
                except Exception as e:
                    st.error(f"Tablo yüklenirken hata oluştu: {e}")
            
            with alt_sekmeler[-1]:
                st.markdown("<h4 style='color: #a78bfa;'>📦 Malzeme Arşivi & Performans Dashboard</h4>", unsafe_allow_html=True)
                try:
                    df_arsiv = pd.read_sql('''
                        SELECT 
                            Urun_Kodu, 
                            Urun_Adi, 
                            CAST(Miktar AS TEXT),
                            Islem_Turu, 
                            Aciklama, 
                            Tarih,
                            0,
                            Kullanici,
                            CASE 
                                WHEN EXISTS (SELECT 1 FROM cam_bloklar c WHERE c.Blok_Kodu = m.Urun_Kodu AND c.Durum IN ('Yarım', 'Aktif')) THEN 'Aktif'
                                WHEN EXISTS (SELECT 1 FROM aktif_frezler f WHERE f.frez_kod = m.Urun_Kodu AND f.durum = 'Aktif') THEN 'Aktif'
                                WHEN EXISTS (SELECT 1 FROM stok s WHERE s.Urun_Kodu = m.Urun_Kodu AND s.Durum = 'Aktif') THEN 'Aktif'
                                ELSE 'Pasif'
                            END,
                            '-' as yapilan_is
                        FROM malzeme_arsivi m

                        UNION ALL

                        SELECT 
                            u.malzeme_kodu,
                            u.malzeme_adi,
                            CAST(u.uye_sayisi AS TEXT),
                            'Üretim (' || u.malzeme_turu || ')',
                            u.is_adi,
                            u.tarih,
                            COALESCE(u.dakika, 0),
                            'Sistem (Üretim Logu)',
                            CASE 
                                WHEN EXISTS (SELECT 1 FROM cam_bloklar c WHERE c.Blok_Kodu = u.malzeme_kodu AND c.Durum IN ('Yarım', 'Aktif')) THEN 'Aktif'
                                WHEN EXISTS (SELECT 1 FROM aktif_frezler f WHERE f.frez_kod = u.malzeme_kodu AND f.durum = 'Aktif') THEN 'Aktif'
                                WHEN EXISTS (SELECT 1 FROM stok s WHERE s.Urun_Kodu = u.malzeme_kodu AND s.Durum = 'Aktif') THEN 'Aktif'
                                ELSE 'Pasif'
                            END,
                            COALESCE(i.Is_Turu, '-') as yapilan_is
                        FROM uretim_loglari u
                        LEFT JOIN isler i ON u.is_id = i.id
                        
                        ORDER BY 6 DESC
                    ''', conn)

                    if df_arsiv.empty:
                        st.info("Arşivlenmiş malzeme veya üretim logu bulunmamaktadır.")
                    else:
                        # SQLite / PostgreSQL Alias farklarını yok etmek için kolonları Pandas seviyesinde zorla:
                        df_arsiv.columns = ["stok_kodu", "urun_adi", "miktar_veya_uye", "islem_turu", "aciklama", "tarih", "harcanan_dk", "sistem_kullanici", "durum", "yapilan_is"]
                        
                        st.markdown("<br>", unsafe_allow_html=True)
                        col_ma, _ = st.columns([2, 4])
                        arsiv_arama = col_ma.text_input("🔍 Arşivde Ara", placeholder="Tüm sütunlarda ara...", key="ara_arsiv")
                        if arsiv_arama:
                            mask = df_arsiv.astype(str).apply(lambda x: x.str.contains(arsiv_arama, case=False, na=False)).any(axis=1)
                            df_arsiv = df_arsiv[mask]
                            
                        if df_arsiv.empty:
                            st.warning("Arama kriterinize uygun arşiv kaydı bulunamadı.")
                        
                        # İlk olarak her bloğun kategorisini belirlemek ve özet listeyi oluşturmak için verileri işleyelim
                        liste_verileri = []
                        essiz_kodlar = df_arsiv['stok_kodu'].unique()
                        
                        stok_malzeme_map = {}
                        stok_kategori_map = {}
                        if len(essiz_kodlar) > 0:
                            kod_list = "', '".join([str(k) for k in essiz_kodlar])
                            try:
                                q = f"SELECT Urun_Kodu, COALESCE(Malzeme, ''), COALESCE(Kategori, '') FROM stok WHERE Urun_Kodu IN ('{kod_list}')"
                                rows = c.execute(q).fetchall()
                                for r in rows:
                                    if r[1]:
                                        stok_malzeme_map[r[0]] = r[1]
                                    if r[2]:
                                        stok_kategori_map[r[0]] = r[2]
                            except:
                                pass
                                
                        def kategori_belirle(urun_adi, isler_serisi, urun_malzeme, urun_kategori="", islem_turu_serisi=None):
                            # 1. ÖNCELİK: Stok tablosundaki Kategori bilgisi (en güvenilir)
                            u_kat = str(urun_kategori).lower()
                            if 'reçine' in u_kat or 'recine' in u_kat:
                                return 'REÇİNE'
                            if 'pmma' in u_kat:
                                return 'PMMA'
                            if 'zirkon' in u_kat or 'zircon' in u_kat:
                                return 'ZİRKONYUM'
                            if 'titan' in u_kat:
                                return 'TİTANYUM'
                            if 'frez' in u_kat:
                                return 'FREZ'

                            # 2. ÖNCELİK: uretim_loglari'ndaki malzeme_turu (Reçine kayıtları için)
                            if islem_turu_serisi is not None:
                                islem_serisi_lower = islem_turu_serisi.astype(str).str.lower()
                                if islem_serisi_lower.str.contains('reçine|recine').any():
                                    return 'REÇİNE'
                                if islem_serisi_lower.str.contains('frez').any():
                                    return 'FREZ'
                                if islem_serisi_lower.str.contains('blok').any():
                                    pass  # Blok üretimini ürün adı ile daha iyi belirleyebiliriz

                            # 3. ÖNCELİK: Malzeme alanı
                            u_malz = str(urun_malzeme).lower()
                            if 'reçine' in u_malz or 'recine' in u_malz:
                                return 'REÇİNE'
                            if 'pmma' in u_malz:
                                return 'PMMA'
                            if 'zirkon' in u_malz or 'zircon' in u_malz:
                                return 'ZİRKONYUM'
                            if 'titan' in u_malz:
                                return 'TİTANYUM'

                            # 4. ÖNCELİK: Ürün adı
                            u_adi = str(urun_adi).lower()
                            if 'frez' in u_adi:
                                return 'FREZ'
                            if 'reçine' in u_adi or 'recine' in u_adi or 'geçici reçine' in u_adi or 'model reçine' in u_adi:
                                return 'REÇİNE'
                            if 'pmma' in u_adi:
                                return 'PMMA'
                            if 'zirkon' in u_adi or 'zircon' in u_adi:
                                return 'ZİRKONYUM'
                            if 'titan' in u_adi:
                                return 'TİTANYUM'

                            # 5. ÖNCELİK: İş türü (yapılan iş)
                            isler = isler_serisi.astype(str).str.lower()
                            if isler.str.contains('zirkon|zircon').any():
                                return 'ZİRKONYUM'
                            if isler.str.contains('reçine|recine').any():
                                return 'REÇİNE'
                            if isler.str.contains('pmma').any():
                                return 'PMMA'
                            if isler.str.contains('titan').any():
                                return 'TİTANYUM'

                            return 'DİĞER'

                        for kod in essiz_kodlar:
                            df_urun = df_arsiv[df_arsiv['stok_kodu'] == kod]
                            ilk_kayit = df_urun.iloc[-1] 
                            son_kayit = df_urun.iloc[0]
                            
                            urun_adi = son_kayit['urun_adi']
                            durum = son_kayit['durum']
                            durum_metin = "Aktif" if durum == 'Aktif' else "Pasif"
                            
                            toplam_uye = pd.to_numeric(df_urun[df_urun['islem_turu'].str.contains('Üretim')]['miktar_veya_uye'], errors='coerce').sum()
                            toplam_dk = df_urun['harcanan_dk'].sum()
                            
                            pasif_nedeni = "-"
                            arsiv_kayitlari = df_urun[~df_urun['islem_turu'].str.contains('Üretim')]
                            if not arsiv_kayitlari.empty:
                                pasif_nedeni = f"{arsiv_kayitlari.iloc[0]['islem_turu']} - {arsiv_kayitlari.iloc[0]['aciklama']}"
                                
                            urun_malzeme = stok_malzeme_map.get(kod, "")
                            urun_kategori = stok_kategori_map.get(kod, "")
                            kategori = kategori_belirle(urun_adi, df_urun['yapilan_is'], urun_malzeme, urun_kategori, df_urun['islem_turu'])
                            liste_verileri.append({
                                "Stok Kodu": kod,
                                "Ürün Adı": urun_adi,
                                "Toplam Üretilen": int(toplam_uye),
                                "Çalışma (Dk)": int(toplam_dk) if 'frez' in str(urun_adi).lower() or toplam_dk > 0 else "-",
                                "Durum": durum_metin,
                                "Pasif Nedeni": pasif_nedeni,
                                "İlk İşlem": ilk_kayit['tarih'][:10],
                                "Kategori": kategori
                            })

                        # Reçine miktar: isler tablosundaki Recine_Sarfiyati JSON'undan tuketim_gr okunuyor
                        # Bu hem eski kayıtlar hem de yeni kayıtlar için doğru değeri verir.
                        # Hesaplama: Model Biri = Adet * Model_başı_gr | Üye Birimi = Adet * Üye_başı_gr
                        recine_miktar_map = {}   # {malzeme_kodu: toplam_gr}
                        recine_adet_map   = {}   # {malzeme_kodu: toplam_adet}
                        recine_birim_map  = {}   # {malzeme_kodu: birim_basi_gr (ort)}
                        try:
                            import json as _json
                            recine_is_rows = c.execute(
                                "SELECT u.malzeme_kodu, i.Recine_Sarfiyati "
                                "FROM uretim_loglari u "
                                "JOIN isler i ON u.is_id = i.id "
                                "WHERE u.malzeme_turu = 'Re\u00e7ine'"
                            ).fetchall()
                            for r_kod_j, r_sarf_j in recine_is_rows:
                                if not r_sarf_j:
                                    continue
                                try:
                                    data = r_sarf_j if isinstance(r_sarf_j, dict) else _json.loads(str(r_sarf_j))
                                    tuketim_gr = float(data.get('tuketim_gr', 0))
                                    miktar     = float(data.get('miktar', 0))
                                    recine_miktar_map[r_kod_j] = recine_miktar_map.get(r_kod_j, 0.0) + tuketim_gr
                                    recine_adet_map[r_kod_j]   = recine_adet_map.get(r_kod_j, 0.0)   + miktar
                                except:
                                    pass
                        except:
                            pass
                        # Adet başı gr = toplam_gr / toplam_adet
                        recine_adet_basi_gr = {
                            k: round(recine_miktar_map[k] / recine_adet_map[k], 3)
                            for k in recine_miktar_map
                            if recine_adet_map.get(k, 0) > 0
                        }

                        for lv in liste_verileri:
                            lv['Kullanılan Miktar (gr)'] = round(recine_miktar_map.get(lv['Stok Kodu'], 0.0), 2)

                        df_liste_full = pd.DataFrame(liste_verileri, columns=["Stok Kodu", "Ürün Adı", "Toplam Üretilen", "Çalışma (Dk)", "Durum", "Pasif Nedeni", "İlk İşlem", "Kategori", "Kullanılan Miktar (gr)"])
                        kategori_map = dict(zip(df_liste_full["Stok Kodu"], df_liste_full["Kategori"]))
                        df_arsiv['Kategori'] = df_arsiv['stok_kodu'].map(kategori_map)

                        def color_durum_liste(val):
                            if val == "Aktif": return 'color: #34d399; font-weight:bold;'
                            elif val == "Pasif": return 'color: #f87171; font-weight:bold;'
                            return ''

                        kategoriler = ["ZİRKONYUM", "PMMA", "TİTANYUM", "FREZ", "REÇİNE", "DİĞER"]
                        sekmeler = st.tabs(kategoriler)
                        
                        for i, kategori_adi in enumerate(kategoriler):
                            with sekmeler[i]:
                                df_arsiv_alt = df_arsiv[df_arsiv['Kategori'] == kategori_adi]
                                if kategori_adi == "REÇİNE":
                                    df_liste_alt = df_liste_full[df_liste_full['Kategori'] == kategori_adi].drop(columns=['Kategori'])
                                else:
                                    df_liste_alt = df_liste_full[df_liste_full['Kategori'] == kategori_adi].drop(columns=['Kategori', 'Kullanılan Miktar (gr)'])
                                
                                if df_arsiv_alt.empty:
                                    st.info(f"{kategori_adi} kategorisinde malzeme bulunmamaktadır.")
                                    continue
                                
                                # Dashboard Gösterimi
                                st.markdown("##### 📊 Kategori Performans Özeti")
                                
                                if kategori_adi in ["ZİRKONYUM", "PMMA", "TİTANYUM", "DİĞER"]:
                                    df_blok_uretim = df_arsiv_alt[df_arsiv_alt['islem_turu'] == 'Üretim (Blok)']
                                    toplam_blok_uye = pd.to_numeric(df_blok_uretim['miktar_veya_uye'], errors='coerce').sum()
                                    toplam_essiz_blok = df_blok_uretim['stok_kodu'].nunique()
                                    ort_blok_verimi = round(toplam_blok_uye / toplam_essiz_blok, 1) if toplam_essiz_blok > 0 else 0
                                    
                                    m1, m2 = st.columns(2)
                                    m1.metric("Toplam Üretilen Üye (Blok)", f"{int(toplam_blok_uye)}")
                                    m2.metric("Blok Başı Ortalama Verim", f"{ort_blok_verimi} Üye")
                                
                                elif kategori_adi == "REÇİNE":
                                    # toplam_gr ve adet hesaplamak için onceden hazirladigimiz map'leri kullan
                                    toplam_gr      = sum(recine_miktar_map.values())
                                    toplam_kayit   = sum(1 for v in recine_adet_map.values() if v > 0)
                                    toplam_tur     = len([k for k in recine_miktar_map if recine_miktar_map[k] > 0])
                                    toplam_adet    = sum(recine_adet_map.values())
                                    ort_adet_basi  = round(toplam_gr / toplam_adet, 2) if toplam_adet > 0 else 0

                                    r1, r2, r3, r4 = st.columns(4)
                                    r1.metric("🟢 Toplam Kullanım", f"{toplam_gr:,.2f} gr")
                                    r2.metric("📦 Toplam Adet", f"{int(toplam_adet)}")
                                    r3.metric("🧪 Farklı Reçine Türü", f"{toplam_tur}")
                                    r4.metric("⚖️ Adet Başı Ort.", f"{ort_adet_basi} gr")

                                    if recine_miktar_map:
                                        st.markdown("###### 🧪 Reçine Türlerine Göre Tüketim")
                                        # Her reçine kodu için adini bul
                                        recine_tur_satirlar = []
                                        for r_kod_d, r_toplam_gr in recine_miktar_map.items():
                                            r_adet   = recine_adet_map.get(r_kod_d, 0)
                                            r_ab_gr  = recine_adet_basi_gr.get(r_kod_d, 0)
                                            # isim: stok_malzeme_map yoksa df_arsiv'den bul
                                            r_adi_d  = df_arsiv_alt[df_arsiv_alt['stok_kodu'] == r_kod_d]['urun_adi'].iloc[0] if not df_arsiv_alt[df_arsiv_alt['stok_kodu'] == r_kod_d].empty else r_kod_d
                                            recine_tur_satirlar.append({
                                                'Reçine Adı':         r_adi_d,
                                                'Toplam Tüketim (gr)': round(r_toplam_gr, 2),
                                                'Toplam Adet':          int(r_adet),
                                                'Adet Başı Ort. (gr)':  r_ab_gr
                                            })
                                        if recine_tur_satirlar:
                                            r_cols_n = st.columns(min(4, max(1, len(recine_tur_satirlar))))
                                            for ri, rrow in enumerate(recine_tur_satirlar):
                                                r_cols_n[ri % len(r_cols_n)].metric(
                                                    rrow['Reçine Adı'],
                                                    f"{rrow['Adet Başı Ort. (gr)']} gr/adet",
                                                    f"Toplam: {rrow['Toplam Tüketim (gr)']:,.2f} gr | {rrow['Toplam Adet']} adet"
                                                )
                                    else:
                                        st.caption("Henüz reçine üretim verisi yok.")
                                
                                st.markdown("---")
                                st.markdown("##### 🗂️ Tüm Malzemeler (Özet Liste)")
                                if not df_liste_alt.empty:
                                    st.dataframe(df_liste_alt.style.map(color_durum_liste, subset=["Durum"]), hide_index=True, use_container_width=True)
                                else:
                                    st.dataframe(df_liste_alt, hide_index=True, use_container_width=True)
                                    
                                st.markdown("---")
                                st.markdown("<h5 style='color:#38bdf8;margin-bottom:8px;'>⚡ Arşiv İşlemleri & Detay Kartı</h5>", unsafe_allow_html=True)
                                
                                islem_secenekleri = [f"{r['Stok Kodu']} | {r['Ürün Adı']} - {r['Durum']}" for _, r in df_liste_alt.iterrows()]
                                secilen_arsiv_urun = st.selectbox(
                                    "🔍 Detaylı İncelemek veya İşlem Yapmak İçin Ürün Seçin", 
                                    ["— Seçiniz —"] + islem_secenekleri,
                                    key=f"arsiv_islem_urun_{kategori_adi}"
                                )
                                
                                if secilen_arsiv_urun != "— Seçiniz —":
                                    secilen_kod = secilen_arsiv_urun.split("|")[0].strip()
                                    secilen_durum = secilen_arsiv_urun.split("-")[-1].strip()
                                    
                                    st.markdown(f"#### 🏷️ Malzeme Detay Kartı: {secilen_kod}")
                                    df_urun_detay = df_arsiv_alt[df_arsiv_alt['stok_kodu'] == secilen_kod].copy()
                                    
                                    if not df_urun_detay.empty:
                                        with st.container(border=True):
                                            mc1, mc2, mc3 = st.columns(3)
                                            mc1.metric("Stok Kodu", secilen_kod)
                                            mc2.metric("Ürün Adı", str(df_urun_detay.iloc[0]['urun_adi']))
                                            mc3.metric("Güncel Durum", secilen_durum)
                                            
                                            t1, t2 = st.tabs(["🦷 Hasta / Kullanım Geçmişi", "📦 Stok Hareketleri"])
                                            
                                            with t1:
                                                df_hasta = df_urun_detay[df_urun_detay['islem_turu'].str.contains('Üretim')].copy()
                                                if not df_hasta.empty:
                                                    df_hasta_show = df_hasta[['tarih', 'aciklama', 'yapilan_is', 'miktar_veya_uye', 'sistem_kullanici']].rename(columns={'tarih': 'Tarih', 'aciklama': 'Hasta / İş Adı', 'yapilan_is': 'Yapılan İş', 'miktar_veya_uye': 'Miktar/Dk', 'sistem_kullanici': 'Kullanıcı'})
                                                    st.dataframe(df_hasta_show, hide_index=True, use_container_width=True)
                                                else:
                                                    st.info("Bu malzeme ile henüz bir üretim kaydı bulunmamaktadır.")
                                                    
                                            with t2:
                                                df_stok = df_urun_detay[~df_urun_detay['islem_turu'].str.contains('Üretim')].copy()
                                                if not df_stok.empty:
                                                    df_stok_show = df_stok[['tarih', 'islem_turu', 'aciklama', 'sistem_kullanici']].rename(columns={'tarih': 'Tarih', 'islem_turu': 'İşlem', 'aciklama': 'Açıklama', 'sistem_kullanici': 'Kullanıcı'})
                                                    st.dataframe(df_stok_show, hide_index=True, use_container_width=True)
                                                else:
                                                    st.info("Stok hareket kaydı bulunmamaktadır.")
                                                    
                                    st.markdown("##### ⚡ Hızlı İşlemler")
                                    c1, c2 = st.columns(2)
                                    with c1:
                                        if secilen_durum == "Pasif":
                                            if st.button("⏪ Arşivden Çıkar (Aktife Al)", use_container_width=True, key=f"btn_aktif_{secilen_kod}"):
                                                c.execute("DELETE FROM malzeme_arsivi WHERE Urun_Kodu=?", (secilen_kod,))
                                                c.execute("UPDATE cam_bloklar SET Durum='Yarım' WHERE Blok_Kodu=?", (secilen_kod,))
                                                c.execute("UPDATE aktif_frezler SET durum='Aktif' WHERE frez_kod=?", (secilen_kod,))
                                                conn.commit()
                                                st.success(f"{secilen_kod} başarıyla aktif hale getirildi.")
                                    with c2:
                                        if st.button("🗑️ Kalıcı Olarak Sil", use_container_width=True, key=f"btn_sil_{secilen_kod}"):
                                            c.execute("DELETE FROM malzeme_arsivi WHERE Urun_Kodu=?", (secilen_kod,))
                                            c.execute("DELETE FROM uretim_loglari WHERE malzeme_kodu=?", (secilen_kod,))
                                            conn.commit()
                                            st.success(f"{secilen_kod} arşivden ve sistemden tamamen silindi.")
                                            st.rerun()


                        # =========================================================
                        # B PLANI: MANUEL VERI DUZELTME PANELI
                        # =========================================================
                        st.markdown("---")
                        kullanici_rol = st.session_state.get("kullanici_rolu", "")
                        if kullanici_rol in ["Admin", "Yönetici", "Yetkili"]:
                            with st.expander("B Plani - Manuel Uretim Kaydi Duzeltme", expanded=False):
                                st.warning("Bu panel yalnizca yetkili kullanicilar icindir. Yanlis silme veya degisiklik geri alinamaz!")
                                try:
                                    df_loglar = pd.read_sql('SELECT u.id, u.is_id, u.is_adi, u.malzeme_turu, u.malzeme_kodu, u.malzeme_adi, u.uye_sayisi, u.tarih FROM uretim_loglari u ORDER BY u.tarih DESC LIMIT 100', conn)
                                    df_loglar.columns = df_loglar.columns.str.lower()
                                    if df_loglar.empty:
                                        st.info("Duzeltilecek uretim kaydi bulunamadi.")
                                    else:
                                        st.markdown("**Son 100 Uretim Kaydi (Malzeme Log lari)**")
                                        df_loglar_show = df_loglar[["tarih","is_adi","malzeme_turu","malzeme_kodu","malzeme_adi","uye_sayisi"]].rename(columns={
                                            "tarih":"Tarih","is_adi":"Is/Hasta","malzeme_turu":"Tur",
                                            "malzeme_kodu":"Malzeme Kodu","malzeme_adi":"Malzeme Adi","uye_sayisi":"Miktar/Uye"
                                        })
                                        st.dataframe(df_loglar_show, hide_index=True, use_container_width=True)
                                        st.markdown("#### Hatali Kaydi Sec ve Duzelt")
                                        log_secenekleri = [f"ID:{r['id']} | {r['tarih']} | {r['is_adi']} | {r['malzeme_kodu']} ({r['malzeme_turu']}, {r['uye_sayisi']} uye)"
                                                          for _, r in df_loglar.iterrows()]
                                        secilen_log_str = st.selectbox("Duzeltilecek Kaydi Secin", ["- Seciniz -"] + log_secenekleri, key="b_plan_log")
                                        if secilen_log_str != "- Seciniz -":
                                            log_id = int(secilen_log_str.split("|")[0].replace("ID:","").strip())
                                            log_row = df_loglar[df_loglar["id"] == log_id].iloc[0]
                                            st.info(f"Secilen kayit: **{log_row['malzeme_kodu']}** - {log_row['is_adi']} - {log_row['uye_sayisi']} uye - {log_row['tarih']}")
                                            bc1, bc2 = st.columns(2)
                                            with bc1:
                                                if log_row["malzeme_turu"] == "Blok":
                                                    iade_et = st.checkbox("Bloga uyeleri iade et (Kalan_Uye geri yukle)", value=True, key="b_iade")
                                                else:
                                                    iade_et = False
                                                    st.caption("(Frez kayitlari icin otomatik iade yapilmaz)")
                                            with bc2:
                                                onay_metni = st.text_input("Onaylamak icin 'ONAYLA' yazin:", key="b_onay")
                                            if st.button("Bu Kaydi Sil (Geri Alinamaz)", type="primary", key="b_sil") and onay_metni == "ONAYLA":
                                                if iade_et and log_row["malzeme_turu"] == "Blok":
                                                    c.execute("UPDATE cam_bloklar SET Kalan_Uye = Kalan_Uye + ?, Durum='Yarim' WHERE Blok_Kodu=?",
                                                              (int(log_row["uye_sayisi"]), str(log_row["malzeme_kodu"])))
                                                c.execute("DELETE FROM uretim_loglari WHERE id=?", (log_id,))
                                                c.execute("INSERT INTO malzeme_arsivi (Tarih, Urun_Kodu, Urun_Adi, Miktar, Islem_Turu, Aciklama, Kullanici) VALUES (?,?,?,?,?,?,?)",
                                                          (datetime.now().strftime("%Y-%m-%d %H:%M"),
                                                           str(log_row["malzeme_kodu"]), str(log_row["malzeme_adi"]),
                                                           float(log_row["uye_sayisi"]), "Manuel Duzeltme (B Plani)",
                                                           f"Log ID {log_id} silindi. Is: {log_row['is_adi']}. Yetkili: {st.session_state.get('kullanici_adi','?')}",
                                                           str(st.session_state.get("kullanici_adi","Sistem"))))
                                                conn.commit()
                                                st.success(f"Log kaydi silindi. Blok iade: {'Evet' if iade_et else 'Hayir'}. Audit kaydi dusuldu.")
                                            elif onay_metni and onay_metni != "ONAYLA":
                                                st.error("Onay metni hatali. Tam olarak 'ONAYLA' yaziniz.")
                                except Exception as log_e:
                                    st.error(f"Duzeltme paneli yuklenemedi: {log_e}")
                        else:
                            st.caption("Veri duzeltme paneli yalnizca Admin ve Yetkili kullanicilara aciktir.")

                except Exception as e:
                    st.error(f"Tablo yüklenirken hata oluştu: {e}")
        with t3:
            st.markdown("<h4 style='color: #FFFFFF;'>📥 Toplu Stok Aktarımı</h4>", unsafe_allow_html=True)
            st.info("💡 İpucu: Excel dosyanıza 'KATEGORİ' sütunu eklerseniz, ürünleri doğrudan 'Demirbaşlar' veya diğer kategorilere kaydedebilirsiniz.")
            yuklenen_dosya = st.file_uploader("Dosya Sürükle (.xlsx, .csv)", type=["csv", "xlsx"])
            if yuklenen_dosya:
                if st.button("🚀 Sisteme Aktar", key="p-StokAktar"):
                    try:
                        df_toplu = pd.read_csv(yuklenen_dosya, sep=';') if yuklenen_dosya.name.endswith('.csv') else pd.read_excel(yuklenen_dosya)
                        if len(df_toplu.columns) < 2 and yuklenen_dosya.name.endswith('.csv'): df_toplu = pd.read_csv(yuklenen_dosya, sep=',')
                        
                        sutunlar = [str(col).strip().upper() for col in df_toplu.columns]
                        df_toplu.columns = sutunlar
                        
                        kod_kolonu = next((col for col in sutunlar if any(x in col for x in ["KOD", "CODE", "NO", "NUM"])), sutunlar[0] if len(sutunlar) > 0 else None)
                        adi_kolonu = next((col for col in sutunlar if any(x in col for x in ["AD", "ÜRÜN", "URUN", "MALZEME", "TANIM", "DESC", "NAME", "AÇIKLAMA", "ACIKLAMA"]) and col != kod_kolonu), sutunlar[1] if len(sutunlar) > 1 else kod_kolonu)
                        fiyat_kolonu = next((col for col in sutunlar if "FİYAT" in col or "FIYAT" in col or "PRICE" in col or "TUTAR" in col), None)
                        kat_kolonu = next((col for col in sutunlar if "KATEGORİ" in col or "KATEGORI" in col or "CAT" in col), None)
                        
                        eklenen = 0
                        for _, row in df_toplu.iterrows():
                            if not kod_kolonu: continue
                            
                            kodu = str(row.get(kod_kolonu, ""))
                            adi = str(row.get(adi_kolonu, ""))
                            
                            # Kategori hücresini oku, yoksa 'Sarf Malzeme' ata
                            kategorisi = str(row.get(kat_kolonu, "Sarf Malzeme")) if kat_kolonu else "Sarf Malzeme"
                            if kategorisi == "nan" or not kategorisi.strip(): kategorisi = "Sarf Malzeme"
                            
                            try: fiyati = float(row.get(fiyat_kolonu, 0.0)) if fiyat_kolonu else 0.0
                            except: fiyati = 0.0
                            
                            if kodu.strip() != "" and kodu != "nan":
                                mevcut_mu = c.execute("SELECT id FROM stok WHERE Urun_Kodu=?", (kodu,)).fetchone()
                                if not mevcut_mu:
                                    c.execute("INSERT INTO stok (Urun_Kodu, Urun_Adi, Kategori, Mevcut_Miktar, Birim, Kritik_Sinir, Satis_Fiyati, Durum, Guncelleme_Tarihi) VALUES (?,?,?,?,?,?,?,'Aktif',?)", 
                                              (kodu, adi, kategorisi, 0.0, "Adet", 5.0, fiyati, datetime.now().strftime('%Y-%m-%d %H:%M')))
                                    eklenen += 1
                        conn.commit()
                        if eklenen > 0: st.success(f"✅ {eklenen} yeni ürün/demirbaş başarıyla eklendi!"); st.balloons()
                        else: st.warning("Yeni ürün bulunamadı veya tüm ürünler zaten kayıtlı.")
                    except Exception as e: st.error(f"Hata oluştu: {e}")

        with t4:
            st.markdown("<h4 style='color: #FFFFFF;'>🤖 Akıllı Tedarik ve Yapay Zeka Asistanı</h4>", unsafe_allow_html=True)
            df_k = pd.read_sql("SELECT Urun_Kodu, Urun_Adi, Kategori, Mevcut_Miktar, Kritik_Sinir, Birim FROM stok WHERE Durum='Aktif'", conn)
            if not df_k.empty:
                df_kritik = df_k[df_k['Mevcut_Miktar'] <= df_k['Kritik_Sinir']]
                df_uyari = df_k[(df_k['Mevcut_Miktar'] > df_k['Kritik_Sinir']) & (df_k['Mevcut_Miktar'] <= df_k['Kritik_Sinir'] * 1.5)]
                df_guvenli = df_k[df_k['Mevcut_Miktar'] > df_k['Kritik_Sinir'] * 1.5]
                
                k1, k2, k3 = st.columns(3)
                k1.markdown(f"<div class='glass-card' style='text-align:center; border-color: rgba(248, 113, 113, 0.5);'><span style='color:#FFFFFF;'>🔴 Kritik (Acil Sipariş)</span><br><span class='neon-text-red' style='font-size:24px;'>{len(df_kritik)}</span></div>", unsafe_allow_html=True)
                k2.markdown(f"<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>🟠 Azalan (Tetiktekiler)</span><br><span style='color:#FB923C; font-size:24px; font-weight:bold;'>{len(df_uyari)}</span></div>", unsafe_allow_html=True)
                k3.markdown(f"<div class='glass-card' style='text-align:center; border-color: rgba(52, 211, 153, 0.5);'><span style='color:#FFFFFF;'>🟢 Güvenli Stok</span><br><span class='neon-text-green' style='font-size:24px;'>{len(df_guvenli)}</span></div>", unsafe_allow_html=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                if not df_kritik.empty:
                    st.dataframe(df_kritik.rename(columns={"Urun_Kodu":"Kod", "Urun_Adi":"Ürün", "Mevcut_Miktar":"Kalan", "Kritik_Sinir":"Sınır"}).style.format({"Kalan":"{:.0f}","Sınır":"{:.0f}"}), hide_index=True, use_container_width=True)
                    siparis_metni = "Merhaba, laboratuvarımız için acil sipariş listemiz aşağıdadır:\n\n"
                    for _, row in df_kritik.iterrows():
                        onerilen_siparis = max((row['Kritik_Sinir'] * 2) - row['Mevcut_Miktar'], 1)
                        siparis_metni += f"▫️ {row['Urun_Kodu']} - {row['Urun_Adi']} ({onerilen_siparis:.0f} {row['Birim']} lazım)\n"
                    siparis_metni += "\nTeşekkürler, iyi çalışmalar."
                    wp_url_siparis = f"https://wa.me/?text={urllib.parse.quote(siparis_metni)}"
                    st.markdown(f"""<a href="{wp_url_siparis}" target="_blank" class="wp-btn">🟢 AI Tarafından Oluşturulan Sipariş Listesini Tedarikçiye WhatsApp'tan Gönder</a>""", unsafe_allow_html=True)


    elif sayfa == "🏭 Tedarikçi Yönetimi":
        banner_olustur("🏭", "Tedarikçi ve Satın Alma Yönetimi", "Laboratuvarınızın malzeme tedarikçilerini yönetin ve satın alma geçmişini takip edin.")
        
        t1, t2, t3 = st.tabs(["📋 Tedarikçi Listesi & Bakiyeler", "➕ Yeni Tedarikçi Ekle", "🛒 Satın Alma Geçmişi"])
        
        with t1:
            st.markdown("### Mevcut Tedarikçiler")
            try:
                df_ted = pd.read_sql("SELECT id, Firma_Unvani, Yetkili_Kisi, Telefon, Email, Kategori, Bakiye, IBAN, Vergi_Dairesi, Vergi_No, Adres FROM tedarikciler WHERE Durum='Aktif' ORDER BY Firma_Unvani ASC", conn)
                
                if not df_ted.empty:
                    df_gorsel = df_ted.copy()
                    
                    # SIRA NUMARASI VE OTOMATİK TEDARİKÇİ NUMARASI EKLENMESİ
                    df_gorsel['Sıra'] = range(1, len(df_gorsel) + 1)
                    df_gorsel['Tedarikçi No'] = df_gorsel['id'].apply(lambda x: f"TED-{str(x).zfill(4)}")
                    
                    # Kolon sırasını ve başlıklarını ayarlama
                    df_gorsel = df_gorsel[['Sıra', 'Tedarikçi No', 'Firma_Unvani', 'Yetkili_Kisi', 'Telefon', 'Email', 'Kategori', 'Bakiye', 'IBAN', 'Vergi_Dairesi', 'Vergi_No', 'Adres']]
                    df_gorsel.columns = ["Sıra", "Tedarikçi No", "Firma Ünvanı", "Yetkili Kişi", "Telefon", "E-Posta", "Kategori", "Bakiye (TL)", "IBAN", "Vergi Dairesi", "Vergi No", "Adres"]
                    
                    st.dataframe(df_gorsel.style.format({"Bakiye (TL)": "{:,.2f}"}), hide_index=True, use_container_width=True)
                    
                    if rol in ["Admin", "Yönetici"]:
                        st.markdown("---")
                        st.markdown("#### ⚡ Tedarikçi İşlemleri")
                        secilen_ted = st.selectbox("İşlem Yapılacak Tedarikçi", ["-- Seçiniz --"] + df_ted['Firma_Unvani'].tolist())
                        
                        if secilen_ted != "-- Seçiniz --":
                            ted_id = df_ted[df_ted['Firma_Unvani'] == secilen_ted]['id'].values[0]
                            mevcut = df_ted[df_ted['Firma_Unvani'] == secilen_ted].iloc[0]
                            
                            c1, c2 = st.columns([2, 1])
                            with c1:
                                with st.form("ted_guncelle"):
                                    st.subheader("Bilgileri Güncelle")
                                    y_firma = st.text_input("Firma Ünvanı *", value=mevcut['Firma_Unvani'])
                                    
                                    g_c1, g_c2 = st.columns(2)
                                    y_yetkili = g_c1.text_input("Yetkili Kişi", value=mevcut['Yetkili_Kisi'])
                                    y_tel = g_c2.text_input("Telefon", value=mevcut['Telefon'])
                                    y_email = g_c1.text_input("E-Posta", value=mevcut['Email'])
                                    y_bakiye = g_c2.number_input("Güncel Bakiye (TL)", value=float(mevcut['Bakiye']), step=100.0)
                                    
                                    kat_index = 0
                                    kat_listesi = ["Zirkonyum", "Metal", "Sarf Malzeme", "Genel", "Diğer"]
                                    if mevcut['Kategori'] in kat_listesi: kat_index = kat_listesi.index(mevcut['Kategori'])
                                    y_kat = g_c1.selectbox("Kategori", kat_listesi, index=kat_index)
                                    
                                    y_iban = g_c2.text_input("IBAN", value=mevcut['IBAN'])
                                    y_vd = g_c1.text_input("Vergi Dairesi", value=mevcut['Vergi_Dairesi'])
                                    y_vn = g_c2.text_input("Vergi No", value=mevcut['Vergi_No'])
                                    y_adres = st.text_area("Adres", value=mevcut['Adres'])
                                    
                                    if st.form_submit_button("💾 Kaydet", use_container_width=True):
                                        c.execute("UPDATE tedarikciler SET Firma_Unvani=?, Yetkili_Kisi=?, Telefon=?, Email=?, Kategori=?, Bakiye=?, IBAN=?, Vergi_Dairesi=?, Vergi_No=?, Adres=? WHERE id=?", 
                                                 (y_firma, y_yetkili, y_tel, y_email, y_kat, y_bakiye, y_iban, y_vd, y_vn, y_adres, int(ted_id)))
                                        conn.commit(); st.success("Güncellendi!"); st.rerun()
                            with c2:
                                st.warning("Tedarikçiyi Sil / Arşive Kaldır")
                                if st.button("🗑️ Arşive Kaldır", type="primary", use_container_width=True):
                                    c.execute("UPDATE tedarikciler SET Durum='Pasif' WHERE id=?", (int(ted_id),))
                                    conn.commit(); st.success("Arşive kaldırıldı!"); st.rerun()
                else:
                    st.info("Sistemde henüz kayıtlı aktif bir tedarikçi bulunmuyor.")
            except Exception as e:
                st.error("Veritabanında tedarikçiler tablosu henüz oluşmamış. Cloud Run ilk kez yeniden başlatıldığında tablo otomatik kurulacaktır.")
                
        with t2:
            if rol in ["Admin", "Yönetici"]:
                st.markdown("### Yeni Tedarikçi Tanımla")
                with st.form("yeni_tedarikci_ekle"):
                    n_firma = st.text_input("Firma Ünvanı *")
                    
                    c1, c2 = st.columns(2)
                    n_yetkili = c1.text_input("Yetkili Kişi")
                    n_tel = c2.text_input("Telefon")
                    n_email = c1.text_input("E-Posta")
                    n_iban = c2.text_input("IBAN", value="-")
                    n_vd = c1.text_input("Vergi Dairesi", value="-")
                    n_vn = c2.text_input("Vergi No", value="-")
                    n_kat = c1.selectbox("Kategori", ["Zirkonyum", "Metal", "Sarf Malzeme", "Genel", "Diğer"])
                    n_bakiye = c2.number_input("Açılış Bakiyesi (TL)", value=0.0, step=100.0)
                    n_adres = st.text_area("Adres", value="-")
                    
                    if st.form_submit_button("➕ Tedarikçiyi Kaydet", type="primary"):
                        if n_firma.strip():
                            try:
                                c.execute("INSERT INTO tedarikciler (Firma_Unvani, Yetkili_Kisi, Telefon, Email, Kategori, Bakiye, IBAN, Vergi_Dairesi, Vergi_No, Adres) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                         (n_firma, n_yetkili, n_tel, n_email, n_kat, n_bakiye, n_iban, n_vd, n_vn, n_adres))
                                conn.commit(); st.success("Yeni tedarikçi başarıyla eklendi!"); st.rerun()
                            except Exception as e:
                                st.error(f"Ekleme hatası: {e}")
                        else:
                            st.warning("Firma Ünvanı zorunludur!")
            else:
                st.error("Bu alanı sadece Admin yetkisine sahip kullanıcılar görüntüleyebilir ve işlem yapabilir.")
                
        with t3:
            st.info("Satın Alma Geçmişi modülü yapım aşamasındadır. Burada ilerleyen güncellemelerde oluşturulan satın alma siparişleri ve faturaları listelenecektir.")

    elif sayfa == "💰 Finans & Analitik":
        banner_olustur("💰", "Finans ve Analitik Merkezi v3", "Tahsilatları girin, cari ekstreleri çıkarın ve laboratuvarınızın kârlılığını analiz edin.")
        
        euro_kuru_anlik = guncel_euro_kuru_getir()
        st.info(f"💶 **Sistemdeki Güncel Euro Kuru:** {euro_kuru_anlik:,.2f} TL (TCMB Canlı Kur)")
        
        try:
            klinik_liste = c.execute("SELECT Klinik_Unvani FROM cariler WHERE Durum='Aktif'").fetchall()
            klinikler = [k[0] for k in klinik_liste]
        except:
            klinikler = []

        tab_fiyat, tab_ekstre_arsiv, tab_finans_veri = st.tabs(["🏷️ İş Fiyatlandırma", "📂 Hesap Ekstreleri", "📊 Finans Veri Tabloları"])

        with tab_fiyat:
            st.markdown("#### 🏷️ İş Fiyatlandırma")
            st.caption("İş Akışı'nda oluşturulan ve henüz fiyatlandırılmamış (Tutarı 0 olan) veya fiyatı güncellenmek istenen reçetelerin fiyatlarını bu tablodan belirleyebilirsiniz. Belirlenen tutarlar otomatik olarak kliniğin borç bakiyesine yansıtılır.")
            
            if klinikler:
                f_klinik = st.selectbox("Filtrelenecek Klinik", ["Tümü"] + klinikler, key="fiyat_klinik_secim")
                
                query_fiyat = """SELECT id, Teslim_Tarihi, Klinik_Unvani, Hasta_Adi, Hasta_Kodu, Is_Turu, Adet, Tutar_TL, Fatura_Tarihi, Iskonto, Bakiye_Durumu FROM isler i WHERE NOT EXISTS (SELECT 1 FROM hesap_ekstreleri h JOIN faturalar f ON h.id = f.Ekstre_ID WHERE i.Klinik_Unvani = h.Klinik_Unvani AND i.Tarih >= h.Baslangic_Tarihi AND i.Tarih <= h.Bitis_Tarihi || ' 23:59:59')"""
                if f_klinik != "Tümü":
                    df_fiyat = pd.read_sql(f"{query_fiyat} AND i.Klinik_Unvani='{f_klinik}' ORDER BY i.id DESC LIMIT 200", conn)
                else:
                    df_fiyat = pd.read_sql(f"{query_fiyat} ORDER BY i.id DESC LIMIT 300", conn)
                    
                if not df_fiyat.empty:
                    if 'adet' in df_fiyat.columns:
                        df_fiyat = df_fiyat.rename(columns={"adet": "Adet"})
                    if 'teslim_tarihi' in df_fiyat.columns:
                        df_fiyat = df_fiyat.rename(columns={"teslim_tarihi": "Teslim_Tarihi"})
                    if 'fatura_tarihi' in df_fiyat.columns:
                        df_fiyat = df_fiyat.rename(columns={"fatura_tarihi": "Fatura_Tarihi"})
                    if 'iskonto' in df_fiyat.columns:
                        df_fiyat = df_fiyat.rename(columns={"iskonto": "Iskonto"})
                    if 'bakiye_durumu' in df_fiyat.columns:
                        df_fiyat = df_fiyat.rename(columns={"bakiye_durumu": "Bakiye_Durumu"})
                        
                    df_fiyat = df_fiyat.rename(columns={
                        "Teslim_Tarihi": "TESLİM TARİHİ",
                        "Klinik_Unvani": "KLİNİK", 
                        "Hasta_Adi": "HASTA ADI", 
                        "Hasta_Kodu": "HASTA KODU",
                        "hasta_kodu": "HASTA KODU",
                        "Is_Turu": "İŞLEM TÜRÜ", 
                        "Adet": "ADET",
                        "Fatura_Tarihi": "FATURA TARİHİ",
                        "Iskonto": "İSKONTO",
                        "Bakiye_Durumu": "BAKİYE DURUMU"
                    })
                    
                    df_fiyat["FATURA TARİHİ"] = df_fiyat["FATURA TARİHİ"].fillna("-")
                    df_fiyat["İSKONTO"] = pd.to_numeric(df_fiyat["İSKONTO"], errors='coerce').fillna(0.0)

                    if 'ADET' in df_fiyat.columns:
                        df_fiyat["ADET"] = pd.to_numeric(df_fiyat["ADET"], errors='coerce').fillna(1).astype(int)
                    else:
                        df_fiyat["ADET"] = 1
                    
                    df_fiyat["Tutar_TL"] = pd.to_numeric(df_fiyat["Tutar_TL"], errors='coerce').fillna(0.0)
                    df_fiyat["ESKİ_TUTAR_TL"] = df_fiyat["Tutar_TL"]
                    
                    # Hizmet Fiyat Listesini Çek (Para birimi dahil)
                    fiyatlar_raw = c.execute("SELECT Hizmet_Adi, Fiyat, Para_Birimi FROM fiyat_listesi").fetchall()
                    # Sözlük yapısı: {'Zirkonyum': {'fiyat': 1500, 'birim': 'Euro'}}
                    fiyat_dict = {f[0]: {'fiyat': float(f[1] if f[1] is not None else 0.0), 'birim': str(f[2] if f[2] is not None else 'TL')} for f in fiyatlar_raw}
                    euro_kuru = guncel_euro_kuru_getir()
                    
                    def get_birim_fiyat(row):
                        if row["Tutar_TL"] > 0:
                            iskonto_orani = float(row.get("İSKONTO", 0.0))
                            carpan = 1 - (iskonto_orani / 100.0)
                            if carpan <= 0: carpan = 1.0
                            gercek_toplam_tutar = row["Tutar_TL"] / carpan
                            return round(gercek_toplam_tutar / row["ADET"], 2)
                        
                        # Eğer tutar 0 ise fiyat listesinden güncel kurla getir
                        hizmet = row["İŞLEM TÜRÜ"]
                        if hizmet in fiyat_dict:
                            h_fiyat = fiyat_dict[hizmet]['fiyat']
                            h_birim = fiyat_dict[hizmet]['birim']
                            if h_birim == "Euro":
                                return round(h_fiyat * euro_kuru, 2)
                            else:
                                return round(h_fiyat, 2)
                        return 0.0
                        
                    df_fiyat["B.FİYAT"] = df_fiyat.apply(get_birim_fiyat, axis=1)
                    df_fiyat["T.FİYAT"] = (df_fiyat["B.FİYAT"] * df_fiyat["ADET"]) * (1 - (df_fiyat["İSKONTO"] / 100.0))
                    df_fiyat.loc[df_fiyat["T.FİYAT"] < 0, "T.FİYAT"] = 0
                    
                    if "BAKİYE DURUMU" not in df_fiyat.columns:
                        df_fiyat["BAKİYE DURUMU"] = "Bekliyor"
                    df_fiyat["BAKİYE DURUMU"] = df_fiyat["BAKİYE DURUMU"].apply(lambda x: "✅ Aktarıldı" if str(x) == "Aktarıldı" else "⏳ Bekliyor")
                    
                    df_fiyat = df_fiyat.set_index("id")
                    
                    # İstenen sıra: S.NO - TARİH - KLİNİK - HASTA ADI - İŞLEM TÜRÜ - ADET - B.FİYAT - T.FİYAT - BAKİYE DURUMU
                    df_fiyat.insert(0, 'S.NO', range(1, len(df_fiyat) + 1))
                    df_fiyat = df_fiyat[["S.NO", "TESLİM TARİHİ", "KLİNİK", "HASTA ADI", "HASTA KODU", "İŞLEM TÜRÜ", "ADET", "FATURA TARİHİ", "İSKONTO", "B.FİYAT", "T.FİYAT", "BAKİYE DURUMU", "ESKİ_TUTAR_TL"]]
                    
                    st.caption("💡 İpucu: İşlemler (fatura tarihi, fiyat, iskonto) alanını açmak için tablodan bir satır seçiniz.")
                    
                    event_fiyat = st.dataframe(
                        df_fiyat.drop(columns=["ESKİ_TUTAR_TL"]), # Gizlemek için
                        hide_index=True, use_container_width=True,
                        on_select="rerun",
                        selection_mode="single-row",
                        key="fiyat_tablo"
                    )
                    
                    if event_fiyat and len(event_fiyat.selection.rows) > 0:
                        secili_idx = event_fiyat.selection.rows[0]
                        secili_kayit = df_fiyat.iloc[secili_idx]
                        
                        st.markdown(f"### ⚙️ İşlem Güncelle ({secili_kayit['HASTA ADI']} - {secili_kayit['İŞLEM TÜRÜ']})")
                        
                        col1, col2, col3, col4 = st.columns(4)
                        yeni_fatura = col1.text_input("Fatura Tarihi", value=secili_kayit["FATURA TARİHİ"], key="y_fat")
                        yeni_fiyat = col2.number_input("B.Fiyat (TL)", value=float(secili_kayit["B.FİYAT"]), min_value=0.0, step=10.0, key="y_fiy")
                        yeni_iskonto = col3.number_input("İskonto (%)", value=float(secili_kayit["İSKONTO"]), min_value=0.0, max_value=100.0, step=1.0, key="y_isk")
                        
                        yeni_t_fiyat = (yeni_fiyat * secili_kayit["ADET"]) * (1 - (yeni_iskonto / 100.0))
                        if yeni_t_fiyat < 0: yeni_t_fiyat = 0
                        col4.metric("Yeni Toplam Tutar", f"{yeni_t_fiyat:,.2f} TL")
                        
                        bakiye_durumu = secili_kayit.get("BAKİYE DURUMU", "⏳ Bekliyor")
                        aktarildi_mi = bakiye_durumu == "✅ Aktarıldı"
                        
                        col_btn1, col_btn2 = st.columns(2)
                        btn_guncelle = col_btn1.button("💾 Güncelle", use_container_width=True, disabled=aktarildi_mi)
                        btn_yansit = col_btn2.button("📊 Cari Bakiyeye Yansıt", type="primary", use_container_width=True, disabled=aktarildi_mi)

                        if aktarildi_mi:
                            st.success("✅ Bu işlem cari bakiyeye aktarılmıştır.")
                            btn_geri_cek = st.button("↩️ Geri Çek (Yeniden Fiyatlandırmak İçin)", use_container_width=True)
                            
                            if btn_geri_cek:
                                idx_db = secili_kayit.name
                                f_klinik_adi = secili_kayit["KLİNİK"]
                                eski_veritabani_tutar = secili_kayit["ESKİ_TUTAR_TL"]
                                
                                try: c.execute("UPDATE cariler SET Bakiye = Bakiye - ? WHERE Klinik_Unvani=?", (eski_veritabani_tutar, f_klinik_adi))
                                except: pass
                                
                                try: c.execute("UPDATE isler SET Bakiye_Durumu='Bekliyor' WHERE id=?", (int(idx_db),))
                                except: pass
                                conn.commit()
                                st.success("İşlem cari bakiyeden geri çekildi!")
                                st.rerun()

                        if btn_guncelle or btn_yansit:
                            eski_veritabani_tutar = secili_kayit["ESKİ_TUTAR_TL"]
                            eski_adet = secili_kayit["ADET"]
                            eski_fatura = str(secili_kayit["FATURA TARİHİ"])
                            eski_iskonto = float(secili_kayit["İSKONTO"])
                            idx_db = secili_kayit.name  # Since index is "id"

                            fatura_str = str(yeni_fatura)
                            isk_float = float(yeni_iskonto)

                            if (eski_veritabani_tutar != yeni_t_fiyat) or (eski_fatura != fatura_str) or (eski_iskonto != isk_float) or (float(secili_kayit["B.FİYAT"]) != yeni_fiyat) or btn_yansit:
                                f_klinik_adi = secili_kayit["KLİNİK"]
                                
                                c.execute("UPDATE isler SET Tutar_TL=?, Adet=?, Fatura_Tarihi=?, Iskonto=? WHERE id=?", (float(yeni_t_fiyat), int(eski_adet), fatura_str, float(isk_float), int(idx_db)))

                                if btn_yansit:
                                    try: c.execute("UPDATE cariler SET Bakiye = Bakiye + ? WHERE Klinik_Unvani=?", (yeni_t_fiyat, f_klinik_adi))
                                    except: pass
                                    try: c.execute("UPDATE isler SET Bakiye_Durumu='Aktarıldı' WHERE id=?", (int(idx_db),))
                                    except: pass

                                conn.commit()
                                if btn_yansit:
                                    st.success("✅ Fiyatlar güncellendi ve cari bakiyeye aktarıldı!")
                                else:
                                    st.success("✅ Fiyatlar güncellendi (Bakiye değiştirilmedi).")
                                st.rerun()
                            else:
                                st.warning("Herhangi bir değişiklik yapmadınız.")
                else:
                    st.info("Kayıtlı iş bulunamadı.")
            else:
                st.warning("Sistemde kayıtlı klinik bulunmuyor.")

        with tab_ekstre_arsiv:
            st.markdown("#### 📋 Hesap Ekstreleri & Fatura Yönetimi")

            alt_tahsilat, alt_tab0, alt_tab_hareket, alt_tab1, alt_tab2, alt_tab3 = st.tabs(["💵 Tahsilat Gir", "💳 Cari Bakiye", "📈 Cari Hesap Hareketleri", "📋 Yeni Ekstre Oluştur", "🧾 Faturalar", "📂 Arşiv"])

            with alt_tahsilat:
                if klinikler:
                    t_klinik = st.selectbox("Ödeme Yapan Klinik", klinikler, key="tah_klinik_sec")
                    # Bekleyen faturalari getir
                    bekleyen_faturalar = c.execute("SELECT id, Fatura_No, Kalan_Tutar FROM faturalar WHERE Klinik_Unvani=? AND Kalan_Tutar > 0", (t_klinik,)).fetchall()
                    fatura_secenekleri = {"Fatura Bağımsız (Genel Bakiye)": None}
                    for fid, fno, fkal in bekleyen_faturalar:
                        fatura_secenekleri[f"{fno} (Kalan: {float(fkal or 0):,.2f} TL)"] = fid
                    
                    with st.form("tahsilat_form"):
                        c1, c2, c3 = st.columns(3)
                        t_tarih = c1.date_input("Tahsilat Tarihi", value=datetime.now(), key="tah_tarih")
                        t_fatura_anahtar = c2.selectbox("İlgili Fatura (Opsiyonel)", list(fatura_secenekleri.keys()), key="tah_fat_sec")
                        t_turu = c3.selectbox("Ödeme Türü", ["Havale / EFT", "Nakit", "Kredi Kartı", "Çek / Senet"], key="tah_tur")
                        t_tutar = c1.number_input("Alınan Tutar (TL)", min_value=0.0, value=0.0, step=100.0, key="tah_tutar")
                        t_aciklama = c2.text_input("Açıklama / Dekont No", key="tah_aciklama")
                        if st.form_submit_button("Tahsilatı Kaydet ve Bakiyeden Düş", type="primary") and t_tutar > 0:
                            secilen_fat_id = fatura_secenekleri[t_fatura_anahtar]
                            tah_tarih_str = t_tarih.strftime("%Y-%m-%d")
                            if secilen_fat_id:
                                fat_raw = c.execute("SELECT Toplam_Tutar, Odenen_Tutar, Fatura_No FROM faturalar WHERE id=?", (secilen_fat_id,)).fetchone()
                                if fat_raw:
                                    yeni_odenen = float(fat_raw[1] or 0) + t_tutar
                                    yeni_kalan = float(fat_raw[0] or 0) - yeni_odenen
                                    yeni_durum = "Ödendi" if yeni_kalan <= 0 else "Kısmi Ödendi"
                                    c.execute("UPDATE faturalar SET Odenen_Tutar=?, Kalan_Tutar=?, Durum=? WHERE id=?", (yeni_odenen, max(0.0, yeni_kalan), yeni_durum, secilen_fat_id))
                                    c.execute("INSERT INTO fatura_tahsilatlar (Fatura_ID, Tarih, Tutar, Odeme_Turu, Aciklama, Klinik_Unvani) VALUES (?,?,?,?,?,?)", (secilen_fat_id, tah_tarih_str, t_tutar, t_turu, t_aciklama, t_klinik))
                                    t_aciklama = f"Fatura: {fat_raw[2]} - {t_aciklama}"
                            
                            c.execute("INSERT INTO tahsilatlar (Tarih, Klinik_Unvani, Odeme_Turu, Tutar, Aciklama) VALUES (?,?,?,?,?)", (tah_tarih_str, t_klinik, t_turu, t_tutar, t_aciklama))
                            c.execute("UPDATE cariler SET Bakiye = Bakiye - ? WHERE Klinik_Unvani = ?", (float(t_tutar), t_klinik))
                            conn.commit()
                            st.success("✅ Tahsilat işlendi, cari bakiye güncellendi!")
                            st.rerun()
                    st.markdown("---")
                    st.markdown("##### 📜 Geçmiş Tahsilatlar")
                    
                    gecmis_tah = c.execute("SELECT id, Tarih, Odeme_Turu, Tutar, Aciklama FROM tahsilatlar WHERE Klinik_Unvani=? ORDER BY id DESC LIMIT 50", (t_klinik,)).fetchall()
                    if gecmis_tah:
                        for tah in gecmis_tah:
                            with st.container(border=True):
                                ct1, ct2, ct3, ct4 = st.columns([3, 2, 3, 1.5])
                                ct1.markdown(f"📅 **{tah[1]}**  \n🏷️ {tah[2]}")
                                ct2.metric("Tutar", f"{float(tah[3] or 0):,.2f} TL")
                                ct3.markdown(f"📝 {tah[4]}")
                                
                                if ct4.button("🗑️ İptal Et", key=f"iptal_tah_{tah[0]}", help="Tahsilatı iptal edip cari bakiyeyi geri yükler"):
                                    tah_id = tah[0]
                                    tah_tutar = float(tah[3] or 0)
                                    tah_tarih = tah[1]
                                    tah_tur = tah[2]
                                    tah_aciklama = tah[4]
                                    
                                    c.execute("UPDATE cariler SET Bakiye = Bakiye + ? WHERE Klinik_Unvani = ?", (float(tah_tutar), t_klinik))
                                    
                                    fat_tah_rec = c.execute("SELECT id, Fatura_ID FROM fatura_tahsilatlar WHERE Klinik_Unvani=? AND Tarih=? AND Tutar=? AND Odeme_Turu=?", (t_klinik, tah_tarih, tah_tutar, tah_tur)).fetchone()
                                    if fat_tah_rec:
                                        fat_tah_id = fat_tah_rec[0]
                                        fatura_id = fat_tah_rec[1]
                                        
                                        fat_raw = c.execute("SELECT Toplam_Tutar, Odenen_Tutar FROM faturalar WHERE id=?", (fatura_id,)).fetchone()
                                        if fat_raw:
                                            yeni_odenen = float(fat_raw[1] or 0) - tah_tutar
                                            yeni_kalan = float(fat_raw[0] or 0) - yeni_odenen
                                            yeni_durum = "Beklemede" if yeni_odenen <= 0 else "Kısmi Ödendi"
                                            c.execute("UPDATE faturalar SET Odenen_Tutar=?, Kalan_Tutar=?, Durum=? WHERE id=?", (max(0.0, yeni_odenen), max(0.0, yeni_kalan), yeni_durum, fatura_id))
                                        
                                        c.execute("DELETE FROM fatura_tahsilatlar WHERE id=?", (fat_tah_id,))
                                        
                                    c.execute("DELETE FROM tahsilatlar WHERE id=?", (tah_id,))
                                    conn.commit()
                                    st.success("✅ Tahsilat iptal edildi ve bakiye geri yüklendi!")
                                    st.rerun()
                    else:
                        st.info("Bu kliniğe ait geçmiş tahsilat bulunmuyor.")


            # ============================================================
            # ALT SEKME 0: CARİ BAKİYE
            # ============================================================
            with alt_tab0:
                st.markdown("##### 💳 Cari Bakiye")
                if klinikler:
                    cb_klinik = st.selectbox("Klinik Seçin", klinikler, key="cb_klinik_sec")

                    # Bakiye kartı
                    # Önce veriyi çekip toplamı buluyoruz
                    try:
                        # Tüm işlerin toplamını bulmak için LIMIT'siz ayrı bir sorgu yapalım ki tam bakiye çıksın
                        toplam_isler = c.execute("SELECT SUM(Tutar_TL) FROM isler WHERE Klinik_Unvani=? AND Bakiye_Durumu='Aktarıldı'", (cb_klinik,)).fetchone()[0] or 0.0
                        kdv_orani_t = float(ayar_getir("KDV_Orani", "20"))
                        carpan_t = 1.0 + (kdv_orani_t / 100.0)
                        toplam_tahsilat_kdvli = c.execute("SELECT SUM(Tutar) FROM tahsilatlar WHERE Klinik_Unvani=?", (cb_klinik,)).fetchone()[0] or 0.0
                        toplam_tahsilat = toplam_tahsilat_kdvli / carpan_t
                        net_bakiye = toplam_isler - toplam_tahsilat
                        
                        # S.NO-HASTA KODU-HASTA ADI-İŞLEM TÜRÜ-ADET-İSKONTO-B. FİYAT-TUTAR(TL)
                        df_isler_cb = pd.read_sql(
                            f"SELECT i.id, i.Hasta_Kodu, i.Hasta_Adi, i.Is_Turu, i.Adet, i.Iskonto, i.Tutar_TL "
                            f"FROM isler i WHERE i.Klinik_Unvani='{cb_klinik}' AND i.Bakiye_Durumu='Aktarıldı' "
                            f"ORDER BY i.Tarih DESC LIMIT 500", conn)
                        
                        # Eğer PostgreSQL küçük harfe dönüştürdüyse toparla
                        df_isler_cb.columns = [c.lower() for c in df_isler_cb.columns]
                        
                        if not df_isler_cb.empty:
                            
                            df_isler_cb["iskonto"] = pd.to_numeric(df_isler_cb["iskonto"], errors='coerce').fillna(0.0)
                            df_isler_cb["adet"] = pd.to_numeric(df_isler_cb["adet"], errors='coerce').fillna(1.0)
                            df_isler_cb["tutar_tl"] = pd.to_numeric(df_isler_cb["tutar_tl"], errors='coerce').fillna(0.0)
                            
                            def calc_bfiyat(row):
                                carpan = 1 - (row["iskonto"] / 100.0)
                                if carpan <= 0: carpan = 1.0
                                gercek_toplam = row["tutar_tl"] / carpan
                                adet = row["adet"] if row["adet"] > 0 else 1.0
                                return round(gercek_toplam / adet, 2)
                                
                            df_isler_cb["B. FİYAT"] = df_isler_cb.apply(calc_bfiyat, axis=1)
                            
                            df_isler_cb = df_isler_cb.rename(columns={
                                "hasta_kodu": "HASTA KODU",
                                "hasta_adi": "HASTA ADI",
                                "is_turu": "İŞLEM TÜRÜ",
                                "adet": "ADET",
                                "iskonto": "İSKONTO",
                                "tutar_tl": "TUTAR(TL)"
                            })
                            
                            df_isler_cb.insert(0, 'S.NO', range(1, len(df_isler_cb) + 1))
                            df_isler_cb = df_isler_cb[["S.NO", "HASTA KODU", "HASTA ADI", "İŞLEM TÜRÜ", "ADET", "İSKONTO", "B. FİYAT", "TUTAR(TL)"]]
                    except Exception as e_cb:
                        st.error(f"Veriler yüklenemedi: {e_cb}")
                        df_isler_cb = pd.DataFrame()
                        toplam_isler = 0.0
                        toplam_tahsilat = 0.0
                        net_bakiye = 0.0

                    # Bakiye kartı (Listedeki toplamı gösterir)
                    para_birimi_cb = ayar_getir("Para_Birimi", "TL")
                    renk_cb = "#ef4444" if net_bakiye > 0 else "#22c55e"
                    st.markdown(f"""
                    <div style='background: linear-gradient(135deg, #1e293b, #0f172a); border: 1px solid {renk_cb}40;
                         border-radius: 16px; padding: 24px; text-align: center; margin-bottom: 16px;'>
                    <div style='color: #94a3b8; font-size: 14px; margin-bottom: 8px;'>⚡ Güncel Net Bakiye</div>
                    <div style='color: {renk_cb}; font-size: 48px; font-weight: 800;'>{net_bakiye:,.2f} {para_birimi_cb}</div>
                        <div style='color: #64748b; font-size: 13px; margin-top: 8px;'>{cb_klinik}</div>
                        <div style='display: flex; justify-content: space-around; margin-top: 24px; border-top: 1px solid #334155; padding-top: 16px;'>
                            <div>
                                <div style='color: #94a3b8; font-size: 13px;'>Toplam Borç (Reçeteler)</div>
                                <div style='color: #cbd5e1; font-size: 20px; font-weight: 700;'>{toplam_isler:,.2f} {para_birimi_cb}</div>
                            </div>
                            <div>
                                <div style='color: #94a3b8; font-size: 13px;'>Ödenen (Net Tahsilat)</div>
                                <div style='color: #22c55e; font-size: 20px; font-weight: 700;'>{toplam_tahsilat:,.2f} {para_birimi_cb}</div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    # Fiyat listesinden gelen işler tablosu
                    st.markdown("---")
                    st.markdown("##### 📋 Fiyat Listesine İşlenen Hizmetler")
                    
                    if not df_isler_cb.empty:
                        st.dataframe(df_isler_cb,  hide_index=True, use_container_width=True)
                    else:
                        st.info("Bu klinik için fiyat listesine işlenmiş hizmet bulunmuyor.")



            # ============================================================
            # ALT SEKME 1: YENİ EKSTRE OLUŞTUR
            # ============================================================
            # ============================================================
            # ALT SEKME HAREKET: CARİ HESAP HAREKETLERİ
            # ============================================================
            with alt_tab_hareket:
                st.markdown("##### 📈 Cari Hesap Hareketleri")
                st.caption("Seçilen kliniğe ait tüm borç (işlem/reçete) ve alacak (tahsilat) kayıtlarının kronolojik olarak listelendiği ekstre hareketleridir.")
                if klinikler:
                    ch_klinik = st.selectbox("Hareketleri Gösterilecek Klinik", klinikler, key="ch_klinik_sec")
                    
                    df_ch_borc = pd.read_sql(f"SELECT Tarih, Barkod, Hasta_Adi, Is_Turu, Tutar_TL as borc FROM isler WHERE Klinik_Unvani='{ch_klinik}' AND Bakiye_Durumu='Aktarıldı' AND (Tutar_TL > 0 OR Is_Turu LIKE '%(RPT)%')", conn)
                    df_ch_alacak = pd.read_sql(f"SELECT id, Tarih, Odeme_Turu, Aciklama, Tutar as alacak FROM tahsilatlar WHERE Klinik_Unvani='{ch_klinik}'", conn)
                    
                    df_list = []
                    
                    if not df_ch_borc.empty:
                        df_ch_borc.columns = [c.lower() for c in df_ch_borc.columns]
                        df_ch_borc['belge_no'] = df_ch_borc['barkod']
                        df_ch_borc['aciklama'] = df_ch_borc['hasta_adi'].astype(str) + ' - ' + df_ch_borc['is_turu'].astype(str)
                        df_ch_borc['alacak'] = 0.0
                        df_list.append(df_ch_borc[['tarih', 'belge_no', 'aciklama', 'borc', 'alacak']])
                        
                    if not df_ch_alacak.empty:
                        df_ch_alacak.columns = [c.lower() for c in df_ch_alacak.columns]
                        df_ch_alacak['belge_no'] = 'TAH-' + df_ch_alacak['id'].astype(str)
                        df_ch_alacak['aciklama'] = df_ch_alacak['odeme_turu'].astype(str) + ' Tahsilatı (' + df_ch_alacak['aciklama'].astype(str) + ')'
                        df_ch_alacak['borc'] = 0.0
                        
                        try:
                            df_ft_ch = pd.read_sql(f"SELECT ft.Tarih, ft.Tutar, ft.Odeme_Turu, f.KDV_Orani FROM fatura_tahsilatlar ft JOIN faturalar f ON ft.Fatura_ID = f.id WHERE ft.Klinik_Unvani='{ch_klinik}'", conn)
                            if not df_ft_ch.empty:
                                df_ft_ch.columns = [c.lower() for c in df_ft_ch.columns]
                                df_ch_alacak = pd.merge(df_ch_alacak, df_ft_ch, left_on=['tarih', 'alacak', 'odeme_turu'], right_on=['tarih', 'tutar', 'odeme_turu'], how='left')
                            else:
                                df_ch_alacak['kdv_orani'] = None
                        except:
                            df_ch_alacak['kdv_orani'] = None

                        kdv_orani_h = float(ayar_getir("KDV_Orani", "20"))
                        def get_ch_alacak_net(row):
                            if pd.notna(row.get('kdv_orani')):
                                return row['alacak'] / (1.0 + float(row['kdv_orani']) / 100.0)
                            else:
                                return row['alacak'] / (1.0 + kdv_orani_h / 100.0)
                        
                        df_ch_alacak['alacak'] = df_ch_alacak.apply(get_ch_alacak_net, axis=1)
                        if 'kdv_orani' in df_ch_alacak.columns: df_ch_alacak = df_ch_alacak.drop(columns=['kdv_orani'])
                        if 'tutar' in df_ch_alacak.columns: df_ch_alacak = df_ch_alacak.drop(columns=['tutar'])

                        df_list.append(df_ch_alacak[['tarih', 'belge_no', 'aciklama', 'borc', 'alacak']])
                        
                    if df_list:
                        df_hareket = pd.concat(df_list).sort_values(by="tarih").reset_index(drop=True)
                        
                        df_hareket['bakiye'] = df_hareket['borc'].cumsum() - df_hareket['alacak'].cumsum()
                        
                        # Ters çevirme (En yeni en üstte)
                        df_hareket = df_hareket.iloc[::-1].reset_index(drop=True)
                        
                        df_goster_ch = df_hareket.rename(columns={
                            "tarih": "TARİH",
                            "belge_no": "BELGE NO",
                            "aciklama": "AÇIKLAMA",
                            "borc": "BORÇ",
                            "alacak": "ALACAK",
                            "bakiye": "BAKİYE"
                        })
                        
                        st.dataframe(df_goster_ch.style.format({
                            "BORÇ": "{:,.2f} ₺", 
                            "ALACAK": "{:,.2f} ₺", 
                            "BAKİYE": "{:,.2f} ₺"
                        }), hide_index=True, use_container_width=True)
                    else:
                        st.info("Bu kliniğe ait herhangi bir hesap hareketi bulunamadı.")
                else:
                    st.info("Kayıtlı klinik bulunamadı.")

            with alt_tab1:
                st.markdown("##### 📋 Geriye Dönük Hesap Ekstresi Oluştur")
                if klinikler:
                    e_klinik = st.selectbox("Klinik Seçin", klinikler, key="yeni_ekstre_klinik")

                    col_d1, col_d2 = st.columns(2)
                    e_baslangic = col_d1.date_input("Başlangıç Tarihi", key="e_bas", value=None)
                    e_bitis = col_d2.date_input("Bitiş Tarihi", key="e_bit", value=None)

                    if e_baslangic and e_bitis:
                        if e_bitis < e_baslangic:
                            st.error("Bitiş tarihi başlangıç tarihinden önce olamaz!")
                        else:
                            bas_str = str(e_baslangic)
                            bit_str = str(e_bitis)

                            # Ön izleme
                            try:
                                df_prev_borc = pd.read_sql(
                                    f"SELECT Tarih, Is_Turu || ' - ' || Hasta_Adi as Islem, Tutar_TL as Borc, 0.0 as Alacak "
                                    f"FROM isler WHERE Klinik_Unvani='{e_klinik}' AND Bakiye_Durumu='Aktarıldı' AND (Tutar_TL > 0 OR Is_Turu LIKE '%(RPT)%') "
                                    f"AND Tarih >= '{bas_str}' AND Tarih <= '{bit_str}'", conn)
                                df_prev_alacak = pd.read_sql(
                                    f"SELECT Tarih, Odeme_Turu, Tutar, Odeme_Turu || ' Odemesi (' || Aciklama || ')' as Islem, 0.0 as Borc, Tutar as Alacak "
                                    f"FROM tahsilatlar WHERE Klinik_Unvani='{e_klinik}' "
                                    f"AND Tarih >= '{bas_str}' AND Tarih <= '{bit_str}'", conn)

                                # PostgreSQL küçük harf → büyük harf normalize
                                for df_tmp in [df_prev_borc, df_prev_alacak]:
                                    df_tmp.columns = [c.capitalize() if c.lower() in ['tarih','islem','borc','alacak'] else c for c in df_tmp.columns]
                                df_prev_borc  = df_prev_borc.rename(columns={"tarih":"Tarih","islem":"Islem","borc":"Borc","alacak":"Alacak"})
                                df_prev_alacak = df_prev_alacak.rename(columns={"tarih":"Tarih","islem":"Islem","borc":"Borc","alacak":"Alacak"})

                                # DEVREDEN BAKIYE HESAPLAMA (İleriye dönük tam doğruluk ve KDV hariç tahsilat)
                                try:
                                    kdv_orani_h = float(ayar_getir("KDV_Orani", "20"))
                                    
                                    # KDV oranlarını bulmak için fatura_tahsilatlar
                                    try:
                                        df_ft_prev = pd.read_sql(f"SELECT ft.Tarih, ft.Tutar, ft.Odeme_Turu, f.KDV_Orani FROM fatura_tahsilatlar ft JOIN faturalar f ON ft.Fatura_ID = f.id WHERE ft.Klinik_Unvani='{e_klinik}'", conn)
                                        if not df_ft_prev.empty and not df_prev_alacak.empty:
                                            df_prev_alacak = pd.merge(df_prev_alacak, df_ft_prev, on=['Tarih', 'Tutar', 'Odeme_Turu'], how='left')
                                        else:
                                            df_prev_alacak['KDV_Orani'] = None
                                    except:
                                        df_prev_alacak['KDV_Orani'] = None
                                        df_ft_prev = pd.DataFrame()
                                        
                                    def apply_kdv_prev(row, val_col):
                                        if pd.notna(row.get('KDV_Orani')):
                                            return row[val_col] / (1.0 + float(row['KDV_Orani']) / 100.0)
                                        else:
                                            return row[val_col] / (1.0 + kdv_orani_h / 100.0)
                                            
                                    if not df_prev_alacak.empty:
                                        df_prev_alacak['Alacak'] = df_prev_alacak.apply(lambda r: apply_kdv_prev(r, 'Alacak'), axis=1)
                                        if 'KDV_Orani' in df_prev_alacak.columns: df_prev_alacak = df_prev_alacak.drop(columns=['KDV_Orani'])
                                        if 'Tutar' in df_prev_alacak.columns: df_prev_alacak = df_prev_alacak.drop(columns=['Tutar'])
                                        if 'Odeme_Turu' in df_prev_alacak.columns: df_prev_alacak = df_prev_alacak.drop(columns=['Odeme_Turu'])

                                    # Devreden bakiyeyi baştan hesapla (Geçmiş Borç - Geçmiş Alacak)
                                    past_borc_row = c.execute(f"SELECT SUM(Tutar_TL) FROM isler WHERE Klinik_Unvani='{e_klinik}' AND Bakiye_Durumu='Aktarıldı' AND (Tutar_TL > 0 OR Is_Turu LIKE '%(RPT)%') AND Tarih < '{bas_str}'").fetchone()
                                    past_borc = float(past_borc_row[0] or 0.0) if past_borc_row else 0.0
                                    
                                    try:
                                        df_past_alacak = pd.read_sql(f"SELECT Tarih, Odeme_Turu, Tutar FROM tahsilatlar WHERE Klinik_Unvani='{e_klinik}' AND Tarih < '{bas_str}'", conn)
                                        if not df_past_alacak.empty:
                                            if not df_ft_prev.empty:
                                                df_past_alacak = pd.merge(df_past_alacak, df_ft_prev, on=['Tarih', 'Tutar', 'Odeme_Turu'], how='left')
                                            else:
                                                df_past_alacak['KDV_Orani'] = None
                                            past_alacak = df_past_alacak.apply(lambda r: apply_kdv_prev(r, 'Tutar'), axis=1).sum()
                                        else:
                                            past_alacak = 0.0
                                    except:
                                        past_alacak_row = c.execute(f"SELECT SUM(Tutar) FROM tahsilatlar WHERE Klinik_Unvani='{e_klinik}' AND Tarih < '{bas_str}'").fetchone()
                                        past_alacak_raw = float(past_alacak_row[0] or 0.0) if past_alacak_row else 0.0
                                        past_alacak = past_alacak_raw / (1.0 + kdv_orani_h / 100.0)
                                    
                                    devreden_bakiye = past_borc - past_alacak
                                    
                                    import pandas as pd
                                    devreden_df = pd.DataFrame([{
                                        "Tarih": bas_str,
                                        "Islem": "Devreden Bakiye",
                                        "Borc": devreden_bakiye if devreden_bakiye > 0 else 0.0,
                                        "Alacak": abs(devreden_bakiye) if devreden_bakiye < 0 else 0.0
                                    }])
                                    df_prev = pd.concat([devreden_df, df_prev_borc, df_prev_alacak]).sort_values(by="Tarih").reset_index(drop=True)
                                except Exception as e:
                                    # Fallback
                                    df_prev = pd.concat([df_prev_borc, df_prev_alacak]).sort_values(by="Tarih").reset_index(drop=True)
                                borc_col  = "Borc"  if "Borc"  in df_prev.columns else "borc"
                                alacak_col = "Alacak" if "Alacak" in df_prev.columns else "alacak"
                                tarih_col  = "Tarih"  if "Tarih"  in df_prev.columns else "tarih"
                                df_prev['Kümülatif Bakiye'] = df_prev[borc_col].cumsum() - df_prev[alacak_col].cumsum()
                                toplam_borc_prev   = float(df_prev[borc_col].sum())
                                toplam_alacak_prev = float(df_prev[alacak_col].sum())
                                net_bakiye_prev = toplam_borc_prev - toplam_alacak_prev

                                # Özet kartlar
                                m1, m2, m3 = st.columns(3)
                                m1.metric("📤 Toplam Borç", f"{toplam_borc_prev:,.2f} TL")
                                m2.metric("📥 Toplam Alacak", f"{toplam_alacak_prev:,.2f} TL")
                                m3.metric("⚖️ Net Bakiye", f"{net_bakiye_prev:,.2f} TL",
                                         delta_color="inverse")

                                if not df_prev.empty:
                                    st.dataframe(df_prev.style.format({"Borc": "{:,.2f}", "Alacak": "{:,.2f}"}),
                                                 hide_index=True, use_container_width=True)
                                else:
                                    st.info("Seçilen dönemde kayıt bulunamadı.")

                                col_btn_e1, col_btn_e2 = st.columns(2)
                                if col_btn_e1.button("💾 Ekstreyi Oluştur ve Arşive Kaydet", type="primary",
                                                      use_container_width=True, key="ekstre_kaydet_btn"):
                                    try:
                                        ekstre_pdf = ekstre_pdf_uret(e_klinik, df_prev, net_bakiye_prev)
                                        dosya_adi = f"{e_klinik}_Ekstre_{bas_str}_{bit_str}.pdf"
                                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                                        c.execute(
                                            "INSERT INTO hesap_ekstreleri (Olusturma_Tarihi, Klinik_Unvani, Baslangic_Tarihi, Bitis_Tarihi, "
                                            "Toplam_Borc, Toplam_Alacak, Net_Bakiye, PDF_Verisi, Dosya_Adi, Durum) "
                                            "VALUES (?,?,?,?,?,?,?,?,?,?)",
                                            (now_str, e_klinik, bas_str, bit_str,
                                             toplam_borc_prev, toplam_alacak_prev, net_bakiye_prev,
                                             ekstre_pdf, dosya_adi, "Taslak"))
                                        conn.commit()
                                        st.success(f"✅ Ekstre arşive kaydedildi! ({bas_str} - {bit_str})")
                                        st.session_state["son_yeni_ekstre_pdf"] = ekstre_pdf
                                        st.session_state["son_yeni_ekstre_dosya"] = dosya_adi
                                        st.session_state["son_yeni_ekstre_df"] = df_prev
                                        st.session_state["son_yeni_ekstre_net"] = net_bakiye_prev
                                        st.session_state["son_yeni_ekstre_klinik"] = e_klinik
                                        st.rerun()
                                    except Exception as e_save:
                                        st.error(f"Kayıt hatası: {e_save}")

                                # PDF indir butonu (son kaydedilen için)
                                if st.session_state.get("son_yeni_ekstre_klinik") == e_klinik and st.session_state.get("son_yeni_ekstre_pdf"):
                                    col_btn_e2.download_button(
                                        "📥 PDF İndir",
                                        data=st.session_state["son_yeni_ekstre_pdf"],
                                        file_name=st.session_state["son_yeni_ekstre_dosya"],
                                        mime="application/pdf", use_container_width=True,
                                        key="ekstre_pdf_indir"
                                    )

                            except Exception as e_prev:
                                st.error(f"Önizleme hatası: {e_prev}")
                    else:
                        st.info("📅 Lütfen başlangıç ve bitiş tarihlerini seçin.")

            # ============================================================
            # ALT SEKME 2: FATURALAR
            # ============================================================
            with alt_tab2:
                st.markdown("##### 🧾 Fatura Yönetimi")

                # Faturalanmamış ekstreler
                try:
                    df_bekleyen = pd.read_sql(
                        "SELECT id, Olusturma_Tarihi, Klinik_Unvani, Baslangic_Tarihi, Bitis_Tarihi, Net_Bakiye, Durum "
                        "FROM hesap_ekstreleri WHERE Durum='Taslak' ORDER BY id DESC", conn)
                    col_map = {"id": "id", "olusturma_tarihi": "Olusturma_Tarihi", "klinik_unvani": "Klinik_Unvani", "baslangic_tarihi": "Baslangic_Tarihi", "bitis_tarihi": "Bitis_Tarihi", "net_bakiye": "Net_Bakiye", "durum": "Durum", "fatura_id": "Fatura_ID"}
                    df_bekleyen = df_bekleyen.rename(columns=col_map)
                    if not df_bekleyen.empty:
                        with st.expander(f"📌 Faturalanmayı Bekleyen {len(df_bekleyen)} Ekstre", expanded=True):
                            for _, row_e in df_bekleyen.iterrows():
                                with st.container(border=True):
                                    fe1, fe2, fe3 = st.columns([3, 2, 2])
                                    fe1.markdown("🏥 **" + str(row_e["Klinik_Unvani"]) + "**  \n📅 " + str(row_e["Baslangic_Tarihi"]) + " → " + str(row_e["Bitis_Tarihi"]))
                                    fe2.metric("Net Bakiye", f"{float(row_e['Net_Bakiye'] or 0):,.2f} TL")
                                    if fe3.button("🧾 Faturalandır", key=f"fat_btn_{row_e['id']}", type="primary", use_container_width=True):
                                        st.session_state["faturalandirilacak_ekstre_id"] = int(row_e["id"])
                                        st.session_state["faturalandirilacak_klinik"] = str(row_e["Klinik_Unvani"])
                                        st.session_state["faturalandirilacak_tutar"] = float(row_e["Net_Bakiye"] or 0)
                except Exception:
                    pass

                # Fatura oluşturma formu
                if st.session_state.get("faturalandirilacak_ekstre_id"):
                    ekstre_id_f = st.session_state["faturalandirilacak_ekstre_id"]
                    fat_klinik = st.session_state["faturalandirilacak_klinik"]
                    fat_tutar = st.session_state["faturalandirilacak_tutar"]

                    st.markdown("---")
                    st.markdown("#### 📝 Fatura Oluştur — " + str(fat_klinik))
                    with st.form("fatura_olustur_form"):
                        # Otomatik fatura no
                        try:
                            son_id = c.execute("SELECT COUNT(*) FROM faturalar").fetchone()[0]
                        except:
                            son_id = 0
                        otomatik_fatura_no = f"OMG-{datetime.now().year}-{str(son_id+1).zfill(4)}"
                        fc1, fc2, fc3 = st.columns([2, 2, 1])
                        fatura_no_input = fc1.text_input("Fatura No", value=otomatik_fatura_no)
                        fatura_tarihi_input = fc2.text_input("Fatura Tarihi", value=datetime.now().strftime("%Y-%m-%d"))
                        fatura_kdv_input = fc3.selectbox("KDV Oranı (%)", [0, 1, 10, 20], index=0)
                        
                        fatura_tutar_input = st.number_input("Ara Toplam / Fatura Tutarı (KDV Hariç TL)", value=float(fat_tutar), step=100.0)
                        
                        kdv_tutar_hesap = fatura_tutar_input * (fatura_kdv_input / 100.0)
                        genel_toplam_hesap = fatura_tutar_input + kdv_tutar_hesap
                        st.info(f"🧾 **Hesaplanan KDV:** {kdv_tutar_hesap:,.2f} TL | **Genel Toplam:** {genel_toplam_hesap:,.2f} TL")
                        
                        fatura_aciklama = st.text_area("Açıklama", placeholder="Fatura açıklaması...")

                        if st.form_submit_button("✅ Fatura Oluştur ve PDF Kaydet", type="primary"):
                            try:
                                # Ekstre PDF'ini al
                                ekstre_row = c.execute("SELECT PDF_Verisi FROM hesap_ekstreleri WHERE id=?", (ekstre_id_f,)).fetchone()
                                ekstre_pdf_bytes = bytes(ekstre_row[0]) if ekstre_row and ekstre_row[0] else b""

                                # Ekstre DataFrame'i al
                                df_ekstre_fat = pd.DataFrame()
                                try:
                                    ekstre_data = c.execute("SELECT Baslangic_Tarihi, Bitis_Tarihi FROM hesap_ekstreleri WHERE id=?", (ekstre_id_f,)).fetchone()
                                    if ekstre_data:
                                        df_b = pd.read_sql(f"SELECT Tarih, Is_Turu || ' - ' || Hasta_Adi as Islem, Tutar_TL as Borc, 0.0 as Alacak FROM isler WHERE Klinik_Unvani='{fat_klinik}' AND (Tutar_TL > 0 OR Is_Turu LIKE '%(RPT)%') AND Tarih >= '{ekstre_data[0]}' AND Tarih <= '{ekstre_data[1]}'", conn)
                                        df_a = pd.read_sql(f"SELECT Tarih, Odeme_Turu || ' Odemesi' as Islem, 0.0 as Borc, Tutar as Alacak FROM tahsilatlar WHERE Klinik_Unvani='{fat_klinik}' AND Tarih >= '{ekstre_data[0]}' AND Tarih <= '{ekstre_data[1]}'", conn)
                                        df_ekstre_fat = pd.concat([df_b, df_a]).sort_values("Tarih").reset_index(drop=True)
                                except:
                                    pass

                                fatura_pdf = fatura_pdf_uret(fatura_no_input, fat_klinik, df_ekstre_fat, fatura_tutar_input, fatura_tarihi_input, fatura_kdv_input, fatura_aciklama)
                                dosya_fat = f"Fatura_{fatura_no_input}_{fat_klinik}.pdf"
                                c.execute(
                                    "INSERT INTO faturalar (Fatura_No, Fatura_Tarihi, Klinik_Unvani, Ekstre_ID, "
                                    "Toplam_Tutar, Odenen_Tutar, Kalan_Tutar, Ara_Toplam, KDV_Orani, Durum, PDF_Verisi, Dosya_Adi, Aciklama) "
                                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (fatura_no_input, fatura_tarihi_input, fat_klinik, ekstre_id_f,
                                     float(genel_toplam_hesap), 0.0, float(genel_toplam_hesap), float(fatura_tutar_input), float(fatura_kdv_input),
                                     "Beklemede", fatura_pdf, dosya_fat, fatura_aciklama))
                                fatura_id_yeni = c.execute("SELECT id FROM faturalar ORDER BY id DESC LIMIT 1").fetchone()[0]
                                c.execute("UPDATE hesap_ekstreleri SET Durum=?, Fatura_ID=? WHERE id=?", ("Faturalanmış", fatura_id_yeni, ekstre_id_f))
                                conn.commit()
                                st.success(f"✅ Fatura {fatura_no_input} oluşturuldu!")
                                st.session_state["son_fatura_pdf"] = fatura_pdf
                                st.session_state["son_fatura_dosya"] = dosya_fat
                                st.session_state.pop("faturalandirilacak_ekstre_id", None)
                                st.rerun()
                            except Exception as e_fat:
                                st.error(f"Fatura oluşturma hatası: {e_fat}")

                # Son fatura PDF indir
                if st.session_state.get("son_fatura_pdf"):
                    st.download_button("📥 Fatura PDF İndir", data=st.session_state["son_fatura_pdf"],
                                       file_name=st.session_state.get("son_fatura_dosya", "fatura.pdf"),
                                       mime="application/pdf", use_container_width=True, key="son_fat_indir")

                st.markdown("---")
                st.markdown("##### 📊 Tüm Faturalar")

                # Fatura listesi
                durum_renk = {"Beklemede": "🔴", "Kısmi Ödendi": "🟡", "Ödendi": "🟢"}
                filtre_klinik_fat = st.selectbox("Kliniğe Göre Filtrele", ["Tümü"] + klinikler, key="fat_filtre")

                try:
                    c.execute("ALTER TABLE faturalar ADD COLUMN KDV_Orani REAL DEFAULT 0")
                    conn.commit()
                except Exception:
                    # Hata verirse zaten eklenmiştir, devam et
                    conn.rollback()
                
                try:
                    c.execute("ALTER TABLE faturalar ADD COLUMN Ara_Toplam REAL DEFAULT 0")
                    conn.commit()
                except Exception:
                    conn.rollback()

                try:
                    q_fat = "SELECT id, Fatura_No, Fatura_Tarihi, Klinik_Unvani, Ekstre_ID, Toplam_Tutar, Odenen_Tutar, Kalan_Tutar, Ara_Toplam, KDV_Orani, Durum FROM faturalar"
                    if filtre_klinik_fat != "Tümü":
                        df_faturalar = pd.read_sql(f"{q_fat} WHERE Klinik_Unvani='{filtre_klinik_fat}' ORDER BY id DESC", conn)
                    else:
                        df_faturalar = pd.read_sql(f"{q_fat} ORDER BY id DESC", conn)
                    col_map_fat = {"id": "id", "fatura_no": "Fatura_No", "fatura_tarihi": "Fatura_Tarihi", "klinik_unvani": "Klinik_Unvani", "ekstre_id": "Ekstre_ID", "toplam_tutar": "Toplam_Tutar", "odenen_tutar": "Odenen_Tutar", "kalan_tutar": "Kalan_Tutar", "ara_toplam": "Ara_Toplam", "kdv_orani": "KDV_Orani", "durum": "Durum"}
                    df_faturalar = df_faturalar.rename(columns=col_map_fat)

                    if not df_faturalar.empty:
                        for _, fat_row in df_faturalar.iterrows():
                            durum_icon = durum_renk.get(str(fat_row.get("Durum", "")), "⚪")
                            with st.container(border=True):
                                fa1, fa2, fa3, fa4, fa5 = st.columns([3, 2, 2, 2, 1.5])
                                fa1.markdown(str(durum_icon) + " **" + str(fat_row["Fatura_No"]) + "**  \n🏥 " + str(fat_row["Klinik_Unvani"]) + "  \n📅 " + str(fat_row["Fatura_Tarihi"]))
                                fa2.metric("Toplam", f"{float(fat_row['Toplam_Tutar'] or 0):,.2f} TL")
                                fa3.metric("Kalan", f"{float(fat_row['Kalan_Tutar'] or 0):,.2f} TL",
                                          delta=f"-{float(fat_row['Odenen_Tutar'] or 0):,.2f} ödendi")
                                          
                                if fa5.button("🗑️ Geri Çek", key=f"revert_fat_{fat_row['id']}", help="Faturayı iptal edip ekstreyi taslak durumuna döndürür"):
                                    odenen = float(fat_row.get('Odenen_Tutar') or 0)
                                    if odenen > 0:
                                        st.error("⚠️ ÖNCE TAHSİLATI GERİ ÇEK! Faturaya ait tahsilat bulunduğu için fatura geri çekilemez.")
                                    else:
                                        fat_id = int(fat_row['id'])
                                        # Faturaya bagli ekstreyi bulalim
                                        bagli_ekstre = c.execute("SELECT Ekstre_ID FROM faturalar WHERE id=?", (fat_id,)).fetchone()
                                        if bagli_ekstre and bagli_ekstre[0]:
                                            c.execute("UPDATE hesap_ekstreleri SET Durum='Taslak', Fatura_ID=NULL WHERE id=?", (bagli_ekstre[0],))
                                        c.execute("DELETE FROM faturalar WHERE id=?", (fat_id,))
                                        conn.commit()
                                        st.success("Fatura iptal edildi ve ekstre geri çekildi!")
                                        st.rerun()

                                # PDF indir
                                try:
                                    pdf_raw_f = c.execute("SELECT PDF_Verisi FROM faturalar WHERE id=?", (int(fat_row["id"]),)).fetchone()
                                    if pdf_raw_f and pdf_raw_f[0]:
                                        pdf_bytes_f = bytes(pdf_raw_f[0]) if not isinstance(pdf_raw_f[0], bytes) else pdf_raw_f[0]
                                        fa4.download_button("📥 PDF", data=pdf_bytes_f,
                                                            file_name=str(fat_row.get("Dosya_Adi", "fatura.pdf")),
                                                            mime="application/pdf", use_container_width=True,
                                                            key=f"fat_pdf_{fat_row['id']}")
                                except:
                                    pass

                                with st.expander(f"✏️ Fatura Düzelt — {fat_row['Fatura_No']}"):
                                    with st.form(f"fat_duz_form_{fat_row['id']}"):
                                        duz_col1, duz_col2, duz_col3, duz_col4 = st.columns([2, 2, 2, 1])
                                        d_fno = duz_col1.text_input("Fatura No", value=str(fat_row["Fatura_No"]), key=f"d_fno_{fat_row['id']}")
                                        d_ftar = duz_col2.text_input("Fatura Tarihi", value=str(fat_row["Fatura_Tarihi"]), key=f"d_ftar_{fat_row['id']}")
                                        g_ara = float(fat_row.get('Ara_Toplam') or 0)

                                        g_kdv = int(float(fat_row.get('KDV_Orani') or 0))

                                        

                                        if g_ara == 0:

                                            try:

                                                ekstre_tutar = c.execute("SELECT Tutar_TL FROM hesap_ekstreleri WHERE id=?", (int(fat_row['Ekstre_ID']),)).fetchone()

                                                if ekstre_tutar and float(ekstre_tutar[0]) > 0:

                                                    orijinal_tutar = float(ekstre_tutar[0])

                                                    toplam_tutar = float(fat_row['Toplam_Tutar'])

                                                    oran = round(((toplam_tutar / orijinal_tutar) - 1) * 100)

                                                    if oran in [0, 1, 10, 20]:

                                                        g_ara = orijinal_tutar

                                                        g_kdv = oran

                                            except Exception:

                                                pass

                                            if g_ara == 0:

                                                g_ara = float(fat_row['Toplam_Tutar'])

                                        

                                        kdv_index = [0, 1, 10, 20].index(g_kdv) if g_kdv in [0, 1, 10, 20] else 0

                                        

                                        d_ara_tutar = duz_col3.number_input("Ara Toplam (KDV Hariç)", value=float(g_ara), step=100.0, key=f"d_tutar_{fat_row['id']}")

                                        d_kdv = duz_col4.selectbox("KDV Oranı (%)", [0, 1, 10, 20], index=kdv_index, key=f"d_kdv_{fat_row['id']}")
                                        
                                        d_hesaplanan_kdv = d_ara_tutar * (d_kdv / 100.0)
                                        d_genel_toplam = d_ara_tutar + d_hesaplanan_kdv
                                        st.info(f"🧾 **Hesaplanan KDV:** {d_hesaplanan_kdv:,.2f} TL | **Yeni Genel Toplam:** {d_genel_toplam:,.2f} TL")
                                        
                                        if st.form_submit_button("💾 Değişiklikleri Kaydet", type="primary"):
                                            y_odenen = float(fat_row["Odenen_Tutar"] or 0)
                                            y_kalan = d_genel_toplam - y_odenen
                                            y_durum = "Ödendi" if y_kalan <= 0 else "Kısmi Ödendi" if y_odenen > 0 else "Beklemede"
                                            
                                            c.execute("UPDATE faturalar SET Fatura_No=?, Fatura_Tarihi=?, Toplam_Tutar=?, Kalan_Tutar=?, Ara_Toplam=?, KDV_Orani=?, Durum=? WHERE id=?", 
                                                      (d_fno, d_ftar, float(d_genel_toplam), float(y_kalan), float(d_ara_tutar), float(d_kdv), y_durum, int(fat_row["id"])))
                                            conn.commit()
                                            st.success("Fatura başarıyla güncellendi!")
                                            st.rerun()
                    else:
                        st.info("📭 Henüz fatura bulunmuyor.")
                except Exception as e_fat_list:
                    st.error(f"Fatura listesi yüklenemedi: {e_fat_list}")

            # ============================================================
            # ALT SEKME 3: ARŞİV
            # ============================================================
            with alt_tab3:
                st.markdown("##### 📂 Ekstre ve Fatura Arşivi")
                arsiv_klinik = st.selectbox("Kliniğe Göre Filtrele", ["Tümü"] + klinikler, key="arsiv_klinik_sec")

                try:
                    q_arsiv = ("SELECT id, Olusturma_Tarihi, Klinik_Unvani, Baslangic_Tarihi, Bitis_Tarihi, "
                               "Net_Bakiye, Durum, Fatura_ID FROM hesap_ekstreleri")
                    if arsiv_klinik != "Tümü":
                        df_arsiv2 = pd.read_sql(f"{q_arsiv} WHERE Klinik_Unvani='{arsiv_klinik}' ORDER BY id DESC", conn)
                        col_map = {"id": "id", "olusturma_tarihi": "Olusturma_Tarihi", "klinik_unvani": "Klinik_Unvani", "baslangic_tarihi": "Baslangic_Tarihi", "bitis_tarihi": "Bitis_Tarihi", "net_bakiye": "Net_Bakiye", "durum": "Durum", "fatura_id": "Fatura_ID"}
                        df_arsiv2 = df_arsiv2.rename(columns=col_map)
                    else:
                        df_arsiv2 = pd.read_sql(f"{q_arsiv} ORDER BY id DESC", conn)
                        col_map = {"id": "id", "olusturma_tarihi": "Olusturma_Tarihi", "klinik_unvani": "Klinik_Unvani", "baslangic_tarihi": "Baslangic_Tarihi", "bitis_tarihi": "Bitis_Tarihi", "net_bakiye": "Net_Bakiye", "durum": "Durum", "fatura_id": "Fatura_ID"}
                        df_arsiv2 = df_arsiv2.rename(columns=col_map)

                    if not df_arsiv2.empty:
                        for _, ar_row in df_arsiv2.iterrows():
                            fat_durum = ""
                            fat_id_ar = ar_row.get("Fatura_ID")
                            if fat_id_ar:
                                try:
                                    fat_info = c.execute("SELECT Fatura_No, Durum, Kalan_Tutar FROM faturalar WHERE id=?", (int(fat_id_ar),)).fetchone()
                                    if fat_info:
                                        d_icon = {"Beklemede": "🔴", "Kısmi Ödendi": "🟡", "Ödendi": "🟢"}.get(fat_info[1], "⚪")
                                        fat_durum = f"{d_icon} Fatura: **{fat_info[0]}** — {fat_info[1]} (Kalan: {float(fat_info[2] or 0):,.2f} TL)"
                                except:
                                    pass

                            durum_icon_ar = "📄" if str(ar_row.get("Durum")) == "Taslak" else "🧾"
                            with st.container(border=True):
                                ar1, ar2, ar3 = st.columns([4, 2, 2])
                                ar1.markdown(str(durum_icon_ar) + " **" + str(ar_row["Klinik_Unvani"]) + "** (" + str(ar_row["Durum"]) + ")  \n📅 " + str(ar_row["Baslangic_Tarihi"]) + " → " + str(ar_row["Bitis_Tarihi"]) + ("  \n" + fat_durum if fat_durum else ""))
                                ar2.metric("Net Bakiye", f"{float(ar_row['Net_Bakiye'] or 0):,.2f} TL")
                                try:
                                    pdf_raw_ar = c.execute("SELECT PDF_Verisi FROM hesap_ekstreleri WHERE id=?", (int(ar_row["id"]),)).fetchone()
                                    if pdf_raw_ar and pdf_raw_ar[0]:
                                        pdf_bytes_ar = bytes(pdf_raw_ar[0]) if not isinstance(pdf_raw_ar[0], bytes) else pdf_raw_ar[0]
                                        ar3.download_button("📥 Ekstre PDF",
                                                            data=pdf_bytes_ar,
                                                            file_name=f"Ekstre_{ar_row['Klinik_Unvani']}_{ar_row['Baslangic_Tarihi']}.pdf",
                                                            mime="application/pdf", use_container_width=True,
                                                            key=f"ar_pdf_{ar_row['id']}")
                                except:
                                    ar3.caption("PDF yok")

                                if not fat_id_ar:
                                    if ar3.button("🗑️ Geri Çek", key=f"ar_geri_{ar_row['id']}", use_container_width=True, help="Ekstreyi iptal edip siler. Böylece hatalı ekstreyi düzenlemek için yeniden oluşturabilirsiniz."):
                                        try:
                                            c.execute("DELETE FROM hesap_ekstreleri WHERE id=?", (int(ar_row['id']),))
                                            conn.commit()
                                            st.success("Ekstre başarıyla iptal edildi!")
                                            st.rerun()
                                        except Exception as e_del:
                                            st.error(f"Silinemedi: {e_del}")

                                # Bağlı fatura varsa onu da göster
                                if fat_id_ar:
                                    try:
                                        fat_pdf_raw = c.execute("SELECT PDF_Verisi, Dosya_Adi FROM faturalar WHERE id=?", (int(fat_id_ar),)).fetchone()
                                        if fat_pdf_raw and fat_pdf_raw[0]:
                                            fat_pdf_bytes = bytes(fat_pdf_raw[0]) if not isinstance(fat_pdf_raw[0], bytes) else fat_pdf_raw[0]
                                            ar3.download_button("📥 Fatura PDF",
                                                                data=fat_pdf_bytes,
                                                                file_name=str(fat_pdf_raw[1] or "fatura.pdf"),
                                                                mime="application/pdf", use_container_width=True,
                                                                key=f"fat_ar_pdf_{fat_id_ar}")
                                    except:
                                        pass
                    else:
                        st.info("📭 Henüz arşivlenmiş ekstre bulunmuyor. 'Yeni Ekstre Oluştur' sekmesinden başlayın.")
                except Exception as e_arsiv2:
                    st.error(f"Arşiv yüklenemedi: {e_arsiv2}")


        with tab_finans_veri:
            st.markdown("#### 📊 Finans Veri Tabloları")
            alt_karlilik, alt_nakit = st.tabs(["📈 Gerçek Kârlılık", "🌊 Nakit Radarı"])

            with alt_karlilik:
                st.markdown("""<style>.cfo-card { background: linear-gradient(145deg, rgba(15, 23, 42, 0.8) 0%, rgba(30, 41, 59, 0.4) 100%); border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 16px; padding: 25px 15px; text-align: center; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.4); backdrop-filter: blur(10px); transition: transform 0.3s ease, border-color 0.3s ease; margin-bottom: 20px; } .cfo-card:hover { transform: translateY(-5px); border-color: rgba(56, 189, 248, 0.8); } .cfo-title { color: #94a3b8; font-size: 15px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 10px; } .cfo-val-blue { color: #38bdf8; font-size: 38px; font-weight: 900; text-shadow: 0 0 15px rgba(56,189,248,0.4); } .cfo-val-red { color: #f87171; font-size: 38px; font-weight: 900; text-shadow: 0 0 15px rgba(248,113,113,0.4); } .cfo-val-green { color: #34d399; font-size: 38px; font-weight: 900; text-shadow: 0 0 15px rgba(52,211,153,0.4); } .cfo-val-gray { color: #cbd5e1; font-size: 38px; font-weight: 900; } .cfo-sub { color: #64748b; font-size: 14px; font-weight: 600; margin-top: 8px; } .cfo-sub-down { color: #f87171; font-weight: bold; } .cfo-sub-up { color: #34d399; font-weight: bold; }</style>""", unsafe_allow_html=True)
            
                euro_kuru = guncel_euro_kuru_getir()
                try:
                    df_is_f = pd.read_sql("SELECT Klinik_Unvani, Is_Turu, Tutar_TL FROM isler WHERE Bakiye_Durumu='Aktarıldı'", conn)
                    if not df_is_f.empty:
                        df_is_f['Tutar_TL'] = pd.to_numeric(df_is_f['Tutar_TL'], errors='coerce')
                        toplam_gelir = df_is_f['Tutar_TL'].sum()
                    else: toplam_gelir = 0
                except: df_is_f = pd.DataFrame(); toplam_gelir = 0
            
                try:
                    df_tum_giderler = pd.read_sql("SELECT * FROM giderler", conn)
                    if not df_tum_giderler.empty:
                        gider_tur_kolonu = df_tum_giderler.columns[1] 
                        gider_tutar_kolonu = df_tum_giderler.columns[3]
                        df_tum_giderler[gider_tutar_kolonu] = pd.to_numeric(df_tum_giderler[gider_tutar_kolonu], errors='coerce')
                        toplam_sabit_gider = df_tum_giderler[gider_tutar_kolonu].sum()
                    else: toplam_sabit_gider = 0
                except: df_tum_giderler = pd.DataFrame(); toplam_sabit_gider = 0
            
                try: toplam_üye_sayısı = c.execute("SELECT sum(22 - Kalan_Uye) FROM cam_bloklar").fetchone()[0] or 1
                except: toplam_üye_sayısı = 1
                if toplam_üye_sayısı <= 0: toplam_üye_sayısı = 1
                
                try: frez_maliyeti_euro = c.execute("SELECT sum((CAST(kullanilan_dk AS FLOAT) / toplam_omur_dk) * birim_fiyat_euro) FROM aktif_frezler WHERE toplam_omur_dk > 0").fetchone()[0] or 0
                except: frez_maliyeti_euro = 0
                
                blok_maliyeti_tl = (toplam_üye_sayısı * 150)
                toplam_uretim_maliyeti = (frez_maliyeti_euro * euro_kuru) + blok_maliyeti_tl
                toplam_toplam_gider = toplam_sabit_gider + toplam_uretim_maliyeti
                net_kar = toplam_gelir - toplam_toplam_gider
            
                c_f1, c_f2, c_f3 = st.columns(3)
                c_f1.markdown(f'<div class="cfo-card"><div class="cfo-title">💎 Toplam Ciro</div><div class="cfo-val-blue">{toplam_gelir:,.0f} ₺</div><div class="cfo-sub">Klinik Hakedişleri</div></div>', unsafe_allow_html=True)
                c_f2.markdown(f'<div class="cfo-card"><div class="cfo-title">🔥 Toplam Maliyet</div><div class="cfo-val-red">{toplam_toplam_gider:,.0f} ₺</div><div class="cfo-sub"><span class="cfo-sub-down">▼ {toplam_uretim_maliyeti:,.0f} ₺</span> Üretim</div></div>', unsafe_allow_html=True)
                kar_class = "cfo-val-green" if net_kar > 0 else "cfo-val-red" if net_kar < 0 else "cfo-val-gray"
                kar_marji = int((net_kar/toplam_gelir)*100) if toplam_gelir > 0 else 0
                kar_sinif = "cfo-sub-up" if net_kar > 0 else "cfo-sub-down"
                c_f3.markdown(f'<div class="cfo-card"><div class="cfo-title">💰 Net Kâr / Zarar</div><div class="{kar_class}">{net_kar:,.0f} ₺</div><div class="cfo-sub"><span class="{kar_sinif}">%{kar_marji}</span> Net Marj</div></div>', unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                col_graf1, col_graf2 = st.columns(2)
            
                with col_graf1:
                    st.markdown("<h5 style='text-align:center; color:#e2e8f0;'>💸 GİDER DAĞILIMI</h5>", unsafe_allow_html=True)
                    if not df_tum_giderler.empty:
                        df_g_pasta = df_tum_giderler.groupby(gider_tur_kolonu)[gider_tutar_kolonu].sum().reset_index()
                        df_g_pasta.columns = ["Kategori", "Tutar"]
                    else: df_g_pasta = pd.DataFrame(columns=["Kategori", "Tutar"])
                
                    # Üretim maliyetini pastaya ekle
                    yeni_satir = pd.DataFrame({"Kategori": ["Üretim (Frez/Blok)"], "Tutar": [toplam_uretim_maliyeti]})
                    df_g_pasta = pd.concat([df_g_pasta, yeni_satir], ignore_index=True)
                
                    if df_g_pasta["Tutar"].sum() > 0:
                        fig_gider = px.pie(df_g_pasta, names="Kategori", values="Tutar", hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
                        fig_gider.update_traces(textposition='inside', textinfo='percent+label', insidetextfont=dict(color='white', size=14))
                        fig_gider.update_layout(template="plotly_dark", showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                        st.plotly_chart(fig_gider, use_container_width=True)

                with col_graf2:
                    st.markdown("<h5 style='text-align:center; color:#e2e8f0;'>🏆 EN KÂRLI KLİNİKLER</h5>", unsafe_allow_html=True)
                    if not df_is_f.empty:
                        klinik_ciro = df_is_f.groupby("Klinik_Unvani")["Tutar_TL"].sum().reset_index().sort_values(by="Tutar_TL", ascending=True)
                        fig_c = px.bar(klinik_ciro, x="Tutar_TL", y="Klinik_Unvani", orientation='h', color="Tutar_TL", color_continuous_scale="Tealgrn")
                        fig_c.update_traces(texttemplate='<b>%{x:,.0f} ₺</b>', textposition='outside')
                        fig_c.update_layout(template="plotly_dark", showlegend=False, coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(visible=False), yaxis=dict(title=""))
                        st.plotly_chart(fig_c, use_container_width=True)


            with alt_nakit:
                st.markdown("### 🌊 CFO Radarı: Nakit Akışı ve Gelecek Tahminleme (FP&A)")
                st.info("2. Madde (Bütçe Tahminleme) ve 3. Madde (Likidite/Tahsilat Yönetimi) prensiplerine göre çalışır.")
            
                euro_kuru = guncel_euro_kuru_getir()
                mevcut_ay = datetime.now().strftime("%Y-%m")
                bugun_gun = datetime.now().day
            
                try:
                    toplam_alacak = c.execute("SELECT sum(Bakiye) FROM cariler WHERE Bakiye > 0").fetchone()[0] or 0
                    bu_ay_tahsilat = c.execute(f"SELECT sum(Tutar) FROM tahsilatlar WHERE Tarih LIKE '{mevcut_ay}%'").fetchone()[0] or 0
                    bu_ay_fatura = c.execute(f"SELECT sum(Tutar_TL) FROM isler WHERE Bakiye_Durumu='Aktarıldı' AND Tarih LIKE '{mevcut_ay}%'").fetchone()[0] or 0
                    bu_ay_gider = c.execute(f"SELECT sum(Tutar) FROM giderler WHERE Tarih LIKE '{mevcut_ay}%'").fetchone()[0] or 0
                except: toplam_alacak, bu_ay_tahsilat, bu_ay_fatura, bu_ay_gider = 0, 0, 0, 0
                
                tahsilat_orani = (bu_ay_tahsilat / bu_ay_fatura * 100) if bu_ay_fatura > 0 else 0
            
                st.markdown("#### 💵 Nakit ve Alacak Yönetimi (Likidite)")
                n_col1, n_col2, n_col3 = st.columns(3)
                n_col1.metric("Piyasadaki Toplam Alacak", f"{toplam_alacak:,.2f} TL")
                n_col2.metric("Bu Ay Kesilen Fatura", f"{bu_ay_fatura:,.2f} TL")
                n_col3.metric("Bu Ay Giren Sıcak Para", f"{bu_ay_tahsilat:,.2f} TL", delta=f"%{tahsilat_orani:.1f} Başarı", delta_color="normal" if tahsilat_orani >= 70 else "inverse")
            
                st.markdown("<br>", unsafe_allow_html=True)
                n_graf1, n_graf2 = st.columns([2, 1.5])
                with n_graf1:
                    st.markdown("##### 🚨 En Çok Borcu Olan İlk 5 Klinik")
                    try:
                        df_borclular = pd.read_sql("SELECT Klinik_Unvani, Bakiye FROM cariler WHERE Bakiye > 0 ORDER BY Bakiye DESC LIMIT 5", conn)
                        if not df_borclular.empty:
                            fig_borc = px.bar(df_borclular, x="Bakiye", y="Klinik_Unvani", orientation='h', color="Bakiye", color_continuous_scale="Reds")
                            fig_borc.update_traces(texttemplate='<b>%{x:,.0f} ₺</b>', textposition='outside')
                            fig_borc.update_layout(template="plotly_dark", margin=dict(t=10, b=10, l=10, r=60), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis={'categoryorder':'total ascending', 'title': ''}, xaxis={'visible': False}, coloraxis_showscale=False)
                            st.plotly_chart(fig_borc, use_container_width=True)
                    except: pass
                
                with n_graf2:
                    st.markdown("##### 🌍 Kur Riski Simülatörü")
                    simule_kur = st.slider("Tahmini Euro Kuru (TL)", min_value=45.0, max_value=75.0, value=euro_kuru, step=0.5)
                    try: f_maliyet_euro = c.execute("SELECT sum((CAST(kullanilan_dk AS FLOAT) / toplam_omur_dk) * birim_fiyat_euro) FROM aktif_frezler WHERE toplam_omur_dk > 0").fetchone()[0] or 0
                    except: f_maliyet_euro = 0
                    simule_maliyet = f_maliyet_euro * simule_kur
                    fark = simule_maliyet - (f_maliyet_euro * euro_kuru)
                    st.markdown(f"<div class='cfo-card' style='border-color: {'#f87171' if fark > 0 else '#34d399'}; padding:20px;'><div class='cfo-sub'>Aylık Frez Maliyeti (Simüle):</div><div style='font-size:28px; font-weight:900; color:#f8fafc; margin: 10px 0;'>{simule_maliyet:,.0f} ₺</div><div style='color:{'#f87171' if fark > 0 else '#34d399'}; font-weight:700;'>Kur {simule_kur} ₺ olursa fark: +{fark:,.0f} ₺</div></div>", unsafe_allow_html=True)
                
                st.markdown("---")
                st.markdown("#### 🔮 Gelecek Tahminleme (Forecasting)")
                if bugun_gun > 0:
                    beklenen_ay_sonu_ciro = (bu_ay_fatura / bugun_gun) * 30
                    beklenen_ay_sonu_gider = (bu_ay_gider / bugun_gun) * 30
                    beklenen_net_kar = beklenen_ay_sonu_ciro - beklenen_ay_sonu_gider
                else: beklenen_ay_sonu_ciro, beklenen_ay_sonu_gider, beklenen_net_kar = 0, 0, 0
            
                f_col1, f_col2, f_col3 = st.columns(3)
                f_col1.metric("Ay Sonu Tahmini Ciro", f"{beklenen_ay_sonu_ciro:,.2f} TL")
                f_col2.metric("Ay Sonu Tahmini Gider", f"{beklenen_ay_sonu_gider:,.2f} TL")
                f_col3.metric("Tahmini Kapanış Kârı", f"{beklenen_net_kar:,.2f} TL", delta_color="normal" if beklenen_net_kar > 0 else "inverse")


    elif sayfa == "🛵 Kurye Lojistik":
        banner_olustur("🛵", "Kurye ve Lojistik Yönetimi", "Kliniklerden gelen teslim alma taleplerini yönetin ve kuryeleri yönlendirin.")
        df_kurye = pd.read_sql("SELECT * FROM kurye_islemleri ORDER BY Tarih DESC, Saat DESC", conn)
        
        bekleyenler_df = df_kurye[df_kurye['Durum'] == 'Bekliyor']
        if not bekleyenler_df.empty:
            st.error(f"🚨 **DİKKAT:** Şu an kliniklerde bekleyen **{len(bekleyenler_df)} adet** kurye talebi var!")
            
        tab_liste, tab_rota = st.tabs(["📋 Tüm Talepler ve Durum", "🗺️ Kaptan Rota & Maliyet İşleme"])
        
        with tab_liste:
            if not df_kurye.empty:
                df_goster = df_kurye.drop(columns=["id"])
                def kurye_renk(row):
                    if row['Durum'] == 'Bekliyor': return ['background-color: rgba(248, 113, 113, 0.2)'] * len(row)
                    elif row['Durum'] == 'Kurye Yolda': return ['background-color: rgba(56, 189, 248, 0.2)'] * len(row)
                    else: return ['background-color: rgba(16, 185, 129, 0.2)'] * len(row)
                st.dataframe(df_goster.style.apply(kurye_renk, axis=1), hide_index=True, use_container_width=True)
                
                st.markdown("---")
                k_sec = st.selectbox("İşlem Yapılacak Talebi Seçin", ["-- Seçiniz --"] + [f"ID:{r['id']} | {r['Klinik_Unvani']} - {r['Tarih']} {r['Saat']}" for _, r in df_kurye.iterrows()])
                if k_sec != "-- Seçiniz --":
                    s_id = int(k_sec.split("|")[0].replace("ID:", "").strip())
                    y_durum = st.radio("Durumu Güncelle", ["Bekliyor", "Kurye Yolda", "Teslim Alındı (Laboratuvara Geldi)"], horizontal=True)
                    if st.button("Durumu Kaydet", type="primary"):
                        c.execute("UPDATE kurye_islemleri SET Durum=? WHERE id=?", (y_durum, s_id))
                        conn.commit(); st.success("Kurye durumu güncellendi!"); st.rerun()
            else: st.info("Sistemde henüz kurye talebi bulunmuyor.")

        with tab_rota:
            bekleyenler = c.execute("SELECT DISTINCT Klinik_Unvani FROM kurye_islemleri WHERE Durum='Bekliyor'").fetchall()
            if bekleyenler:
                rota_adresleri = []
                for k in bekleyenler:
                    klinik_adi = k[0]
                    adres_sorgu = c.execute("SELECT Adres FROM cariler WHERE Klinik_Unvani=?", (klinik_adi,)).fetchone()
                    klinik_adresi = adres_sorgu[0] if adres_sorgu and adres_sorgu[0] != "-" else klinik_adi
                    rota_adresleri.append({"Klinik": klinik_adi, "Adres": klinik_adresi})
                
                base_url = "https://www.google.com/maps/dir/"
                for idx, durak in enumerate(rota_adresleri):
                    st.markdown(f"<div class='glass-card' style='border-left: 5px solid #38bdf8; margin-bottom: 10px;'><h4 style='color: #F3F4F6; margin:0;'>{idx + 1}. Durak: {durak['Klinik']}</h4><span style='color: #9CA3AF;'>🗺️ {durak['Adres']}</span></div>", unsafe_allow_html=True)
                    base_url += f"'{urllib.parse.quote(durak['Adres'])}'/"
                
                st.markdown(f"""<br><a href="{base_url}" target="_blank" class="wp-btn" style="background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);">🚀 Kurye İçin Google Haritalar'da Canlı Rotayı Başlat</a><br>""", unsafe_allow_html=True)
                
                st.markdown("---")
                with st.form("rota_tamamla_formu"):
                    col_m1, col_m2 = st.columns(2)
                    ulasim_tipi = col_m1.selectbox("Ulaşım / Kargo Tipi", ["Kurye Motoru (Yakıt)", "Kargo Firması", "Otobüs / Şehirlerarası"])
                    kurye_km = col_m2.number_input("Yapılan Toplam Mesafe (KM)", min_value=0.0, value=0.0)
                    toplam_maliyet = col_m1.number_input("Toplam Harcanan Maliyet (TL)", min_value=0.0, value=0.0, step=50.0)
                    ek_not = col_m2.text_input("Gider Açıklaması (Opsiyonel)")
                    
                    if st.form_submit_button("💸 Rotayı Kapat ve Masrafı Finans'a İşle"):
                        c.execute("UPDATE kurye_islemleri SET Durum='Teslim Alındı (Laboratuvara Geldi)' WHERE Durum='Bekliyor'")
                        gider_aciklamasi = f"ROTA KAPATILDI: {ulasim_tipi} | KM: {kurye_km} | Ek Not: {ek_not}"
                        c.execute("INSERT INTO giderler (Tarih, Kategori, Aciklama, Tutar) VALUES (?,?,?,?)", (datetime.now().strftime('%Y-%m-%d'), "Yakıt/Ulaşım/Kargo", gider_aciklamasi, toplam_maliyet))
                        conn.commit(); st.success(f"✅ Rota kapatıldı! {toplam_maliyet} TL Giderlere eklendi."); st.rerun()
            else: st.success("🎉 Harika! Bekleyen hiçbir rota yok.")

    elif sayfa == "📉 Maliyet Yönetimi":
            banner_olustur("📉", "Maliyet Yönetimi & Fiyat Listesi", "Birim maliyet analizi, hedef fiyat belirleme, hizmet bedellerini yönetme ve kurumsal döküman işlemleri.")
            
            # 🚨 ANA SEKMELER BURADA BAŞLIYOR 🚨
            tab_m2, tab_gider, tab1, tab2, tab3, tab4 = st.tabs(["⚙️ Değişken Ayarları", "💸 Giderler", "➕ Yeni Hizmet Ekle", "📊 Hizmet Listesi", "📁 Dökümanlar & Katalog", "💰 Hizmet Maliyet Tablosu"])
            with tab_gider:
                with st.container(border=True):
                    st.markdown("#### 💸 Genel Gider Girişi")
                    with st.form("gider_form"):
                        c1, c2 = st.columns(2)
                    
                        # 🚨 YENİ GİDER KATEGORİLERİ BURADA 🚨
                        kat = c1.selectbox("Gider Kategorisi", [
                            "Personel maaşları",
                            "Kira",
                            "Faturalar (Elektrik-Su-Doğalgaz-İnternet)",
                            "Yemek (Mutfak)",
                            "Yakıt/Ulaşım/Kargo",
                            "Hammadde (Blok, Metal tozu)",
                            "Sarf Malzeme",
                            "Teknik bakım/onarım",
                            "Diğer (Demirbaş, temizlik...)"
                        ], key="gid_tur")
                    
                        tut = c2.number_input("Tutar (TL)", min_value=0.0, step=100.0, key="gid_tut")
                        acik = st.text_input("Açıklama", key="gid_acik")
                        if st.form_submit_button("💸 Gideri Kaydet", type="primary") and tut > 0:
                            c.execute("INSERT INTO giderler (Tarih, Kategori, Aciklama, Tutar) VALUES (?,?,?,?)", (datetime.now().strftime("%Y-%m-%d"), kat, acik, tut))
                            conn.commit(); st.success("✅ Gider kaydedildi!"); st.rerun()
            
                st.markdown("#### 📑 Son Gider Hareketleri")
                df_giderler = pd.read_sql("SELECT * FROM giderler ORDER BY Tarih DESC", conn)
                st.dataframe(df_giderler, hide_index=True, use_container_width=True)
            
            
            # 🚨 TABLO İÇERİKLERİNİ ORTALAMAK İÇİN GENEL CSS ZIRHI 🚨
            st.markdown("""
<style>
            [data-testid="stDataFrame"] div[data-testid="stTable"] th {text-align: center !important;}
            [data-testid="stDataFrame"] div[data-testid="stTable"] td {text-align: center !important;}
            div[data-testid="stTable"] {text-align: center !important;}
</style>
            """, unsafe_allow_html=True)

            # ==========================================
            # TAB 1: YENİ HİZMET EKLEME
            # ==========================================
            with tab1:
                st.markdown("### ➕ Yeni Hizmet / İşlem Tanımla")
                col_f1, col_f2, col_f3, col_f_bos = st.columns([2.5, 1, 1, 2])
                
                with st.form("yeni_hizmet_form", clear_on_submit=True):
                    kat_sec = col_f1.selectbox("Kategori", KATEGORILER)
                    h_ad = col_f1.text_input("Hizmet / İşlem Adı", placeholder="Örn: Zirkonyum Kron")
                    
                    h_fiyat = col_f2.number_input("Birim Fiyat", min_value=0.0, step=10.0)
                    h_birim = col_f3.selectbox("Birim", ["Üye", "Adet", "Çene", "Gram"])
                    h_doviz = col_f2.selectbox("Para Birimi", ["Euro", "TL", "USD"])
                    
                    if st.form_submit_button("🚀 Hizmeti Listeye Ekle", type="primary"):
                        if h_ad:
                            c.execute("INSERT INTO fiyat_listesi (Kategori, Hizmet_Adi, Fiyat, Para_Birimi) VALUES (?,?,?,?)", (kat_sec, h_ad, h_fiyat, h_doviz))
                            conn.commit(); st.success(f"✅ {h_ad} başarıyla eklendi."); st.rerun()
            
            # ==========================================
            # TAB 2: MEVCUT HİZMET LİSTESİ
            # ==========================================
            with tab2:
                # 🚨 KLASÖR (EXPANDER) RENGİNİ AÇIK MAVİ YAPAN CSS ZIRHI 🚨
                st.markdown("""
<style>
                    /* Klasör açıldığında başlığın arka planını Açık Mavi yap ve yazıyı Siyah yap ki okunsun */
                    [data-testid="stExpander"] details[open] summary {
                        background-color: #38bdf8 !important; 
                        color: #0f172a !important; 
                        border-radius: 8px !important;
                        font-weight: 800 !important;
                    }
                    /* Klasör kapalıyken üzerine gelince (Hover) yazıyı mavi parlat */
                    [data-testid="stExpander"] details summary:hover {
                        color: #38bdf8 !important;
                    }
</style>
                """, unsafe_allow_html=True)

                st.markdown("### 📋 Mevcut Fiyat Tarifesi")
                df_fiyat = pd.read_sql("SELECT * FROM fiyat_listesi", conn)
                
                if not df_fiyat.empty:
                    for kat in KATEGORILER:
                        df_kat = df_fiyat[df_fiyat["Kategori"] == kat]
                        if not df_kat.empty:
                            with st.expander(f"📂 {kat} Listesi"):
                                
                                # 🚨 TABLOYU SOLA YASLAMAK VE DARALTMAK İÇİN YENİ KOLON YAPISI (Sol:3, Sağ:1.5) 🚨
                                col_t_ana, col_t_islemler = st.columns([3, 1.5])
                                
                                with col_t_ana:
                                    # 🚨 BOL SIFIRLARI KALDIRAN ( {:,.2f} ) VE ORTALAYAN KOD 🚨
                                    st.dataframe(
                                        df_kat[["Hizmet_Adi", "Fiyat", "Para_Birimi"]]
                                        .style.format({"Fiyat": "{:,.2f}"})
                                        .set_properties(**{'text-align': 'center'}),
                                        hide_index=True, 
                                        use_container_width=True
                                    )
                                
                                with col_t_islemler:
                                    st.markdown("##### ⚡ İşlemler")
                                    hizmet_sec = st.selectbox(f"Hizmet Seç ({kat})", ["— Seçiniz —"] + [f"{r['id']} | {r['Hizmet_Adi']}" for _, r in df_kat.iterrows()], key=f"sec_hizmet_{kat}")
                                    
                                    if hizmet_sec != "— Seçiniz —":
                                        h_id = hizmet_sec.split("|")[0].strip()
                                        h_mevcut = c.execute("SELECT Hizmet_Adi, Fiyat, Para_Birimi FROM fiyat_listesi WHERE id=?", (h_id,)).fetchone()
                                        
                                        if h_mevcut:
                                            with st.form(key=f"guncelle_form_{h_id}"):
                                                yeni_fiyat = st.number_input("Yeni Fiyat", value=float(h_mevcut[1]), step=10.0)
                                                pb_liste = ["Euro", "TL", "USD"]
                                                yeni_pb = st.selectbox("Para Birimi", pb_liste, index=pb_liste.index(h_mevcut[2]) if h_mevcut[2] in pb_liste else 1)
                                                
                                                c_btn1, c_btn2 = st.columns(2)
                                                if c_btn1.form_submit_button("💾 Güncelle", type="primary"):
                                                    c.execute("UPDATE fiyat_listesi SET Fiyat=?, Para_Birimi=? WHERE id=?", (yeni_fiyat, yeni_pb, h_id))
                                                    conn.commit()
                                                    st.success("Başarıyla güncellendi!")
                                                    
                                                if c_btn2.form_submit_button("🗑️ Sil"):
                                                    c.execute("DELETE FROM fiyat_listesi WHERE id=?", (h_id,))
                                                    conn.commit()
                                                    st.success("Başarıyla silindi!")
                else:
                    st.info("Sistemde henüz kayıtlı hizmet fiyatı bulunamadı.")



            # ==========================================
            # TAB 3: DÖKÜMANLAR & KATALOG
            # ==========================================
            with tab3:
                # CSS YAMASI: İndirme, Yükleme Butonları ve Sürükle-Bırak Alanı
                st.markdown("""
<style>
                    /* İndirme Butonu (Siber Mavi) */
                    [data-testid="stDownloadButton"] button { background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%) !important; border: none !important; box-shadow: 0 4px 15px rgba(14, 165, 233, 0.4) !important; border-radius: 10px !important; }
                    [data-testid="stDownloadButton"] button p { color: #FFFFFF !important; font-weight: 800 !important; }
                    [data-testid="stDownloadButton"] button:hover { transform: translateY(-2px) !important; box-shadow: 0 8px 25px rgba(14, 165, 233, 0.6) !important; }
                    
                    /* Dosya Yükleme Alanı (Sürükle-Bırak Dropzone) */
                    [data-testid="stFileUploaderDropzone"] { background-color: rgba(30, 41, 59, 0.6) !important; border: 2px dashed rgba(56, 189, 248, 0.5) !important; border-radius: 15px !important; transition: border 0.3s ease; }
                    [data-testid="stFileUploaderDropzone"]:hover { border-color: #8B5CF6 !important; background-color: rgba(30, 41, 59, 0.8) !important; }
                    
                    /* Browse Files (Dosya Seç) Butonu (Mor/Eflatun) */
                    [data-testid="stFileUploader"] button { background: linear-gradient(135deg, #8B5CF6 0%, #6D28D9 100%) !important; color: white !important; border: none !important; border-radius: 8px !important; box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4) !important; font-weight: 800 !important; }
                    [data-testid="stFileUploader"] button:hover { transform: translateY(-2px) !important; box-shadow: 0 8px 25px rgba(139, 92, 246, 0.6) !important; }
</style>
                """, unsafe_allow_html=True)

                st.markdown("### 📁 Kurumsal Döküman Arşivi")
                st.info("Katalog (PDF), Excel tabloları veya kurumsal evrakları buradan yükleyip saklayabilirsiniz.")
                
                # --- YÜKLEME ALANI ---
                with st.form("dokuman_yukle"):
                    d_ad = st.text_input("Döküman Adı (Örn: 2024 Ürün Kataloğu)")
                    yuklenen_dosya = st.file_uploader("Dosya Seçin (PDF, DOC, EXCEL, PPT, TXT, GÖRSEL)", type=["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "jpg", "png", "jpeg"])
                    if st.form_submit_button("🚀 Sunucuya Yükle"):
                        if yuklenen_dosya and d_ad:
                            klasor = "uploads/dokumanlar"
                            if not os.path.exists(klasor): os.makedirs(klasor)
                            yol = os.path.join(klasor, yuklenen_dosya.name)
                            yol = storage_utils.dosya_kaydet(os.path.dirname(yol), os.path.basename(yol), yuklenen_dosya)
                            
                            c.execute('''CREATE TABLE IF NOT EXISTS laboratuvar_dokumanlari (id SERIAL PRIMARY KEY, Tarih TEXT, Dokuman_Adi TEXT, Dosya_Yolu TEXT, Dosya_Turu TEXT)''')
                            c.execute("INSERT INTO laboratuvar_dokumanlari (Tarih, Dokuman_Adi, Dosya_Yolu, Dosya_Turu) VALUES (?,?,?,?)", (datetime.now().strftime("%Y-%m-%d"), d_ad, yol, yuklenen_dosya.type))
                            conn.commit(); st.success("Döküman arşive eklendi!"); st.rerun()
                
                st.markdown("---")
                
                # --- AKILLI ARAMA VE LİSTELEME ---
                try: df_dok = pd.read_sql("SELECT id, Dokuman_Adi, Tarih, Dosya_Yolu FROM laboratuvar_dokumanlari", conn)
                except: df_dok = pd.DataFrame() 
                
                if not df_dok.empty:
                    c_ara1, c_ara2 = st.columns([2, 1])
                    
                    belge_listesi = ["-- Tüm Belgeleri Göster --"] + df_dok['Dokuman_Adi'].tolist()
                    secilen_belge = c_ara1.selectbox("🔍 Anlık Akıllı Arama (Yazmaya başlayın...)", belge_listesi)
                    
                    if secilen_belge != "-- Tüm Belgeleri Göster --":
                        df_gosterim = df_dok[df_dok['Dokuman_Adi'] == secilen_belge]
                    else:
                        df_gosterim = df_dok
                    
                    st.subheader(f"📚 Bulunan Dökümanlar ({len(df_gosterim)} Sonuç)")
                    
                    for _, r in df_gosterim.iterrows():
                        with st.container(border=True):
                            col_d1, col_d2 = st.columns([3, 1])
                            col_d1.markdown(f"📄 **{r['Dokuman_Adi']}**")
                            
                            uzanti = str(r['Dosya_Yolu']).split('.')[-1].upper()
                            col_d1.caption(f"Yükleme Tarihi: {r['Tarih']} | Format: {uzanti}")
                            
                            if os.path.exists(r['Dosya_Yolu']):
                                with open(r['Dosya_Yolu'], "rb") as f: dosya_byte = f.read()
                                col_d2.download_button("📥 Bilgisayara İndir", dosya_byte, file_name=os.path.basename(r['Dosya_Yolu']), use_container_width=True, key=f"dl_{r['id']}")
                            else:
                                col_d1.error("Dosya sunucuda bulunamadı!")
                else: 
                    st.info("Sisteme henüz hiç kurumsal döküman veya katalog yüklenmemiş.")

            # ==========================================
            # TAB 4: HİZMET MALİYET TABLOSU
            # ==========================================
            with tab4:
                st.markdown("### 💰 Hizmet Maliyetleri ve Kâr Marjı Analizi")
                st.info("Buradan her bir hizmet için alt maliyet kalemlerini (ör. Zirkon Blok Payı, İşçilik) girerek hizmet başına net kârınızı hesaplayabilirsiniz.")
                
                df_fiyat = pd.read_sql("SELECT id, Hizmet_Adi, Fiyat, Para_Birimi FROM fiyat_listesi", conn)
                
                if not df_fiyat.empty:
                    hizmet_secenekler = [f"{r['id']} | {r['Hizmet_Adi']} ({r['Fiyat']} {r['Para_Birimi']})" for _, r in df_fiyat.iterrows()]
                    secilen_h_tam = st.selectbox("Maliyetini Yönetmek İstediğiniz Hizmeti Seçin", ["— Seçiniz —"] + hizmet_secenekler)
                    
                    if secilen_h_tam != "— Seçiniz —":
                        s_id = int(secilen_h_tam.split("|")[0].strip())
                        s_fiyat = df_fiyat[df_fiyat['id'] == s_id].iloc[0]['Fiyat']
                        s_pb = df_fiyat[df_fiyat['id'] == s_id].iloc[0]['Para_Birimi']
                        
                        st.markdown("---")
                        col_m1, col_m2 = st.columns([2, 1])
                        
                        with col_m1:
                            st.markdown("#### 🛒 Kayıtlı Maliyet Kalemleri")
                            maliyetler = pd.read_sql('SELECT id, kalem_adi as "Kalem Adı", tutar as "Tutar" FROM hizmet_maliyetleri WHERE hizmet_id=?', conn, params=(s_id,))
                            
                            if not maliyetler.empty:
                                # Show dataframe
                                m_goster = maliyetler.copy()
                                m_goster['Tutar'] = m_goster['Tutar'].apply(lambda x: f"{x:,.2f} {s_pb}")
                                st.dataframe(m_goster.drop(columns=["id"]), hide_index=True, use_container_width=True)
                                
                                # Silme mekanizması
                                st.markdown("##### 🗑️ Kalem Sil")
                                m_sec = st.selectbox("Silinecek Kalem", ["— Seçiniz —"] + [f"{r['id']} | {r['Kalem Adı']}" for _, r in maliyetler.iterrows()])
                                if m_sec != "— Seçiniz —":
                                    m_sil_id = m_sec.split("|")[0].strip()
                                    if st.button("Seçili Kalemi Sil", type="secondary"):
                                        c.execute("DELETE FROM hizmet_maliyetleri WHERE id=?", (m_sil_id,))
                                        conn.commit(); st.rerun()
                                
                                toplam_maliyet = maliyetler['Tutar'].sum()
                            else:
                                st.info("Bu hizmet için henüz maliyet kalemi eklenmemiş.")
                                toplam_maliyet = 0.0
                                
                        with col_m2:
                            st.markdown("#### ➕ Yeni Maliyet Ekle")
                            with st.form(key=f"maliyet_form_{s_id}", clear_on_submit=True):
                                yeni_kalem_adi = st.text_input("Gider Kalemi (Örn: İşçilik, Sarf Malzeme vb.)")
                                yeni_tutar = st.number_input(f"Tutar ({s_pb})", min_value=0.0, step=1.0)
                                if st.form_submit_button("Listeye Ekle", type="primary"):
                                    if yeni_kalem_adi and yeni_tutar > 0:
                                        c.execute("INSERT INTO hizmet_maliyetleri (hizmet_id, kalem_adi, tutar) VALUES (?,?,?)", (s_id, yeni_kalem_adi, yeni_tutar))
                                        conn.commit(); st.rerun()
                                    else:
                                        st.error("Lütfen geçerli bir isim ve tutar giriniz.")
                            
                            st.markdown("#### 🤖 Otonom Makine Maliyeti")
                            st.info("Seçilen makinenin saatlik güç tüketimi ve elektrik fiyatına göre maliyet hesaplar.")
                            
                            df_makineler = pd.read_sql("SELECT Cihaz_Adi, Guc_kW FROM cihazlar WHERE Durum='Aktif'", conn)
                            col_cihaz = df_makineler.columns[0] if not df_makineler.empty else 'Cihaz_Adi'
                            col_guc = df_makineler.columns[1] if not df_makineler.empty and len(df_makineler.columns) > 1 else 'Guc_kW'
                            
                            makine_isimleri = df_makineler[col_cihaz].tolist() if not df_makineler.empty else ["Genel Makine"]
                            
                            with st.form(key=f"otonom_maliyet_form_{s_id}"):
                                secili_mak = st.selectbox("Kullanılacak Makine", makine_isimleri)
                                makine_dk = st.number_input("İşlem ortalama kaç dakika sürüyor? (Dk)", min_value=0, step=1)
                                if st.form_submit_button("Otonom Hesapla ve Ekle"):
                                    if makine_dk > 0:
                                        # Seçili Makinenin kW Gücünü Bul
                                        if secili_mak != "Genel Makine" and not df_makineler.empty:
                                            kw_guc = df_makineler[df_makineler[col_cihaz] == secili_mak][col_guc].iloc[0]
                                        else:
                                            kw_guc = float(ayar_getir("Makine_Gucu_kW", "2.5"))
                                            
                                        # Elektrik Maliyeti (TL)
                                        kwh_fiyat = float(ayar_getir("Elektrik_kWh_Fiyati", "3.0"))
                                        elektrik_tl_maliyet = (kw_guc * kwh_fiyat) / 60.0 * makine_dk
                                        
                                        euro_kuru = guncel_euro_kuru_getir()
                                        
                                        if s_pb in ["EUR", "Euro"]:
                                            nihai_tutar = float(elektrik_tl_maliyet / euro_kuru if euro_kuru > 0 else 0)
                                        else: 
                                            nihai_tutar = float(elektrik_tl_maliyet)
                                            
                                        c.execute("INSERT INTO hizmet_maliyetleri (hizmet_id, kalem_adi, tutar) VALUES (?,?,?)", 
                                                  (s_id, f"Makine Üretimi - {secili_mak} ({makine_dk} Dk)", nihai_tutar))
                                        conn.commit(); st.rerun()
                                        
                            st.markdown("#### 📦 Otonom Malzeme (Stok) Maliyeti")
                            st.info("Seçilen malzemenin güncel depo fiyatı üzerinden otomatik canlı maliyet hesaplar.")
                            
                            df_stok_m = pd.read_sql("SELECT Urun_Adi, Birim FROM stok WHERE Durum='Aktif'", conn)
                            stok_isimleri = df_stok_m['Urun_Adi'].tolist() if not df_stok_m.empty else ["Genel Malzeme"]
                            
                            with st.form(key=f"otonom_stok_form_{s_id}"):
                                secili_stok = st.selectbox("Kullanılacak Malzeme", stok_isimleri)
                                
                                sf_col1, sf_col2 = st.columns([1, 2.5])
                                stok_adet = sf_col1.number_input("Miktar / Üye", min_value=0.0, step=0.1)
                                hesap_tipi = sf_col2.radio("Hesaplama Tipi", ["Manuel Miktar (Örn: 2 Adet Zirkon Blok)", "Tarihsel Ortalamaya Göre (Örn: 3 Üyelik İş)"])
                                
                                if st.form_submit_button("Stok Maliyeti Ekle"):
                                    if stok_adet > 0:
                                        birim_isim = "Adet"
                                        if secili_stok != "Genel Malzeme" and not df_stok_m.empty:
                                            b_vals = df_stok_m[df_stok_m['Urun_Adi'] == secili_stok]['Birim'].values
                                            if len(b_vals) > 0: birim_isim = str(b_vals[0])
                                            
                                        if "Ortalama" in hesap_tipi:
                                            kalem_ismi = f"Stok Tüketimi (Ortalama) - {secili_stok} ({stok_adet} Üye)"
                                        else:
                                            kalem_ismi = f"Stok Tüketimi (Miktar) - {secili_stok} ({stok_adet} {birim_isim})"
                                            
                                        c.execute("INSERT INTO hizmet_maliyetleri (hizmet_id, kalem_adi, tutar) VALUES (?,?,?)", (s_id, kalem_ismi, 0.0))
                                        conn.commit()
                                        otomatik_maliyetleri_guncelle()
                                        st.rerun()
                        
                        # Kâr Marjı Hesaplama Göstergesi
                        st.markdown("---")
                        st.markdown("#### 📊 Hizmet Başına Kârlılık Özeti")
                        kar_tutari = s_fiyat - toplam_maliyet
                        kar_yuzdesi = (kar_tutari / s_fiyat * 100) if s_fiyat > 0 else 0
                        
                        kc1, kc2, kc3, kc4 = st.columns(4)
                        kc1.metric("Satış Fiyatı", f"{s_fiyat:,.2f} {s_pb}")
                        kc2.metric("Toplam Maliyet", f"{toplam_maliyet:,.2f} {s_pb}")
                        
                        renk = "normal" if kar_tutari >= 0 else "inverse"
                        kc3.metric("Birim Kâr", f"{kar_tutari:,.2f} {s_pb}", delta=f"{kar_tutari:,.2f}", delta_color=renk)
                        kc4.metric("Kâr Marjı (%)", f"%{kar_yuzdesi:,.1f}", delta=f"%{kar_yuzdesi:,.1f}", delta_color=renk)
                        
                else:
                    st.warning("Önce 'Yeni Hizmet Ekle' sekmesinden bir fiyat listesi oluşturmanız gerekmektedir.")



            # 🚨 ZAMAN MAKİNESİ (AY/YIL FİLTRESİ) OLUŞTURMA 🚨
            try:
                # Hem işlerden hem giderlerden "YYYY-MM" (Yıl-Ay) formatında eşsiz tarihleri çekiyoruz
                aylar_is = pd.read_sql("SELECT DISTINCT substr(Tarih, 1, 7) as Ay FROM isler", conn)['Ay'].dropna().tolist()
                aylar_gid = pd.read_sql("SELECT DISTINCT substr(Tarih, 1, 7) as Ay FROM giderler", conn)['Ay'].dropna().tolist()
            
                # Tüm ayları birleştirip, tekrarları silip, en yeniden eskiye sıralıyoruz
                tum_aylar = sorted(list(set(aylar_is + aylar_gid)), reverse=True)
                secenekler = ["Genel (Tüm Zamanlar)"] + tum_aylar
            except:
                secenekler = ["Genel (Tüm Zamanlar)"]

            col_filtre1, col_filtre2 = st.columns([1.5, 3])
            secilen_ay = col_filtre1.selectbox("📅 Analiz Dönemini Seçin", secenekler)
        
            # 🚨 SEÇİLEN AYA GÖRE SQL FİLTRELERİNİ HAZIRLA 🚨
            if secilen_ay == "Genel (Tüm Zamanlar)":
                filtre_is = ""
                filtre_gid = ""
                col_filtre2.info("Şu an laboratuvarın açılışından bu yana olan TÜM veriler analiz ediliyor.")
            else:
                filtre_is = f"WHERE Tarih LIKE '{secilen_ay}%'"
                filtre_gid = f"WHERE Tarih LIKE '{secilen_ay}%'"
                col_filtre2.success(f"Şu an sadece **{secilen_ay}** ayının gelir ve giderleri analiz ediliyor.")

            # 1. TEMEL VERİLERİ ÇEK
            try: toplam_maas = c.execute("SELECT sum(Maas) FROM personeller WHERE Durum='Aktif'").fetchone()[0] or 0
            except: toplam_maas = 0
            
            euro_kuru = guncel_euro_kuru_getir()
        
            try: bgs_blok_euro = c.execute("SELECT Satis_Fiyati FROM stok WHERE Kategori LIKE '%Blok%' LIMIT 1").fetchone()[0] or 0
            except: bgs_blok_euro = 0
            bgs_blok_tl = bgs_blok_euro * euro_kuru

            # 2. DİNAMİK FREZ DAKİKA MALİYETİ
            try:
                df_frez = pd.read_sql("SELECT birim_fiyat_euro, toplam_omur_dk FROM aktif_frezler WHERE durum='Aktif'", conn)
                if not df_frez.empty and (df_frez['toplam_omur_dk'] > 0).all():
                    df_frez['dk_maliyet_euro'] = df_frez['birim_fiyat_euro'] / df_frez['toplam_omur_dk']
                    ortalama_dk_maliyet_euro = df_frez['dk_maliyet_euro'].mean()
                else:
                    ortalama_dk_maliyet_euro = 0.02 
            except:
                ortalama_dk_maliyet_euro = 0.02
        
            ortalama_dk_maliyet_tl = ortalama_dk_maliyet_euro * euro_kuru

            # 🚨 3. FİNANS MODÜLÜNDEN "SEÇİLEN AYA AİT" GİDERLERİ ÇEK 🚨
            try:
                sorgu_gider = f"SELECT Kategori, SUM(Tutar) as Toplam FROM giderler {filtre_gid} GROUP BY Kategori"
                df_giderler_ozet = pd.read_sql(sorgu_gider, conn)
                sabit_isletme_giderleri = df_giderler_ozet[df_giderler_ozet['Kategori'] != 'Hammadde']
                toplam_finans_gideri = sabit_isletme_giderleri['Toplam'].sum()
            except:
                sabit_isletme_giderleri = pd.DataFrame()
                toplam_finans_gideri = 0
            
            # 🚨 4. SEÇİLEN AYDAKİ GERÇEK ÜRETİM (İŞ) ADEDİNİ ÇEK 🚨
            try:
                sorgu_is_sayisi = f"SELECT COUNT(*) FROM isler {filtre_is}"
                gercek_is_adedi = c.execute(sorgu_is_sayisi).fetchone()[0] or 1
            except:
                gercek_is_adedi = 1

            # --- MODÜL ARAYÜZÜ ---

            with tab_m2:
                st.markdown(f"### 🏢 Otonom Gider ve Kapasite ({secilen_ay})")
                st.info("Bu sayfadaki veriler Finans modülünden seçtiğiniz aya göre anlık çekilir.")
            
                col_s1, col_s2 = st.columns(2)
            
                with col_s1:
                    st.markdown("##### 💸 Seçili Dönem Giderleri")
                    st.text_input("👥 Personel Maaş Yükü", value=f"{toplam_maas:,.2f} TL", disabled=True)
                
                    if not sabit_isletme_giderleri.empty:
                        for _, row in sabit_isletme_giderleri.iterrows():
                            st.text_input(f"📌 {row['Kategori']}", value=f"{row['Toplam']:,.2f} TL", disabled=True)
                    else:
                        st.warning(f"{secilen_ay} dönemi için kayıtlı finans gideri bulunmuyor.")
                
                    total_sabit_gider = toplam_maas + toplam_finans_gideri
                    st.markdown(f"**Toplam Sabit Yük: :red[{total_sabit_gider:,.2f} TL]**")
            
                with col_s2:
                    st.markdown("##### ⚙️ Kapasite ve Verimlilik")
                    aylik_is_adedi = st.number_input(f"{secilen_ay} Üretim Hacmi (Üye)", min_value=1, value=gercek_is_adedi, help="Seçilen dönemde yapılan toplam gerçek iş sayınız. Giderler buna bölünür.")
                    blok_verim = st.number_input("1 Bloktan Çıkan Üye", value=22)
                    uye_kazima_dk = st.number_input("1 Üye Ortalama Kazıma (Dakika)", value=15.0, step=1.0)
                
                    st.markdown("---")
                    st.markdown("##### ⚡ Enerji ve Sarf Giderleri")
                    mevcut_kwh = float(ayar_getir("Elektrik_kWh_Fiyati", "3.0"))
                    mevcut_guc = float(ayar_getir("Makine_Gucu_kW", "2.5"))
                
                    with st.form(key="enerji_ayarlari"):
                        yeni_kwh = st.number_input("1 kWh Elektrik Fiyatı (TL)", value=mevcut_kwh, step=0.1)
                        yeni_guc = st.number_input("Makine Saatlik Tüketimi (kW)", value=mevcut_guc, step=0.1)
                        if st.form_submit_button("Ayarları Kaydet"):
                            ayar_kaydet("Elektrik_kWh_Fiyati", yeni_kwh)
                            ayar_kaydet("Makine_Gucu_kW", yeni_guc)
                            st.success("Maliyet değişkenleri kaydedildi!")
                            st.rerun()

                    st.markdown("---")
                    st.markdown("#### 🔄 Frez Algoritması")
                    st.text_input("Frez Dakika Maliyeti", value=f"{ortalama_dk_maliyet_tl:,.2f} TL / Dk", disabled=True)


    elif sayfa == "🔧 Makine Parkuru ve Bakımı":
        banner_olustur("🔧", "Makine Parkuru ve Bakımı", "Makine ömürlerini uzatın, güç tüketimlerini analiz edin ve periyodik bakımları yönetin.")
        # 💎 GÖRSEL YAMA: Cihaz Modülü Yükleme Butonları 💎
        st.markdown("""
<style>
            [data-testid="stFileUploader"] button { background: linear-gradient(135deg, #8B5CF6 0%, #6D28D9 100%) !important; color: white !important; border: none !important; border-radius: 8px !important; box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4) !important; font-weight: 800 !important; }
            [data-testid="stFileUploaderDropzone"] { background-color: rgba(30, 41, 59, 0.6) !important; border: 2px dashed rgba(56, 189, 248, 0.5) !important; border-radius: 15px !important; transition: border 0.3s ease; }
            [data-testid="stFileUploaderDropzone"]:hover { border-color: #8B5CF6 !important; background-color: rgba(30, 41, 59, 0.8) !important; }
</style>
        """, unsafe_allow_html=True)
        tab_cihaz, tab_bakim, tab_yeni, tab_guncelle, tab_sil = st.tabs(["📊 Cihaz Durumları & Timer", "🔧 Bakım İşle", "➕ Yeni Cihaz Ekle", "✏️ Düzenle", "🗑️ Cihaz Sil"])
        
        with tab_cihaz:
            df_cihaz = pd.read_sql("SELECT * FROM cihazlar", conn)
            if not df_cihaz.empty:
                for idx, row in df_cihaz.iterrows():
                    with st.container(border=True):
                        col_img, col_info = st.columns([1, 3])
                        with col_img:
                            if row['Gorsel_Yolu'] != '-' and os.path.exists(row['Gorsel_Yolu']): st.image(row['Gorsel_Yolu'], use_container_width=True)
                            else: st.markdown("<div style='text-align:center; padding: 40px; background:#374151; border-radius:10px; color:#9CA3AF;'>📷<br>Görsel Yok</div>", unsafe_allow_html=True)
                        with col_info:
                            st.subheader(f"⚙️ {row['Cihaz_Adi']}")
                            guc = row.get('Guc_kW', 0.0)
                            st.caption(f"{row['Kategori']} | Güç: {guc} kW/h")
                            yuzde_saat = min(row['Calisma_Saati'] / row['Bakim_Siniri'], 1.0)
                            renk_saat = "#34D399" if yuzde_saat < 0.7 else "#FBBF24" if yuzde_saat < 0.9 else "#F87171"
                            st.markdown(f"**⚙️ Spindle / Çalışma Süresi Doluluk Oranı:** {row['Calisma_Saati']:.0f} / {row['Bakim_Siniri']:.0f} Saat")
                            st.markdown(f"""<div style="width: 100%; background-color: #374151; border-radius: 4px; margin-bottom:15px;"><div style="width: {yuzde_saat*100}%; height: 16px; background-color: {renk_saat}; border-radius: 4px;"></div></div>""", unsafe_allow_html=True)
                            col_t1, col_t2, col_t3 = st.columns(3)
                            with col_t1: st.markdown("<span style='color:#9CA3AF;'>🗓️ Haftalık</span>", unsafe_allow_html=True); st.markdown(timer_renk_hesapla(row['Haftalik_Hedef'], 7), unsafe_allow_html=True)
                            with col_t2: st.markdown("<span style='color:#9CA3AF;'>🗓️ Aylık</span>", unsafe_allow_html=True); st.markdown(timer_renk_hesapla(row['Aylik_Hedef'], 30), unsafe_allow_html=True)
                            with col_t3: st.markdown("<span style='color:#9CA3AF;'>🗓️ Yıllık</span>", unsafe_allow_html=True); st.markdown(timer_renk_hesapla(row['Yillik_Hedef'], 365), unsafe_allow_html=True)
            else: st.info("Kayıtlı cihaz bulunamadı.")
                
        with tab_bakim:
            cihaz_listesi = [row[0] for row in c.execute("SELECT Cihaz_Adi FROM cihazlar").fetchall()]
            if cihaz_listesi:
                secilen_cihaz = st.selectbox("İşlem Yapılacak Cihaz", cihaz_listesi)
                islem_tipi = st.radio("Yapılacak İşlem Türü", ["⏱️ Sadece Çalışma Saati Ekle", "🔧 Periyodik Donanım Bakımı Yapıldı", "♻️ Spindle / Kritik Parça Değişimi"], horizontal=False)
                
                eslesen_recete = []
                for anahtar, maddeler in BAKIM_RECELERI.items():
                    if anahtar in secilen_cihaz.lower():
                        eslesen_recete = maddeler
                        break
                
                yapilan_islem_metni = ""
                secilen_maddeler = []
                
                if eslesen_recete and "Saat Ekle" not in islem_tipi and "Değişimi" not in islem_tipi:
                    st.markdown(f"##### 🛠️ {secilen_cihaz} Özel Bakım Protokolü")
                    for m_idx, madde in enumerate(eslesen_recete):
                        if st.checkbox(madde, key=f"chk_{m_idx}"): secilen_maddeler.append(madde)
                    ek_aciklama = st.text_input("Ek Açıklama (Opsiyonel)")
                    yapilan_islem_metni = " | ".join(secilen_maddeler)
                    if ek_aciklama: yapilan_islem_metni += f" | Ek Not: {ek_aciklama}"
                elif "Saat Ekle" not in islem_tipi:
                    yapilan_islem_metni = st.text_input("Yapılan İşlem Detayı", placeholder="Sistemde özel reçetesi bulunamadı. Lütfen yapılan işlemi manuel yazın.")
                
                c_saat, c_maliyet = st.columns(2)
                saat_ekle = c_saat.number_input("Eklenecek Saat (Spindle/Baskı süresi)", min_value=0.0, value=0.0)
                bakim_maliyeti = c_maliyet.number_input("Bakım Maliyeti (TL)", min_value=0.0, value=0.0)
                
                if st.button("💳 Bakım İşlemini Kaydet", type="primary", use_container_width=True):
                    if "Bakımı Yapıldı" in islem_tipi and eslesen_recete and not secilen_maddeler:
                        st.error("⚠️ Bakımı kaydetmek için listedeki işlemlerden en az birini tamamlayıp işaretlemelisiniz!")
                    elif "Bakım" in islem_tipi and not eslesen_recete and not yapilan_islem_metni:
                        st.error("⚠️ Lütfen yapılan işlemi metin kutusuna yazınız!")
                    else:
                        mevcut_saat = c.execute("SELECT Calisma_Saati FROM cihazlar WHERE Cihaz_Adi=?", (secilen_cihaz,)).fetchone()[0]
                        bugun_str = datetime.now().strftime('%Y-%m-%d')
                        
                        if "Saat Ekle" in islem_tipi: 
                            c.execute("UPDATE cihazlar SET Calisma_Saati=? WHERE Cihaz_Adi=?", (mevcut_saat + saat_ekle, secilen_cihaz))
                        elif "Periyodik" in islem_tipi: 
                            c.execute("UPDATE cihazlar SET Calisma_Saati=?, Haftalik_Hedef=?, Aylik_Hedef=?, Son_Bakim_Tarihi=? WHERE Cihaz_Adi=?", (mevcut_saat + saat_ekle, (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d'), (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'), bugun_str, secilen_cihaz))
                        elif "Değişimi" in islem_tipi: 
                            c.execute("UPDATE cihazlar SET Calisma_Saati=0, Yillik_Hedef=?, Son_Bakim_Tarihi=? WHERE Cihaz_Adi=?", ((datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d'), bugun_str, secilen_cihaz))
                            yapilan_islem_metni = "Kritik Parça/Spindle Değişimi Yapıldı. Sayaç Sıfırlandı."
                        
                        if "Saat Ekle" not in islem_tipi:
                            c.execute("INSERT INTO cihaz_bakim_gecmisi (Cihaz_Adi, Tarih, Islem, Maliyet, Aciklama) VALUES (?,?,?,?,?)", (secilen_cihaz, bugun_str, yapilan_islem_metni, bakim_maliyeti, "Sistem Onaylı"))
                            if bakim_maliyeti > 0: c.execute("INSERT INTO giderler (Tarih, Kategori, Aciklama, Tutar) VALUES (?,?,?,?)", (bugun_str, "Fatura/Bakım", f"{secilen_cihaz}: {yapilan_islem_metni}", bakim_maliyeti))
                        
                        conn.commit(); st.success("✅ Makine bakımı başarıyla veri tabanına işlendi!"); st.rerun()

        with tab_yeni:
            with st.form("yeni_cihaz_formu"):
                c1, c2 = st.columns(2)
                c_adi = c1.text_input("Cihaz Adı / Markası")
                c_kat = c2.selectbox("Kategori", ["Kazıma Makinesi (Milling)", "Fırın (Sinter/Porselen)", "3D Yazıcı", "Tarayıcı (Scanner)", "Yardımcı Ekipman"])
                c_bakim_siniri = c1.number_input("Spindle/Parça Ömrü (Saat veya Döngü)", min_value=1.0, value=500.0)
                c_guc = c2.number_input("Saatlik Enerji Tüketimi (kW/h)", min_value=0.0, value=2.5, step=0.1)
                yuklenen_cihaz_gorsel = st.file_uploader("Makinenin Fotoğrafını Seç", type=["png", "jpg", "jpeg"])
                if st.form_submit_button("Cihazı Sisteme Ekle") and c_adi:
                    dosya_yolu = "-"
                    if yuklenen_cihaz_gorsel:
                        dosya_yolu = os.path.join("uploads", "cihazlar", f"{datetime.now().strftime('%H%M%S')}_{yuklenen_cihaz_gorsel.name}")
                        dosya_yolu = storage_utils.dosya_kaydet(os.path.dirname(dosya_yolu), os.path.basename(dosya_yolu), yuklenen_cihaz_gorsel)
                    bugun_str = datetime.now().strftime('%Y-%m-%d')
                    c.execute("INSERT INTO cihazlar (Cihaz_Adi, Kategori, Calisma_Saati, Bakim_Siniri, Son_Bakim_Tarihi, Durum, Gorsel_Yolu, Haftalik_Hedef, Aylik_Hedef, Yillik_Hedef, Guc_kW) VALUES (?,?,?,?,?,?,?,?,?,?,?)", 
                              (c_adi, c_kat, 0.0, c_bakim_siniri, bugun_str, "Aktif", dosya_yolu, (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d'), (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'), (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d'), c_guc))
                    conn.commit(); st.rerun()

        with tab_guncelle:
            st.markdown("<h4 style='color: #38BDF8;'>✏️ Kayıtlı Cihazı Düzenle</h4>", unsafe_allow_html=True)
            cihaz_listesi_guncelle = [row[0] for row in c.execute("SELECT Cihaz_Adi FROM cihazlar").fetchall()]
            if cihaz_listesi_guncelle:
                secilen_guncelle = st.selectbox("Düzenlenecek Cihazı Seçin", cihaz_listesi_guncelle, key="guncelle_secim")
                try: g_veri = c.execute("SELECT Cihaz_Adi, Kategori, Bakim_Siniri, Gorsel_Yolu, Guc_kW FROM cihazlar WHERE Cihaz_Adi=?", (secilen_guncelle,)).fetchone()
                except: 
                    g_veri = c.execute("SELECT Cihaz_Adi, Kategori, Bakim_Siniri, Gorsel_Yolu FROM cihazlar WHERE Cihaz_Adi=?", (secilen_guncelle,)).fetchone()
                    g_veri = (g_veri[0], g_veri[1], g_veri[2], g_veri[3], 0.0)
                
                with st.form("cihaz_guncelle_formu"):
                    c1, c2 = st.columns(2)
                    yeni_adi = c1.text_input("Cihaz Adı / Markası", value=g_veri[0])
                    
                    kategoriler_list = ["Kazıma Makinesi (Milling)", "Fırın (Sinter/Porselen)", "3D Yazıcı", "Tarayıcı (Scanner)", "Yardımcı Ekipman"]
                    idx_kat = kategoriler_list.index(g_veri[1]) if g_veri[1] in kategoriler_list else 0
                    yeni_kat = c2.selectbox("Kategori", kategoriler_list, index=idx_kat)
                    
                    yeni_sinir = c1.number_input("Spindle/Parça Ömrü (Saat veya Döngü)", min_value=1.0, value=float(g_veri[2]))
                    yeni_guc = c2.number_input("Saatlik Enerji Tüketimi (kW/h)", min_value=0.0, value=float(g_veri[4]), step=0.1)
                    yeni_gorsel = st.file_uploader("Yeni Fotoğraf Seç (Sadece değiştirmek istiyorsanız)", type=["png", "jpg", "jpeg"])
                    
                    if st.form_submit_button("💾 Değişiklikleri Kaydet"):
                        guncel_yol = g_veri[3]
                        if yeni_gorsel:
                            guncel_yol = os.path.join("uploads", "cihazlar", f"{datetime.now().strftime('%H%M%S')}_{yeni_gorsel.name}")
                            guncel_yol = storage_utils.dosya_kaydet(os.path.dirname(guncel_yol), os.path.basename(guncel_yol), yeni_gorsel)
                        
                        c.execute("UPDATE cihazlar SET Cihaz_Adi=?, Kategori=?, Bakim_Siniri=?, Gorsel_Yolu=?, Guc_kW=? WHERE Cihaz_Adi=?", (yeni_adi, yeni_kat, yeni_sinir, guncel_yol, yeni_guc, secilen_guncelle))
                        if yeni_adi != secilen_guncelle: c.execute("UPDATE cihaz_bakim_gecmisi SET Cihaz_Adi=? WHERE Cihaz_Adi=?", (yeni_adi, secilen_guncelle))
                        conn.commit(); st.success("✅ Cihaz bilgileri başarıyla güncellendi!"); st.rerun()
            else: st.info("Sistemde düzenlenecek kayıtlı cihaz bulunmuyor.")
                
        with tab_sil:
            st.markdown("<h4 style='color: #F87171;'>🗑️ Sistemden Cihaz Kaldır</h4>", unsafe_allow_html=True)
            st.warning("⚠️ DİKKAT: Bu işlem geri alınamaz. Cihaz ve o cihaza ait tüm bakım geçmişi tamamen silinir.")
            cihaz_listesi_sil = [row[0] for row in c.execute("SELECT Cihaz_Adi FROM cihazlar").fetchall()]
            if cihaz_listesi_sil:
                silinecek_cihaz = st.selectbox("Silinecek Cihazı Seçin", cihaz_listesi_sil)
                onay = st.checkbox("Bu cihazı kalıcı olarak silmeyi onaylıyorum.")
                if st.button("🗑️ Cihazı Sil", type="primary"):
                    if onay:
                        c.execute("DELETE FROM cihazlar WHERE Cihaz_Adi=?", (silinecek_cihaz,))
                        c.execute("DELETE FROM cihaz_bakim_gecmisi WHERE Cihaz_Adi=?", (silinecek_cihaz,))
                        conn.commit(); st.success(f"✅ {silinecek_cihaz} sistemden tamamen silindi!"); st.rerun()
                    else: st.error("Lütfen silme işlemini onaylayın.")

    # 💎 V2.8 KUSURSUZ AYARLAR MENÜSÜ (DİKEY YAPIDA) 💎
    elif sayfa == "🔐 Kullanıcı & Yetki Yönetimi":
        banner_olustur("🔐", "Kullanıcı & Yetki Yönetimi", "Sisteme giriş yapabilen personellerin erişim yetkilerini (rollerini) ve şifrelerini yönetin.")
        
        t1, t2 = st.tabs(["👥 Mevcut Kullanıcılar", "➕ Yeni Kullanıcı Tanımla"])
        
        with t1:
            st.markdown("### Sistemdeki Kullanıcılar")
            df_kullanicilar = pd.read_sql("SELECT id, Kullanici_Adi, Sifre, Rol FROM kullanicilar ORDER BY Kullanici_Adi ASC", conn)
            
            if not df_kullanicilar.empty:
                # SQLite ve Postgres arasındaki büyük/küçük harf farklılıklarını gidermek için kolonları standartlaştırıyoruz
                df_kullanicilar.columns = ["id", "Kullanici_Adi", "Sifre", "Rol"]
                
                df_gorsel = df_kullanicilar.copy()
                if rol == "Yönetici":
                    df_gorsel["Sifre"] = "***"
                df_gorsel.columns = ["ID", "Kullanıcı Adı", "Şifre", "Yetki Rolü"]
                st.dataframe(df_gorsel, hide_index=True, use_container_width=True)
                
                st.markdown("---")
                st.markdown("#### ⚡ Kullanıcı İşlemleri")
                secilen_kullanici = st.selectbox("İşlem Yapılacak Kullanıcı", ["-- Seçiniz --"] + df_kullanicilar['Kullanici_Adi'].tolist())
                
                if secilen_kullanici != "-- Seçiniz --":
                    mevcut = df_kullanicilar[df_kullanicilar['Kullanici_Adi'] == secilen_kullanici].iloc[0]
                    
                    c1, c2 = st.columns([2, 1])
                    with c1:
                        with st.form("kullanici_guncelle"):
                            st.subheader("Bilgileri Güncelle")
                            y_kadi = st.text_input("Kullanıcı Adı (Giriş ID)", value=mevcut['Kullanici_Adi'], disabled=True)
                            gosterilecek_sifre = "***" if rol == "Yönetici" else mevcut['Sifre']
                            y_sifre = st.text_input("Şifre", value=gosterilecek_sifre)
                            
                            roller = ["Admin", "Yönetici", "Sekreter", "Teknisyen", "Kurye", "Klinik", "Klinik_Asistan"]
                            r_index = 0
                            if mevcut['Rol'] in roller: r_index = roller.index(mevcut['Rol'])
                            y_rol = st.selectbox("Yetki Rolü", roller, index=r_index)
                            
                            if st.form_submit_button("💾 Kaydet", use_container_width=True):
                                c.execute("UPDATE kullanicilar SET Sifre=?, Rol=? WHERE Kullanici_Adi=?", (y_sifre, y_rol, mevcut['Kullanici_Adi']))
                                conn.commit(); st.success(f"{mevcut['Kullanici_Adi']} başarıyla güncellendi!"); st.rerun()
                                
                    with c2:
                        st.warning("Kullanıcıyı Tamamen Sil")
                        if st.button("🗑️ Kullanıcıyı Sil", type="primary", use_container_width=True):
                            if mevcut['Kullanici_Adi'] == 'tamer':
                                st.error("Sistemin kurucu hesabı ('tamer') silinemez!")
                            else:
                                c.execute("DELETE FROM kullanicilar WHERE Kullanici_Adi=?", (mevcut['Kullanici_Adi'],))
                                conn.commit(); st.success("Silindi!"); st.rerun()
            else:
                st.info("Sistemde kayıtlı kullanıcı bulunmuyor.")
                
        with t2:
            st.markdown("### Yeni Personel Kullanıcısı Aç")
            st.info("Not: Klinik (Hekim) girişleri 'Hekim ve Cari Kayıt' modülünden otomatik oluşturulur. Buradan sadece kendi laboratuvar personelinizi kaydedin.")
            with st.form("yeni_kullanici_ekle"):
                c1, c2 = st.columns(2)
                n_kadi = c1.text_input("Kullanıcı Adı (Sisteme giriş ID'si)")
                n_sifre = c2.text_input("Şifre")
                n_rol = st.selectbox("Yetki Rolü", ["Yönetici", "Admin", "Sekreter", "Teknisyen", "Kurye"])
                
                if st.form_submit_button("➕ Kullanıcıyı Sisteme Kaydet", type="primary"):
                    if n_kadi.strip() and n_sifre.strip():
                        var_mi = c.execute("SELECT count(*) FROM kullanicilar WHERE Kullanici_Adi=?", (n_kadi,)).fetchone()[0]
                        if var_mi > 0:
                            st.error("Bu kullanıcı adı başka bir personele ait, lütfen farklı bir isim seçin!")
                        else:
                            try:
                                c.execute("INSERT INTO kullanicilar (Kullanici_Adi, Sifre, Rol) VALUES (?,?,?)", (n_kadi.strip(), n_sifre.strip(), n_rol))
                                conn.commit(); st.success(f"Kullanıcı '{n_kadi}' eklendi!"); st.rerun()
                            except Exception as e:
                                st.error(f"Veritabanı hatası: {e}")
                    else:
                        st.warning("Lütfen kullanıcı adı ve şifre alanlarını boş bırakmayın!")

    elif sayfa == "⚙️ Ayarlar":
        banner_olustur("⚙️", "Sistem Ayarları", "Laboratuvarınızın siber ekosistemini, otonom kurallarını ve güvenliğini buradan yapılandırın.")
        
        ayarlar_menu = [
            "🏢 Kurumsal Kimlik", 
            "🎨 Görünüm Ayarları", 
            "💬 İletişim & Şablon", 
            "🖨️ Donanım Entegrasyonu", 
            "🗄️ Veri & Yedekleme", 
            "💰 Finansal Parametreler", 
            "🔐 Güvenlik", 
            "🌍 Dil Seçenekleri", 
            "💎 Lisans (PRO)", 
            "ℹ️ Sistem Hakkında"
        ]
        
        col_ayarlar_menu, col_ayarlar_icerik = st.columns([1, 3])
        
        with col_ayarlar_menu:
            st.markdown("<h4 style='color:#38bdf8; margin-top:0;'>⚙️ Ayar Modülleri</h4>", unsafe_allow_html=True)
            secilen_ayar = st.radio(" ", ayarlar_menu, label_visibility="collapsed")
            
        with col_ayarlar_icerik:
            with st.container(border=True):
                
                if secilen_ayar == "🏢 Kurumsal Kimlik":
                    # 💎 CSS YAMASI: Logo Yükleme Alanını Estetik Hale Getirir 💎
                    st.markdown("""
<style>
                        /* Sürükle-Bırak Alanı */
                        [data-testid="stFileUploaderDropzone"] { background-color: rgba(30, 41, 59, 0.6) !important; border: 2px dashed rgba(56, 189, 248, 0.5) !important; border-radius: 15px !important; }
                        [data-testid="stFileUploaderDropzone"]:hover { border-color: #8B5CF6 !important; background-color: rgba(30, 41, 59, 0.8) !important; }
                        
                        /* Browse Files Butonu (Mor) */
                        [data-testid="stFileUploader"] button { background: linear-gradient(135deg, #8B5CF6 0%, #6D28D9 100%) !important; color: white !important; border: none !important; border-radius: 8px !important; box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4) !important; font-weight: 800 !important; }
                        [data-testid="stFileUploader"] button:hover { transform: translateY(-2px) !important; box-shadow: 0 8px 25px rgba(139, 92, 246, 0.6) !important; }
</style>
                    """, unsafe_allow_html=True)
                    
                    st.markdown("### 🏢 Kurumsal Kimlik Ayarları")
                    st.info("Laboratuvarınızın belgelerde ve sistemde görünecek olan temel kimlik bilgilerini belirleyin.")
                    st.markdown("#### Genel & İletişim Bilgileri")
                    k_c1, k_c2, k_c3 = st.columns(3)
                    with k_c1:
                        y_lab_adi = st.text_input("Laboratuvar Adı", value=ayar_getir("Lab_Ad", "OMG Smile Sistem"))
                        y_lab_unvan = st.text_input("Ticaret Ünvanı", value=ayar_getir("Lab_Unvan", "Belirtilmemiş"))
                        y_lab_kurulus = st.text_input("Kuruluş Tarihi", value=ayar_getir("Lab_Kurulus_Tarihi", "Bilinmiyor"))
                        y_lab_sorumlu = st.text_input("Sorumlu Kişi", value=ayar_getir("Lab_Sorumlu_Kisi", "Belirtilmemiş"))
                    with k_c2:
                        y_lab_vergi_no = st.text_input("Vergi No", value=ayar_getir("Lab_Vergi_No", "Belirtilmemiş"))
                        y_lab_vergi_dairesi = st.text_input("Vergi Dairesi", value=ayar_getir("Lab_Vergi_Dairesi", "Belirtilmemiş"))
                        y_lab_iban = st.text_input("IBAN (Cari Hesap)", value=ayar_getir("Lab_IBAN", "TR00 0000 0000 0000 0000 0000 00"))
                        y_lab_kep = st.text_input("KEP Adresi", value=ayar_getir("Lab_Kep", "Belirtilmemiş"))
                    with k_c3:
                        y_lab_telefon = st.text_input("Telefon", value=ayar_getir("Lab_Telefon", "Belirtilmemiş"))
                        y_lab_email = st.text_input("E-Mail", value=ayar_getir("Lab_Email", "Belirtilmemiş"))
                        y_lab_web = st.text_input("Web Sitesi", value=ayar_getir("Lab_Web", "Belirtilmemiş"))
                        y_lab_adres = st.text_area("Adres", value=ayar_getir("Lab_Adres", "Belirtilmemiş"), height=68)
                    if st.button("Kurumsal Bilgileri Kaydet", type="primary", use_container_width=True):
                        ayar_kaydet("Lab_Ad", y_lab_adi)
                        ayar_kaydet("Lab_Unvan", y_lab_unvan)
                        ayar_kaydet("Lab_Kurulus_Tarihi", y_lab_kurulus)
                        ayar_kaydet("Lab_Sorumlu_Kisi", y_lab_sorumlu)
                        ayar_kaydet("Lab_Vergi_No", y_lab_vergi_no)
                        ayar_kaydet("Lab_Vergi_Dairesi", y_lab_vergi_dairesi)
                        ayar_kaydet("Lab_IBAN", y_lab_iban)
                        ayar_kaydet("Lab_Kep", y_lab_kep)
                        ayar_kaydet("Lab_Telefon", y_lab_telefon)
                        ayar_kaydet("Lab_Email", y_lab_email)
                        ayar_kaydet("Lab_Web", y_lab_web)
                        ayar_kaydet("Lab_Adres", y_lab_adres)
                        st.success("Kurumsal bilgiler başarıyla güncellendi!")
                        st.rerun()
                    st.markdown("---")
                    c_s1, c_s2 = st.columns(2)
                    with c_s1:
                        st.markdown("#### Barkod & Belge Ön Eki (Prefix)")
                        mevcut_onek = ayar_getir("Barkod_Onek", "OMG")
                        yeni_onek = st.text_input("Barkod ve Sertifikalar Nasıl Başlasın?", value=mevcut_onek)
                        st.caption(f"Örnek Görünüm: {yeni_onek}-0042")
                        if st.button("Ön Eki Kaydet", type="primary"):
                            ayar_kaydet("Barkod_Onek", yeni_onek)
                            st.success("Kaydedildi!")
                    with c_s2:
                        st.markdown("#### Logo (White-Label)")
                        
                        # Mevcut logoyu göster veya emojiyi hatırlat
                        suanki_logo = ayar_getir("Kurumsal_Logo", "-")
                        if suanki_logo != "-" and os.path.exists(suanki_logo):
                            st.image(suanki_logo, width=150, caption="Sistemde Aktif Logo")
                            if st.button("🗑️ Logoyu Kaldır (Eski Diş Emojisine Dön)", use_container_width=True):
                                ayar_kaydet("Kurumsal_Logo", "-")
                                st.success("Özel logo kaldırıldı. Efsanevi diş emojisi (🦷) tüm birimlerde tekrar aktif!")
                                st.rerun()
                        else:
                            st.info("Şu an varsayılan sistem emojisi (🦷) kullanılıyor.")

                        st.markdown("---")
                        logo_dosyasi = st.file_uploader("Yeni Logo Yükle (.png, .jpg)", type=["png", "jpg", "jpeg"], key="logo_yukle_main")
                        
                        if st.button("🚀 Yeni Logoyu Sisteme Giydir", use_container_width=True):
                            if logo_dosyasi:
                                kurumsal_yol = "uploads/kurumsal"
                                if not os.path.exists(kurumsal_yol): os.makedirs(kurumsal_yol)
                                
                                # 💎 HATA ÇÖZÜMÜ: Dosyanın gerçek uzantısını (.jpg, .png) otomatik bulur 💎
                                gercek_uzanti = str(logo_dosyasi.name).split('.')[-1].lower()
                                dosya_adi = f"sistem_logosu_{datetime.now().strftime('%H%M%S')}.{gercek_uzanti}"
                                
                                tam_yol = os.path.join(kurumsal_yol, dosya_adi)
                                tam_yol = storage_utils.dosya_kaydet(os.path.dirname(tam_yol), os.path.basename(tam_yol), logo_dosyasi)
                                ayar_kaydet("Kurumsal_Logo", tam_yol)
                                st.success(f"✅ Kurumsal logo ({gercek_uzanti.upper()} formatında) başarıyla güncellendi!")
                                st.rerun()
                            else:
                                st.error("Lütfen önce bir logo dosyası seçin!")
                        
                elif secilen_ayar == "🎨 Görünüm Ayarları":
                    st.markdown("### 🎨 Ekran ve Widget Ayarları")
                    st.info("Komuta Merkezinde görünmesini istediğiniz modülleri buradan açıp kapatabilirsiniz.")
                    st.session_state.w_ciro = st.checkbox("Yapay Zeka CFO & Finans Kartlarını Göster", value=st.session_state.w_ciro)
                    st.session_state.w_radar = st.checkbox("Canlı Üretim Radarını Göster", value=st.session_state.w_radar)
                    st.session_state.w_grafikler = st.checkbox("Analitik Grafikleri Göster", value=st.session_state.w_grafikler)
                    st.markdown("---")
                    st.markdown("#### 🖼️ Arkaplan Teması")
                    st.selectbox("Tema Seçimi (Yakında)", ["Cyberpunk Dark (Aktif)", "Clean Light", "Deep Blue Ocean"])
                    
                elif secilen_ayar == "💬 İletişim & Şablon":
                    st.markdown("### 💬 Dinamik Mesaj Şablonları")
                    st.info("WhatsApp modülü üzerinden hekimlere giden otomatik bildirim metinlerini kişiselleştirin.")
                    mevcut_sablon = ayar_getir("Kurye_Sablonu", "Sayın [Hekim_Adı],\nKurye talebiniz alınmıştır. Kuryemiz en kısa sürede adresinize yönlendirilecektir.\nTeşekkür ederiz.")
                    yeni_sablon = st.text_area("Kurye Bildirim Şablonu", value=mevcut_sablon, height=100)
                    st.caption("Kullanabileceğiniz etiketler: [Hekim_Adı], [Klinik_Unvanı]")
                    if st.button("Şablonu Kaydet", type="primary"):
                        ayar_kaydet("Kurye_Sablonu", yeni_sablon)
                        st.success("WhatsApp Kurye şablonu güncellendi!")
                    st.markdown("---")
                    st.markdown("#### 🤫 Sessiz Saatler")
                    sessiz_saat = st.selectbox("Sistemin otomatik SMS/Mesaj atmasını engelleyin:", ["Kapalı", "20:00 - 08:00", "22:00 - 08:00"])
                    if st.button("Saatleri Uygula"):
                        ayar_kaydet("Sms_Sessiz_Saatler", sessiz_saat)
                        st.success(f"Sessiz saatler ayarlandı: {sessiz_saat}")
                        
                elif secilen_ayar == "🖨️ Donanım Entegrasyonu":
                    st.markdown("### 🖨️ Çevre Birimleri ve Donanım")
                    st.info("Barkod yazıcı, tarayıcı (Scanner) ve lobi televizyonu gibi harici donanımların entegrasyonu.")
                    c_d1, c_d2 = st.columns(2)
                    with c_d1:
                        st.markdown("#### Barkod Yazıcı Kalibrasyonu")
                        st.selectbox("Kullanılan Yazıcı Tipi", ["Standart (A4 Lazer)", "Xprinter / Zebra Termal", "Dymo Termal"])
                        st.selectbox("Etiket Boyutu", ["40x20 mm", "50x30 mm", "70x40 mm"])
                        st.button("Sınama Sayfası Yazdır")
                    with c_d2:
                        st.markdown("#### Lobi Ekranı (Kiosk) Yayını")
                        mevcut_ip = ayar_getir("Lobi_IP", "192.168.1.100")
                        yeni_ip = st.text_input("Televizyon / Kiosk IP Adresi", value=mevcut_ip)
                        if st.button("IP Kaydet ve Yayınla", type="primary"):
                            ayar_kaydet("Lobi_IP", yeni_ip)
                            st.success(f"Lobi radarı {yeni_ip} adresine yönlendirildi.")
                            
                elif secilen_ayar == "🗄️ Veri & Yedekleme":
                    # 💎 CSS YAMASI: İndirme butonlarının görünmez olma sorununu Zümrüt Yeşili ile çözer 💎
                    st.markdown("""
<style>
                        [data-testid="stDownloadButton"] button { background: linear-gradient(135deg, #10B981 0%, #059669 100%) !important; border: none !important; box-shadow: 0 4px 15px rgba(16, 185, 129, 0.4) !important; border-radius: 10px !important;}
                        [data-testid="stDownloadButton"] button p { color: #FFFFFF !important; font-weight: 900 !important; }
                        [data-testid="stDownloadButton"] button:hover { transform: translateY(-2px) !important; box-shadow: 0 8px 25px rgba(16, 185, 129, 0.6) !important; }
</style>
                    """, unsafe_allow_html=True)
                    
                    st.markdown("### 🗄️ Veri ve Arşiv Yönetimi")
                    st.info("Sistemin veritabanını dışa aktarın, tam yedeğini alın veya gereksiz depolamaları temizleyin.")
                    
                    st.markdown("#### 📥 Veritabanını Excel (CSV) Olarak Dışa Aktar")
                    yedek_secim = st.selectbox("İndirmek İstediğiniz Tabloyu Seçin:", ["İşler (Reçete ve Üretim)", "Klinikler (Cari Kartlar)", "Güncel Stok Envanteri", "Finans (Giderler)", "Finans (Tahsilatlar)", "Personel Özlük"])
                    
                    if yedek_secim == "İşler (Reçete ve Üretim)": df_export = pd.read_sql("SELECT * FROM isler", conn); dosya_adi = "omg_isler.csv"
                    elif yedek_secim == "Klinikler (Cari Kartlar)": df_export = pd.read_sql("SELECT * FROM cariler", conn); dosya_adi = "omg_klinikler.csv"
                    elif yedek_secim == "Güncel Stok Envanteri": df_export = pd.read_sql("SELECT * FROM stok", conn); dosya_adi = "omg_stok.csv"
                    elif yedek_secim == "Finans (Giderler)": df_export = pd.read_sql("SELECT * FROM giderler", conn); dosya_adi = "omg_giderler.csv"
                    elif yedek_secim == "Finans (Tahsilatlar)": df_export = pd.read_sql("SELECT * FROM tahsilatlar", conn); dosya_adi = "omg_tahsilatlar.csv"
                    elif yedek_secim == "Personel Özlük": df_export = pd.read_sql("SELECT * FROM personeller", conn); dosya_adi = "omg_personel.csv"
                    
                    # Türkçe karakter (BOM) ve noktalı virgül desteği
                    csv_data = df_export.to_csv(index=False, sep=";").encode('utf-8-sig')
                    st.download_button(label=f"📊 {yedek_secim} Tablosunu İndir", data=csv_data, file_name=dosya_adi, mime="text/csv")
                    
                    st.markdown("---")
                    c_v1, c_v2 = st.columns(2)
                    with c_v1:
                        st.markdown("#### 💾 Tam Sistem Yedekleme (Çelik Kasa)")
                        st.info("Laboratuvarın tüm veritabanı dosyasını tek tıkla güvence altına alıp flash belleğe atabilirsiniz.")
                        try:
                            with open("omg_smile_erp.db", "rb") as f:
                                st.download_button("🛡️ Ana Veritabanını (.db) İndir", f, file_name=f"omg_ana_yedek_{datetime.now().strftime('%Y%m%d')}.db")
                        except: st.error("Veritabanı dosyasına şu an ulaşılamıyor.")
                        
                        st.markdown("#### ☁️ Otomatik Bulut Yedekleme")
                        st.selectbox("Yedekleme Frekansı", ["Kapalı", "Günde 1 Kez (Gece)", "12 Saatte Bir", "Her Saat Başı"])
                        if st.button("Şimdi Buluta Yedekle (Google Drive)"):
                            st.success("Yedekleme komutu verildi! (Not: Google Drive Masaüstü uygulamasının kurulu olduğundan emin olun).")
                            
                    with c_v2:
                        st.markdown("#### 🧹 Sunucu Temizliği")
                        st.warning("Eski 3D (STL) dosyalarını silerek sunucu alanında yer açın.")
                        st.selectbox("Silinecek Dosyalar", ["1 Yıldan Eskiler", "2 Yıldan Eskiler", "3 Yıldan Eskiler"])
                        if st.button("Seçilenleri Sil"):
                            st.success("Temizlik işlemi başlatıldı.")

                        st.markdown("---")
                        st.markdown("#### 🔄 Hata Düzeltme & İadeler")
                        st.caption("Eskiden silinmiş işlere ait blok ve frez sarfiyatlarını tespit edip stoğa/ömre geri yükler.")
                        if st.button("Silinen İşlerin Sarfiyatlarını (Blok & Frez) İade Et", type="primary"):
                            try:
                                import db_baglanti
                                conn2 = db_baglanti.get_connection()
                                c2 = conn2.cursor()
                                c2.execute('''SELECT is_id, malzeme_turu, malzeme_kodu, uye_sayisi, dakika 
                                             FROM uretim_loglari 
                                             WHERE is_id NOT IN (SELECT id FROM isler)''')
                                orphaned_logs = c2.fetchall()
                                if not orphaned_logs:
                                    st.success("İade edilecek askıda kalmış sarfiyat (Blok veya Frez) bulunamadı.")
                                else:
                                    blok_iade = 0
                                    frez_iade = 0
                                    for log in orphaned_logs:
                                        is_id, m_turu, m_kodu, m_uye, m_dk = log
                                        if m_turu == 'Blok':
                                            c2.execute("SELECT Kalan_Uye FROM cam_bloklar WHERE Blok_Kodu=?", (m_kodu,))
                                            mevcut_blok = c2.fetchone()
                                            if mevcut_blok:
                                                yeni_kalan = mevcut_blok[0] + m_uye
                                                c2.execute("UPDATE cam_bloklar SET Kalan_Uye=?, Durum='Yarım' WHERE Blok_Kodu=?", (yeni_kalan, m_kodu))
                                                blok_iade += 1
                                        elif m_turu == 'Frez':
                                            c2.execute("SELECT kullanilan_dk FROM aktif_frezler WHERE frez_kod=? AND durum!='Kırıldı' AND durum!='Ömrü Doldu'", (m_kodu,))
                                            mevcut_frez = c2.fetchone()
                                            if mevcut_frez:
                                                yeni_kullanilan = max(0, mevcut_frez[0] - m_dk)
                                                c2.execute("UPDATE aktif_frezler SET kullanilan_dk=? WHERE frez_kod=? AND durum!='Kırıldı' AND durum!='Ömrü Doldu'", (yeni_kullanilan, m_kodu))
                                                frez_iade += 1
                                        
                                        # İşlendiğine dair logu sil
                                        c2.execute("DELETE FROM uretim_loglari WHERE is_id=? AND malzeme_turu=? AND malzeme_kodu=?", (is_id, m_turu, m_kodu))
                                    conn2.commit()
                                    st.success(f"Başarılı! Toplam {blok_iade} adet blok ve {frez_iade} adet frez sarfiyatı geri yüklendi.")
                            except Exception as e:
                                st.error(f"Hata: {e}")
                        
                elif secilen_ayar == "💰 Finansal Parametreler":
                    st.markdown("### 💰 Finansal Parametreler")
                    st.info("Laboratuvarınızın vergi, döviz ve mali standartlarını sisteme öğretin.")
                    c_f1, c_f2 = st.columns(2)
                    with c_f1:
                        mevcut_pb = ayar_getir("Para_Birimi", "TL")
                        yeni_pb = st.selectbox("Sistemin Ana Para Birimi", ["TL", "EUR", "USD"], index=["TL", "EUR", "USD"].index(mevcut_pb))
                        if st.button("Para Birimini Değiştir", type="primary"):
                            ayar_kaydet("Para_Birimi", yeni_pb)
                            st.success("Tüm sistemin para birimi güncellendi!")
                    with c_f2:
                        mevcut_kdv = ayar_getir("KDV_Orani", "20")
                        yeni_kdv = st.number_input("Varsayılan KDV Oranı (%)", min_value=0, max_value=100, value=int(mevcut_kdv))
                        if st.button("KDV Oranını Kaydet", type="primary"):
                            ayar_kaydet("KDV_Orani", yeni_kdv)
                            st.success("KDV ayarları işlendi!")
                            
                elif secilen_ayar == "🔐 Güvenlik":
                    st.markdown("### 🔐 Güvenlik & Denetim İzi (Log)")
                    st.markdown("---")
                    st.markdown("### 🚨 SİBER GÜVENLİK PROTOKOLÜ (PANİK BUTONU)")
                    st.error("DİKKAT: Bu butona basıldığında sistemdeki tüm klinikler, asistanlar ve kuryeler anında dışarı atılır. Sistem tamamen 'Bakım/Kilitli' moduna geçer. Sadece 'Admin' hesabıyla tekrar giriş yapılıp bu kilidi açabilirsiniz.")
                    
                    suanki_kilit_durumu = ayar_getir("Sistem_Kilitli", "Hayır")
                    if suanki_kilit_durumu == "Hayır":
                        if st.button("🚨 SİSTEMİ ACİL KİLİTLE", use_container_width=True):
                            ayar_kaydet("Sistem_Kilitli", "Evet")
                            st.success("SİSTEM KİLİTLENDİ! Yabancı girişler engellendi."); st.rerun()
                    else:
                        st.warning("⚠️ SİSTEM ŞU AN KİLİTLİ (GÜVENLİK MODU AKTİF)")
                        if st.button("✅ KİLİDİ AÇ VE SİSTEMİ NORMALE DÖNDÜR", use_container_width=True, type="primary"):
                            ayar_kaydet("Sistem_Kilitli", "Hayır")
                            st.success("SİSTEM KİLİDİ AÇILDI!"); st.rerun()
                    st.markdown("---")
                    st.markdown("#### 🔑 Şifre Değiştirme")
                    col_s1, col_s2 = st.columns([1, 1])
                    with col_s1:
                        with st.form("sifre_degistir_form_ayarlar"):
                            eski_s = st.text_input("Mevcut Şifreniz", type="password")
                            yeni_s = st.text_input("Yeni Şifre Belirleyin", type="password")
                            if st.form_submit_button("Şifreyi Güncelle", type="primary", use_container_width=True):
                                gercek_eski = c.execute("SELECT Sifre FROM kullanicilar WHERE Kullanici_Adi=?", (kullanici_adi,)).fetchone()[0]
                                if eski_s == gercek_eski: 
                                    c.execute("UPDATE kullanicilar SET Sifre=? WHERE Kullanici_Adi=?", (yeni_s, kullanici_adi))
                                    conn.commit(); st.success("Şifreniz başarıyla değiştirildi!")
                                else: st.error("Eski şifre hatalı!")
                    st.markdown("---")
                    st.markdown("#### 📱 İki Aşamalı Doğrulama (2FA)")
                    st.info("Yönetici hesaplarına girişte cep telefonuna gelen SMS kodunu zorunlu kılın.")
                    st.checkbox("2FA Sistemini Aktifleştir (SMS Modülü Gerektirir)")
                    
                elif secilen_ayar == "🌍 Dil Seçenekleri":
                    st.markdown("### 🌍 Sistem Dili")
                    st.selectbox("Kullanılacak Dili Seçin", ["Türkçe (Aktif)", "English (Yakında)", "Deutsch (Yakında)"])
                    st.info("Çoklu dil desteği global sürüm ile birlikte aktif edilecektir.")
                    
                elif secilen_ayar == "💎 Lisans (PRO)":
                    st.markdown("### 💎 PRO Lisans Yönetimi")
                    st.info("Sistem şu an Altın Sürüm (Sınırsız) modunda çalışmaktadır. Ticari lisanslama altyapısı bu alana eklenecektir.")
                    st.text_input("Lisans Anahtarı", disabled=True, placeholder="OMG-PRO-XXXX-XXXX")
                    st.button("Lisansı Aktifleştir", disabled=True)
                    
                elif secilen_ayar == "ℹ️ Sistem Hakkında":
                    st.markdown("### ℹ️ Yazılım Bilgileri")
                    st.markdown("""
                    <div class='glass-card'>
                        <h2 class='neon-text-blue' style='margin:0;'>OMG Smile Dijital Ekosistem</h2>
                        <p><b>Sürüm:</b> v3.6 (Altın Sürüm - Hekim Otopilotu)</p>
                        <p>Bu program Omg Smile dijital diş laboratuvarında geliştirilmiştir.</p>
                        <p><b>Altyapı:</b> Python, Streamlit, SQLite, OMG AI</p>
                        <p style="color:#94a3b8; font-size:12px; margin-top:20px;">Telif Hakkı © 2026 Tüm Hakları Saklıdır.</p>
                    </div>
                    """, unsafe_allow_html=True)

    elif sayfa == "🤖 OMG AI Asistan":
        # 🚨 CYBER-TEAL TEXTBOX ZIRHI - DÜZELTİLMİŞ (OK VE KUTU YAN YANA) 🚨
        st.markdown("""
<style>
            /* 1. İçerideki o iğrenç beyaz arka planı tamamen kazıyoruz */
            [data-testid="stChatInput"] div {
                background-color: transparent !important;
            }
            
            /* 2. Textarea ve Butonu yan yana tutan ANA KASA */
            [data-testid="stChatInput"] > div {
                background-color: #050505 !important; /* Simsiyah zemin */
                border: 1px solid #00FFFF !important; /* Turkuaz Çerçeve */
                border-radius: 10px !important;
                box-shadow: 0 0 8px rgba(0, 255, 255, 0.2) !important;
                display: flex !important;
                flex-direction: row !important; /* 🚨 OK VE YAZIYI YAN YANA DİZ 🚨 */
                align-items: center !important; /* Ok'u dikeyde tam ortala */
                padding-right: 8px !important;
            }
            
            /* 3. Focus (Kutunun içine tıklayınca) parlama efekti */
            [data-testid="stChatInput"] > div:focus-within {
                border: 2px solid #00FFFF !important;
                box-shadow: 0 0 20px rgba(0, 255, 255, 0.6) !important;
            }

            /* 4. Textarea'nın (Yazı yazdığımız yerin) ayarları */
            [data-testid="stChatInput"] textarea {
                color: #166534 !important; /* Koyu Askeri Yeşil Yazı */
                font-family: 'Courier New', Courier, monospace !important;
                font-weight: 600 !important;
                border: none !important;
                box-shadow: none !important;
            }

            /* 5. Örnek Metin (Placeholder) Rengi */
            [data-testid="stChatInput"] textarea::placeholder {
                color: #052e16 !important;
            }

            /* 6. Gönder Butonu (Turkuaz Ok) */
            [data-testid="stChatInput"] button {
                color: #00FFFF !important;
                background-color: transparent !important;
                border: none !important;
                margin-bottom: 0px !important; /* Oku aşağı iten boşluğu yok et */
            }
            [data-testid="stChatInput"] svg {
                fill: #00FFFF !important;
            }
</style>
        """, unsafe_allow_html=True)

        st.sidebar.success("🔥 Sürüm: V3 - Renk Sistemi Aktif")
        st.title("🤖 OMG AI - Laboratuvar Zekası")
        st.markdown("Merhaba Hocam! Laboratuvarın tüm finansal, üretim ve stok verileri anlık olarak beynimde. Bana ne sormak istersiniz?")
        
        if "mesajlar" not in st.session_state:
            st.session_state.mesajlar = [{"role": "assistant", "content": "Hocam, size raporları hazırlamak için hazırım. Aşağıdaki hızlı butonları kullanabilir veya sorularınızı yazabilirsiniz."}]
            
        for msg in st.session_state.mesajlar:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])
                
        c1, c2, c3, c4 = st.columns(4)
        hizli_soru = None
        
        if c1.button("💰 Alacaklar", use_container_width=True): hizli_soru = "Piyasadaki toplam alacak bakiye durumumuz nedir?"
        if c2.button("💸 Giderler/Faturalar", use_container_width=True): hizli_soru = "Giderleri ve faturaları listele."
        if c3.button("⚠️ Acil İşler", use_container_width=True): hizli_soru = "Geciken veya bugün teslim edilmesi gereken iş var mı?"
        if c4.button("📦 Eksik Stok", use_container_width=True): hizli_soru = "Kritik sınıra düşen malzeme var mı?"
        
        kullanici_girisi = st.chat_input("OMG AI Sistemine Soru Girin...")
        soru = hizli_soru if hizli_soru else kullanici_girisi
        
        if soru:
            st.session_state.mesajlar.append({"role": "user", "content": soru})
            with st.chat_message("user"): st.markdown(soru)
            
            cevap = "Üzgünüm Hocam, bu sorunuzu tam anlayamadım. Finans, Alacak, Gider, Fatura, Tahsilat, Stok, İşler, Personel veya Cihazlar hakkında kelimeler kullanırsanız size hemen detaylı rapor sunabilirim."
            soru_kucuk = soru.lower()
            para_birimi = ayar_getir("Para_Birimi", "TL")
            
            if any(kelime in soru_kucuk for kelime in ["gider", "masraf", "fatura", "harcama"]):
                toplam_gider = c.execute("SELECT sum(Tutar) FROM giderler").fetchone()[0] or 0
                son_giderler = pd.read_sql("SELECT Tarih, Kategori, Aciklama, Tutar FROM giderler ORDER BY Tarih DESC LIMIT 5", conn)
                cevap = f"💸 Hocam, bugüne kadar sisteme işlenen toplam giderimiz **{toplam_gider:,.2f} {para_birimi}**.\n\n**Sisteme Girilen Son 5 Gider / Fatura Kalemi:**\n"
                if not son_giderler.empty:
                    for _, r in son_giderler.iterrows(): cevap += f"▫️ {r['Tarih']} | {r['Kategori']} - {r['Aciklama']}: **{r['Tutar']:,.2f} {para_birimi}**\n"
                else: cevap += "Henüz sisteme hiç fatura veya gider girilmemiş Hocam."
            
            elif any(kelime in soru_kucuk for kelime in ["tahsilat", "ödeme", "gelir", "para geldi"]):
                toplam_tahsilat = c.execute("SELECT sum(Tutar) FROM tahsilatlar").fetchone()[0] or 0
                son_tahsilatlar = pd.read_sql("SELECT Tarih, Klinik_Unvani, Odeme_Turu, Tutar FROM tahsilatlar ORDER BY Tarih DESC LIMIT 5", conn)
                cevap = f"💵 Hocam, şu ana kadar kliniklerden aldığımız toplam tahsilatımız **{toplam_tahsilat:,.2f} {para_birimi}**.\n\n**Son Yapılan 5 Tahsilat:**\n"
                if not son_tahsilatlar.empty:
                    for _, r in son_tahsilatlar.iterrows(): cevap += f"▫️ {r['Tarih']} | {r['Klinik_Unvani']} ({r['Odeme_Turu']}): **{r['Tutar']:,.2f} {para_birimi}**\n"
                else: cevap += "Henüz sisteme bir tahsilat işlenmemiş Hocam."

            elif any(kelime in soru_kucuk for kelime in ["alacak", "alacağ", "para", "borç", "bakiye", "kasa", "finans"]):
                toplam_alacak = c.execute("SELECT sum(Bakiye) FROM cariler").fetchone()[0] or 0
                en_borclu = c.execute("SELECT Klinik_Unvani, Bakiye FROM cariler ORDER BY Bakiye DESC LIMIT 3").fetchall()
                cevap = f"📊 Hocam, piyasadaki toplam alacağımız **{toplam_alacak:,.2f} {para_birimi}**.\n\n**Bize En Yüksek Borcu Olan 3 Klinik:**\n"
                if en_borclu:
                    for k in en_borclu: cevap += f"▫️ {k[0]}: **{k[1]:,.2f} {para_birimi}**\n"
                else: cevap += "Sistemde borçlu klinik bulunmuyor."

            elif any(kelime in soru_kucuk for kelime in ["iş", "üretim", "geciken", "acil", "durum"]):
                aktif_is = c.execute("SELECT count(*) FROM isler WHERE Asama != 'Teslim Edildi'").fetchone()[0]
                gecikenler = pd.read_sql("SELECT Klinik_Unvani, Hasta_Adi, Asama FROM isler WHERE Asama != 'Teslim Edildi' AND Teslim_Tarihi < ?", conn, params=(datetime.now().strftime('%Y-%m-%d'),))
                cevap = f"⚙️ Hocam, şu an laboratuvarda devam eden toplam **{aktif_is} adet** aktif işimiz var.\n\n"
                if not gecikenler.empty:
                    cevap += f"⚠️ **Dikkat Hocam! Teslim tarihi geçen {len(gecikenler)} acil işimiz var:**\n"
                    for _, r in gecikenler.iterrows(): cevap += f"▫️ {r['Klinik_Unvani']} - {r['Hasta_Adi']} (Durum: *{r['Asama']}*)\n"
                else: cevap += "✅ Geciken hiçbir işimiz yok Hocam, üretim hattı harika gidiyor!"

            elif any(kelime in soru_kucuk for kelime in ["stok", "eksik", "malzeme", "depo", "kalan", "biten"]):
                eksikler = c.execute("SELECT Urun_Adi, Mevcut_Miktar FROM stok WHERE Mevcut_Miktar <= Kritik_Sinir AND Durum='Aktif'").fetchall()
                if eksikler:
                    liste = "\n".join([f"▫️ {e[0]} (Kalan: {e[1]:.0f})" for e in eksikler])
                    cevap = f"🚨 Hocam, depoda **{len(eksikler)}** kalem aktif malzeme kritik seviyede! Üretimin aksamaması için tedarik etmeliyiz.\n\n**Eksik Listesi:**\n{liste}"
                else: cevap = "🟢 Depo harika durumda Hocam! Hiçbir eksiğimiz yok, tam gaz üretime devam."

            elif any(kelime in soru_kucuk for kelime in ["cihaz", "makine", "bakım", "arıza"]):
                bakimlar = c.execute("SELECT Cihaz_Adi FROM cihazlar WHERE Calisma_Saati >= Bakim_Siniri OR Durum='Bakım Gerekiyor'").fetchall()
                if bakimlar:
                    liste = "\n".join([f"▫️ {b[0]}" for b in bakimlar])
                    cevap = f"🔧 TEKNİK UYARI! Aşağıdaki cihazların periyodik bakım zamanı gelmiş Hocam:\n{liste}"
                else: cevap = "✅ Cihaz parkurumuz sorunsuz çalışıyor Hocam, şu an bakım gerektiren bir makine yok."

            elif any(kelime in soru_kucuk for kelime in ["personel", "ekip", "kim", "performans", "maaş", "liste", "çalışan"]):
                aktif_p = c.execute("SELECT count(*) FROM personeller WHERE Durum='Aktif'").fetchone()[0]
                
                # Personel ve Maaş verisini veritabanından çekiyoruz
                df_personel = pd.read_sql("SELECT Ad_Soyad, Gorevi, Maas FROM personeller WHERE Durum='Aktif'", conn)
                toplam_maas = df_personel['Maas'].sum() if not df_personel.empty else 0
                
                # Ayın elemanını buluyoruz
                karne = c.execute("SELECT Sorumlu_Personel, COUNT(*) as sayi FROM isler WHERE Sorumlu_Personel != '-' GROUP BY Sorumlu_Personel ORDER BY sayi DESC LIMIT 1").fetchone()
                
                cevap = f"👥 Hocam, laboratuvarımızda şu an **{aktif_p} aktif personel** hizmet veriyor.\n"
                
                if karne: 
                    cevap += f"🏆 Bu ay en çok iş üstlenen teknisyenimiz: **{karne[0]}** ({karne[1]} iş)\n\n"
                
                # Eğer soru maaş veya liste ile ilgiliyse gizli dosyaları aç!
                if any(k in soru_kucuk for k in ["maaş", "liste", "detay", "çalışanlar"]):
                    cevap += f"💸 **Aylık Toplam Maaş Yükümüz:** **{toplam_maas:,.2f} {para_birimi}**\n\n"
                    cevap += "**📋 Güncel Personel ve Maaş Listesi:**\n"
                    cevap += "| Ad Soyad | Görev / Birim | Net Maaş |\n"
                    cevap += "|:---|:---|:---|\n" # Markdown tablo yapısı
                    
                    for _, r in df_personel.iterrows():
                        cevap += f"| {r['Ad_Soyad']} | {r['Gorevi']} | {r['Maas']:,.2f} {para_birimi} |\n"
            
            st.session_state.mesajlar.append({"role": "assistant", "content": cevap})
            with st.chat_message("assistant"): st.markdown(cevap)

# 💎 FAZ 104: SİMETRİK İKONLAR, SAĞA YASLI GERİ TUŞU VE FADEOUT MESAJ 💎

# ==========================================
# BURADAN İTİBAREN ARAYÜZ KODLARIN BAŞLIYOR...
# ==========================================
aktif_kullanici = st.session_state.get("kullanici_adi", "Misafir")

if "aktif_panel" not in st.session_state:
    st.session_state["aktif_panel"] = "bildirim" 

if aktif_kullanici != "Misafir":

    st.markdown("""
<style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        /* 1. ANA BUTON VE KASA ZIRHI */
        div[data-testid="stPopover"] { position: fixed !important; bottom: 25px !important; right: 25px !important; width: fit-content !important; z-index: 999999 !important; }
        
        div[data-testid="stPopover"] button { background-color: #1877F2 !important; border-radius: 25px !important; padding: 12px 30px !important; border: none !important; box-shadow: 0 6px 16px rgba(24, 119, 242, 0.4) !important; transition: all 0.3s ease !important; }
        
        div[data-testid="stPopover"] button:hover, 
        div[data-testid="stPopover"] button:active, 
        div[data-testid="stPopover"] button:focus { background-color: #166FE5 !important; border: none !important; transform: scale(1.02) !important; color: #ffffff !important; outline: none !important;}
        
        div[data-testid="stPopover"] button p { color: #ffffff !important; font-weight: 600 !important; font-size: 16px !important; font-family: 'Inter', sans-serif !important; margin: 0 !important; }
        
        div[data-testid="stPopoverBody"] { position: fixed !important; bottom: 85px !important; top: auto !important; right: 25px !important; left: auto !important; transform: none !important; max-width: 95vw !important; background-color: #ffffff !important; border: 1px solid #E4E6EB !important; border-radius: 12px !important; box-shadow: 0 12px 28px rgba(0, 0, 0, 0.1) !important; z-index: 999999 !important; overflow-y: hidden !important; padding: 0 !important; font-family: 'Inter', sans-serif !important; }
        div[data-testid="stPopoverBody"] > div { position: relative !important; z-index: 2 !important; } 
        div[data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] { background: transparent !important; gap: 0rem !important; padding: 0 !important; }
        div[data-testid="stPopoverBody"] *::-webkit-scrollbar { width: 6px !important; }
        div[data-testid="stPopoverBody"] *::-webkit-scrollbar-thumb { background: #CED0D4 !important; border-radius: 10px !important; }
        
        /* 🚨 SIZINTI ENGELLEYİCİ: SADECE POPOVER İÇİNDEKİ FORMLARI ETKİLER 🚨 */
        div[data-testid="stPopoverBody"] div[data-testid="stForm"] { border: none !important; padding: 10px 15px !important; background-color: #ffffff !important; margin: 0 !important; box-shadow: none !important; border-top: 1px solid #E4E6EB !important; }

        /* 2. SOHBET BALONLARI */
        .mesaj-satiri { display: flex; flex-direction: column; width: 100%; margin-bottom: 8px; }
        .mesaj-kutusu { padding: 8px 12px; margin: 2px 10px; border-radius: 14px; max-width: 80%; font-size: 13px; font-family: 'Inter', sans-serif; display: inline-block; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
        .mesaj-gonderen { background: #1877F2; color: white; align-self: flex-end; border-bottom-right-radius: 4px; }
        .mesaj-alici { background: #F0F2F5; color: #050505; align-self: flex-start; border-bottom-left-radius: 4px; }
</style>
    """, unsafe_allow_html=True)

# ==================================================
# 🚨 MADDE 8: ANA BUTON CANLI BİLDİRİMİ VE DUYURU RADARI 🚨
# ==================================================
benim_id = aktif_id_bul(aktif_kullanici)

# 1. Sohbetin İçindeysek, O Sohbetin Mesajlarını Anında "Okundu" Yap
if "aktif_sohbet_id" in st.session_state and st.session_state.get("aktif_panel") not in ["rehber", "bildirim"]:
    mesajlari_okundu_isaretle(benim_id, st.session_state["aktif_sohbet_id"])
    
# 2. Sistem Duyurularını (Ekran 1) Tarama Motoru
if "okunan_duyurular" not in st.session_state:
    st.session_state["okunan_duyurular"] = []
    
okunmamis_duyuru_sayisi = 0
try:
    temp_duyurular_df = duyurulari_getir()
    if not temp_duyurular_df.empty:
        conn = db_baglanti.get_connection('dentflow.db')
        c = conn.cursor()
        for index, row in temp_duyurular_df.iterrows():
            # Bu kullanıcı bu duyuruyu okumuş mu?
            c.execute("SELECT 1 FROM okunan_duyurular WHERE kullanici_id = ? AND duyuru_id = ?", (str(benim_id), index))
            if not c.fetchone():
                okunmamis_duyuru_sayisi += 1
        conn.close()
except: pass

# 3. Sohbet Mesajlarını Tarama Motoru (Sadece okunmamış ve engellenmemiş mesajlar)
okunmamis_mesaj_sayisi = toplam_okunmamis_sayisi_getir(benim_id)

# 4. SİSTEMDEKİ TÜM BİLDİRİMLERİN TOPLAMI (Mesajlar + Duyurular)
toplam_bildirim = okunmamis_mesaj_sayisi + okunmamis_duyuru_sayisi

# 5. Okunaklı, Jilet Gibi Buton İsmi Tasarımı
buton_ismi = "💬 İletişim & Destek"
if toplam_bildirim > 0:
    buton_ismi = f"💬 İletişim & Destek 🔴 ({toplam_bildirim})"

st.markdown("""
<style>
    /* ANA AÇILIR PANELİ BUTONA DOĞRU YAKLAŞTIRAN YERÇEKİMİ KODU */
    div[data-testid="stPopoverBody"] {
        transform: translateY(18px) !important; /* Bu değer panelin aşağı inme miktarıdır */
    }
</style>
""", unsafe_allow_html=True)    

# 🚨 TEK VE GERÇEK POPOVER BUTONU BURADA AÇILIYOR 🚨
with st.popover(buton_ismi):
    
   
  # ==================================================
    # EKRAN 1: DESTEK PANELİ VE DUYURULAR
    # ==================================================
    if st.session_state["aktif_panel"] == "bildirim":
        st.markdown('<style>div[data-testid="stPopoverBody"] { width: 480px !important; max-width: 95vw !important; }</style>', unsafe_allow_html=True)
        
        # 🚨 DİNAMİK BUTON CSS'İ (Mesaj varsa KIRMIZI LED, yoksa SAKİN GRİ) 🚨
        dinamik_buton_css = ""
        if toplam_bildirim > 0:
            dinamik_buton_css = """
            @keyframes led-flash {
                0% { box-shadow: 0 0 5px rgba(255, 75, 75, 0.5); transform: scale(1); }
                50% { box-shadow: 0 0 20px rgba(255, 75, 75, 0.9), 0 0 30px rgba(255, 75, 75, 0.6); transform: scale(1.05); }
                100% { box-shadow: 0 0 5px rgba(255, 75, 75, 0.5); transform: scale(1); }
            }
            div[data-testid="stPopoverBody"] > div > div > div > div[data-testid="stHorizontalBlock"]:nth-of-type(1) div[data-testid="column"]:nth-of-type(2) .stButton > button { 
                border-radius: 50% !important; height: 42px !important; width: 42px !important; padding: 0 !important; float: right !important; margin-top: 15px !important; margin-right: 15px !important; 
                background: #ff4b4b !important; border: none !important; animation: led-flash 1.5s infinite !important; transition: 0.2s !important; display: flex; justify-content: center; align-items: center;
            }
            div[data-testid="stPopoverBody"] > div > div > div > div[data-testid="stHorizontalBlock"]:nth-of-type(1) div[data-testid="column"]:nth-of-type(2) .stButton > button p { font-size: 20px !important; margin: 0 !important; color: #ffffff !important; }
            div[data-testid="stPopoverBody"] > div > div > div > div[data-testid="stHorizontalBlock"]:nth-of-type(1) div[data-testid="column"]:nth-of-type(2) .stButton > button:hover { background: #ff3333 !important; }
            """
        else:
            dinamik_buton_css = """
            div[data-testid="stPopoverBody"] > div > div > div > div[data-testid="stHorizontalBlock"]:nth-of-type(1) div[data-testid="column"]:nth-of-type(2) .stButton > button { 
                border-radius: 50% !important; height: 42px !important; width: 42px !important; padding: 0 !important; float: right !important; margin-top: 15px !important; margin-right: 15px !important; 
                background: #F0F2F5 !important; border: none !important; box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important; transition: 0.2s !important; display: flex; justify-content: center; align-items: center;
            }
            div[data-testid="stPopoverBody"] > div > div > div > div[data-testid="stHorizontalBlock"]:nth-of-type(1) div[data-testid="column"]:nth-of-type(2) .stButton > button:hover { background: #E4E6EB !important; transform: scale(1.05) !important; }
            div[data-testid="stPopoverBody"] > div > div > div > div[data-testid="stHorizontalBlock"]:nth-of-type(1) div[data-testid="column"]:nth-of-type(2) .stButton > button p { font-size: 20px !important; margin: 0 !important; color: #050505 !important; }
            """

        st.markdown(f"""
<style>
            .messenger-header {{ padding: 15px 15px 25px 15px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #E4E6EB; }}
            .header-title {{ font-size: 22px; font-weight: 700; color: #050505 !important; font-family: 'Inter', sans-serif; }}
            
            {dinamik_buton_css}
            
            /* 🚨 FORM ALTINDAKİ GEREKSİZ YAZIYI GİZLE 🚨 */
            div[data-testid="InputInstructions"] {{ display: none !important; }}
            
            /* ALT 3'LÜ BUTONLAR */
            div[data-testid="stPopoverBody"] > div > div > div > div[data-testid="stHorizontalBlock"]:nth-of-type(2) {{ margin-top: -20px !important; position: relative !important; z-index: 10 !important; padding: 0 !important; display: flex !important; justify-content: center !important; gap: 6px !important; }}
            div[data-testid="stPopoverBody"] > div > div > div > div[data-testid="stHorizontalBlock"]:nth-of-type(2) .stButton > button {{ background: #ffffff !important; border: 1px solid #CED0D4 !important; border-radius: 20px !important; min-height: 32px !important; height: 32px !important; padding: 0 5px !important; margin: 0 !important; width: 100% !important; box-shadow: 0 2px 4px rgba(0,0,0,0.04) !important; transition: 0.2s !important;}}
            div[data-testid="stPopoverBody"] > div > div > div > div[data-testid="stHorizontalBlock"]:nth-of-type(2) .stButton > button:hover {{ background: #F8F9FA !important; border-color: #1877F2 !important; transform: translateY(-2px) !important; box-shadow: 0 4px 6px rgba(24,119,242,0.15) !important; }}
            div[data-testid="stPopoverBody"] > div > div > div > div[data-testid="stHorizontalBlock"]:nth-of-type(2) .stButton > button * {{ color: #050505 !important; font-weight: 700 !important; font-size: 11px !important; margin: 0 !important; white-space: nowrap !important; }}

            div[data-baseweb="tooltip"] > div {{ background-color: #050505 !important; color: #ffffff !important; border-radius: 6px !important; font-weight: 600 !important; font-size: 12px !important; padding: 6px 10px !important; box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important; }}
            
            .bildirim-karti {{ background-color: #ffffff !important; border-left: 4px solid #CED0D4 !important; border-radius: 8px !important; padding: 12px !important; margin: 0 10px 10px 10px !important; box-shadow: 0 2px 6px rgba(0,0,0,0.04) !important; border-top: 1px solid #E4E6EB !important; border-right: 1px solid #E4E6EB !important; border-bottom: 1px solid #E4E6EB !important; opacity: 0.8; transition: 0.3s; }}
            .bildirim-karti:hover {{ opacity: 1; }}
            
            .bildirim-karti-yeni {{ background-color: #F0F7FF !important; border-left: 4px solid #1877F2 !important; border-radius: 8px !important; padding: 12px !important; margin: 0 10px 5px 10px !important; box-shadow: 0 4px 8px rgba(24,119,242,0.15) !important; border-top: 1px solid #B3D7FF !important; border-right: 1px solid #B3D7FF !important; border-bottom: 1px solid #B3D7FF !important; }}
            
            .bildirim-baslik {{ font-size: 12px !important; margin-bottom: 6px !important; display: flex !important; justify-content: space-between !important; font-weight: 700 !important; }}
            .bildirim-baslik span {{ background-color: transparent !important; display: flex; align-items: center; }}
            .bildirim-baslik span:nth-child(1) {{ color: #050505 !important; }} 
            .bildirim-baslik span:nth-child(2) {{ color: #65676B !important; font-weight: 500 !important; }} 
            .bildirim-icerik {{ font-size: 13px !important; color: #050505 !important; font-weight: 600 !important; line-height: 1.4 !important; }}
            
            @keyframes pulse-badge {{ 0% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.7; transform: scale(1.05); }} 100% {{ opacity: 1; transform: scale(1); }} }}
            .yeni-rozet {{ background-color: #1877F2; color: #ffffff !important; padding: 2px 6px; border-radius: 4px; font-size: 9px !important; margin-left: 6px; animation: pulse-badge 1.5s infinite; text-transform: uppercase; letter-spacing: 0.5px;}}
            
            div[data-testid="stPopoverBody"] div[data-testid="stVerticalBlock"] div[data-testid="stHorizontalBlock"] .stButton > button {{ background: transparent !important; border: 1px solid #1877F2 !important; min-height: 24px !important; height: 26px !important; padding: 0 10px !important; border-radius: 12px !important; margin-top: -5px !important; margin-bottom: 15px !important; float: right; margin-right: 15px; transition: 0.2s !important; box-shadow: none !important;}}
            div[data-testid="stPopoverBody"] div[data-testid="stVerticalBlock"] div[data-testid="stHorizontalBlock"] .stButton > button * {{ color: #1877F2 !important; margin: 0 !important; font-weight: 700 !important; font-size: 11px !important; }}
            div[data-testid="stPopoverBody"] div[data-testid="stVerticalBlock"] div[data-testid="stHorizontalBlock"] .stButton > button:hover {{ background: #1877F2 !important; }}
            div[data-testid="stPopoverBody"] div[data-testid="stVerticalBlock"] div[data-testid="stHorizontalBlock"] .stButton > button:hover * {{ color: #ffffff !important; }}
</style>
        """, unsafe_allow_html=True)
        
        # 🚨 TEK VE GERÇEK ÜST BAR (Ekstra div'ler çöpe atıldı) 🚨
        col_bas, col_btn = st.columns([5, 1.2])
        with col_bas:
            st.markdown("<div class='messenger-header'><div class='header-title'>İletişim Merkezi</div></div>", unsafe_allow_html=True)
        
        with col_btn:
            # Artık LED ve Renk kontrolünü yukarıdaki Dinamik CSS yapıyor. Biz sadece butonu çiziyoruz!
            if st.button("👥", key="open_chats_main", help="Sohbetleri Aç", use_container_width=True):
                st.session_state["aktif_panel"] = "rehber"
                st.rerun()

        bos_sol, c1, c2, c3, bos_sag = st.columns([0.2, 1, 1, 1, 0.2])
        
        with c1: 
            if st.button("🚨 Acil Dön", key="btn_acil"): 
                duyuru_ekle(aktif_kullanici, "🚨 DİKKAT: Acil dönüş/iletişim bekleniyor!")
                st.rerun()
        with c2: 
            if st.button("✅ Onayla", key="btn_onay"): 
                duyuru_ekle(aktif_kullanici, "✅ Bekleyen son işlem için ONAY verildi.")
                st.rerun()
        with c3:
            if st.button("📎 Röntgen", key="btn_rontgen"): 
                duyuru_ekle(aktif_kullanici, "📎 Sisteme yeni bir röntgen/görsel yüklendi.")
                st.rerun()

        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

        if "okunan_duyurular" not in st.session_state:
            st.session_state["okunan_duyurular"] = []

        with st.container(height=340):
            duyurular_df = duyurulari_getir()
                
            if duyurular_df.empty:
                st.markdown("<div style='padding: 20px; text-align: center; color: #65676B; font-size: 13px; border: 1px solid #E4E6EB; border-radius: 10px; margin: 0 10px;'>Şu an bekleyen yeni bir sistem duyurusu bulunmuyor.</div>", unsafe_allow_html=True)
            else:
                tum_bildirimler = list(duyurular_df.iterrows())
                tum_bildirimler.reverse() 
                
                for index, row in tum_bildirimler[:30]:
                    # 🚨 1. Veritabanından bu duyurunun okunup okunmadığını kontrol et 🚨
                    conn = db_baglanti.get_connection('dentflow.db')
                    c = conn.cursor()
                    # index (duyuru id'si) ve benim_id'yi kullanarak okuma geçmişine bakıyoruz
                    c.execute("SELECT 1 FROM okunan_duyurular WHERE kullanici_id = ? AND duyuru_id = ?", (str(benim_id), int(index)))
                    okundu_mu = c.fetchone()
                    conn.close()

                    if not okundu_mu:
                        # ==========================================
                        # OKUNMAMIŞ DUYURU (Mavi Yeni Rozetli Kart)
                        # ==========================================
                        st.markdown(f"""
                            <div class="bildirim-karti-yeni">
                                <div class="bildirim-baslik"><span>👤 {row['yazar']} <span class="yeni-rozet">YENİ</span></span> <span>🕒 {row['zaman']}</span></div>
                                <div class="bildirim-icerik">{row['icerik']}</div>
                            </div>
                        """, unsafe_allow_html=True)
                        
                        col_bos, col_okudum = st.columns([3, 1])
                        with col_okudum:
                            if st.button("✔ Okudum", key=f"okudu_{index}"):
                                # 🚨 2. Butona basılınca Kalıcı Veritabanına (DB) kaydet 🚨
                                duyuru_okundu_isaretle_db(benim_id, int(index))
                                st.rerun()
                    else:
                        # ==========================================
                        # OKUNMUŞ DUYURU (Gri Kart)
                        # ==========================================
                        st.markdown(f"""
                            <div class="bildirim-karti">
                                <div class="bildirim-baslik"><span>👤 {row['yazar']}</span> <span>🕒 {row['zaman']}</span></div>
                                <div class="bildirim-icerik">{row['icerik']}</div>
                            </div>
                        """, unsafe_allow_html=True)

        with st.form("hizli_bildirim_form", clear_on_submit=True):
            col_in, col_send = st.columns([6.8, 1]) 
            st.markdown("""<style>
                div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-baseweb="input"] { background: transparent !important; border: none !important; box-shadow: none !important; }
                /* 🚨 INPUT BORDER KALDIRILDI 🚨 */
                div[data-testid="stPopoverBody"] div[data-testid="stForm"] input { background: #F0F2F5 !important; border: none !important; border-radius: 20px !important; height: 36px !important; font-size: 14px !important; color: #050505 !important; outline: none !important; box-shadow: none !important; padding-left: 15px !important;}
                div[data-testid="stPopoverBody"] div[data-testid="stForm"] input:focus { background: #E4E6EB !important; }
                div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(2) button { background: transparent !important; color: transparent !important; border: none !important; border-radius: 50% !important; width: 36px !important; height: 36px !important; padding: 0 !important; display: flex !important; justify-content: center !important; align-items: center !important; transition: 0.2s !important; position: relative; margin: 0 auto !important; box-shadow: none !important; outline:none !important;}
                div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(2) button:hover { background: #E7F3FF !important; transform: scale(1.1) !important; }
                div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(2) button::after { content: ''; display: block; width: 18px; height: 18px; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%231877F2'%3E%3Cpath d='M2.01 21L23 12 2.01 3 2 10l15 2-15 2z'/%3E%3C/svg%3E"); background-size: contain; background-repeat: no-repeat; background-position: center; margin-left: 2px; }
</style>""", unsafe_allow_html=True)
            
            y_mesaj = col_in.text_input("Mesaj", label_visibility="collapsed", placeholder="Sisteme genel duyuru yaz...")
            btn_send = col_send.form_submit_button("➤")
            
            if btn_send and y_mesaj: 
                duyuru_ekle(aktif_kullanici, y_mesaj)
                st.rerun()
# ==================================================
    # EKRAN 2: SOHBET LİSTESİ VE AKILLI REHBER
    # ==================================================
    elif st.session_state["aktif_panel"] == "rehber":
        
        if "rehber_filtre" not in st.session_state:
            st.session_state["rehber_filtre"] = "Tümü"
        if "grup_kurma_modu" not in st.session_state:
            st.session_state["grup_kurma_modu"] = False

        st.markdown('<style>div[data-testid="stPopoverBody"] { width: 380px !important; max-width: 95vw !important; padding: 10px !important; }</style>', unsafe_allow_html=True)
        st.markdown("""
<style>
            .messenger-header { padding: 5px 0px 10px 0px; display: flex; align-items: center; justify-content: flex-start; min-height: 40px; }
            .header-title { font-size: 22px; font-weight: 700; color: #050505 !important; font-family: 'Inter', sans-serif; white-space: nowrap; }
            div[data-baseweb="tooltip"] > div { background-color: #050505 !important; color: #ffffff !important; border-radius: 6px !important; font-weight: 600 !important; font-size: 12px !important; padding: 6px 10px !important; box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important; }
            
            div[data-testid="stVerticalBlock"] > div > div > div[data-testid="stTextInput"] input { background-color: #F0F2F5 !important; border: 1px solid transparent !important; border-radius: 20px !important; padding: 8px 15px !important; font-size: 13px !important; color: #050505 !important; box-shadow: none !important; transition: 0.3s !important;}
            div[data-testid="stVerticalBlock"] > div > div > div[data-testid="stTextInput"] input:focus { border: 1px solid #1877F2 !important; background-color: #ffffff !important;}
            
            /* ========================================================= */
            /* 🚨 MUTLAK KONUMLANDIRMA ZIRHI (ZİKZAKLARA SON!) 🚨 */
            /* ========================================================= */
            div[data-testid="stPopoverBody"] .stButton > button:has(em) { 
                background: #ffffff !important; border: 1px solid transparent !important; border-radius: 8px !important; margin: 0 0 5px 0 !important; 
                width: 100% !important; height: 65px !important; min-height: 65px !important; padding: 0 !important; box-shadow: none !important; 
                color: #050505 !important; transition: 0.2s !important; position: relative !important; display: block !important;
            }
            div[data-testid="stPopoverBody"] .stButton > button:has(em):hover { background: #F0F2F5 !important; }
            div[data-testid="stPopoverBody"] .stButton > button:has(em) div, 
            div[data-testid="stPopoverBody"] .stButton > button:has(em) p { margin: 0 !important; padding: 0 !important; }
            
            div[data-testid="stPopoverBody"] .stButton > button:has(em) em { 
                position: absolute !important; left: 10px !important; top: 12px !important; 
                font-style: normal !important; width: 40px !important; height: 40px !important; border-radius: 50% !important; 
                background: #E4E6EB !important; color: #050505 !important; display: flex !important; justify-content: center !important; 
                align-items: center !important; font-size: 16px !important; font-weight: 600 !important; 
            }
            div[data-testid="stPopoverBody"] .stButton > button:has(em) strong { 
                position: absolute !important; left: 60px !important; top: 12px !important; 
                font-size: 14px !important; color: #050505 !important; font-weight: 700 !important; text-align: left !important; 
                width: calc(100% - 130px) !important; white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; display: block !important;
            }
            div[data-testid="stPopoverBody"] .stButton > button:has(em) code { 
                position: absolute !important; left: 60px !important; top: 35px !important; 
                font-size: 12px !important; color: #65676B !important; background: transparent !important; border: none !important; 
                padding: 0 !important; text-align: left !important; width: calc(100% - 80px) !important; white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; display: block !important;
            }
            div[data-testid="stPopoverBody"] .stButton > button:has(em) del { 
                position: absolute !important; right: 10px !important; top: 12px !important; 
                font-size: 11px !important; color: #65676B !important; text-decoration: none !important; text-align: right !important; 
                font-weight: 600 !important; white-space: nowrap !important; display: block !important;
            } 

            div[data-testid="stHorizontalBlock"]:first-of-type { align-items: center !important; }
            div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="column"]:nth-child(1) button[kind="primary"] {
                background-color: #1877F2 !important; border: none !important; border-radius: 50% !important; width: 34px !important; min-width: 34px !important; height: 34px !important; padding: 0 !important; margin: 0 !important; margin-left: 5px !important; display: flex !important; align-items: center !important; justify-content: center !important; box-shadow: 0 2px 4px rgba(24,119,242,0.3) !important; transition: 0.2s !important;
            }
            div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="column"]:nth-child(1) button[kind="primary"] p { color: #ffffff !important; font-size: 16px !important; font-weight: 800 !important; line-height: 1 !important; margin: 0 !important; }
            div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="column"]:nth-child(1) button[kind="primary"]:hover { background-color: #166FE5 !important; transform: scale(1.05) !important; }
            
            div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="column"]:nth-child(3) button[kind="primary"] { 
                background-color: #1877F2 !important; width: auto !important; min-width: 44px !important; height: 32px !important; border-radius: 16px !important; color: #ffffff !important; margin: 0 !important; margin-top: 5px !important; float: right !important; margin-right: 10px !important; padding: 0 10px !important; border: none !important; transition: 0.2s !important; box-shadow: 0 2px 4px rgba(24,119,242,0.3) !important; display: flex !important; flex-direction: row !important; align-items: center !important; justify-content: center !important;
            }
            div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="column"]:nth-child(3) button[kind="primary"] p { color: #ffffff !important; margin: 0 !important; font-weight: 700 !important; font-size: 13px !important; white-space: nowrap !important; display: inline-block !important; line-height: 1 !important;}
            div[data-testid="stHorizontalBlock"]:first-of-type > div[data-testid="column"]:nth-child(3) button[kind="primary"]:hover { background-color: #166FE5 !important; transform: scale(1.05) !important; }
            
            div[data-testid="stHorizontalBlock"]:nth-of-type(2) button[kind="secondary"] { background-color: #F0F2F5 !important; color: #050505 !important; border: none !important; border-radius: 14px !important; height: 26px !important; min-height: 26px !important; padding: 0 4px !important; transition: 0.2s !important; margin-top: 5px !important; width: 100% !important;}
            div[data-testid="stHorizontalBlock"]:nth-of-type(2) button[kind="secondary"] p { font-size: 11px !important; font-weight: 600 !important; white-space: nowrap !important; margin: 0 !important; line-height: 1 !important;}
            div[data-testid="stHorizontalBlock"]:nth-of-type(2) button[kind="secondary"]:hover { background-color: #E4E6EB !important; }
            
            div[data-testid="stHorizontalBlock"]:nth-of-type(2) button[kind="primary"] { background-color: #E7F3FF !important; color: #1877F2 !important; border: none !important; border-radius: 14px !important; height: 26px !important; min-height: 26px !important; padding: 0 4px !important; transition: 0.2s !important; margin-top: 5px !important; width: 100% !important;}
            div[data-testid="stHorizontalBlock"]:nth-of-type(2) button[kind="primary"] p { font-size: 11px !important; font-weight: 700 !important; white-space: nowrap !important; margin: 0 !important; line-height: 1 !important;}

            div[data-testid="stCheckbox"] { background-color: #ffffff !important; border: 1px solid #CED0D4 !important; border-radius: 8px !important; padding: 10px 15px !important; margin-bottom: 8px !important; min-height: 44px !important; display: flex !important; align-items: center !important; }
            div[data-testid="stCheckbox"] label { display: flex !important; align-items: center !important; width: 100% !important; }
            div[data-testid="stCheckbox"] p { color: #050505 !important; font-weight: 600 !important; font-size: 13px !important; margin: 0 !important; padding-left: 10px !important; line-height: 1.2 !important; white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important;}
</style>
        """, unsafe_allow_html=True)

        col_geri, col_baslik, col_grup = st.columns([1, 4.5, 1.5])
        
        with col_geri:
            if st.button("❮", key="btn_back_to_bildirim", help="Geri Dön", type="primary"):
                st.session_state["aktif_panel"] = "bildirim"
                st.session_state["grup_kurma_modu"] = False 
                st.rerun()
                
        with col_baslik:
            baslik_metni = "Yeni Grup Kur" if st.session_state["grup_kurma_modu"] else "Sohbetler"
            st.markdown(f"<div class='messenger-header'><div class='header-title'>{baslik_metni}</div></div>", unsafe_allow_html=True)
        
        with col_grup:
            if st.session_state["grup_kurma_modu"]:
                if st.button("❌", key="btn_grup_iptal", type="primary"):
                    st.session_state["grup_kurma_modu"] = False
                    st.rerun()
            else:
                if st.button("👥+", key="btn_yeni_grup", help="Yeni Grup Kur", type="primary"):
                    st.session_state["grup_kurma_modu"] = True
                    st.rerun()

        benim_id = aktif_id_bul(aktif_kullanici)
        kullanicilar_df = sohbet_listesi_getir(aktif_kullanici)

        if st.session_state["grup_kurma_modu"]:
            st.markdown("<div style='padding: 0 5px;'>", unsafe_allow_html=True)
            yeni_grup_adi = st.text_input("Grup Adı", placeholder="Örn: Zirkon Ekibi", label_visibility="collapsed")
            st.markdown("<p style='font-size: 12px; font-weight: 700; color: #050505 !important; margin-top: 10px; margin-bottom: 5px;'>Gruba Eklenecek Kişiler:</p>", unsafe_allow_html=True)
            
            secilen_kisiler = []
            with st.container(height=260):
                for index, row in kullanicilar_df.iterrows():
                    if row['rol'] != 'grup': 
                        isim = row["isim"]
                        klinik = row["klinik_ismi"]
                        ek_bilgi = f" ({klinik})" if row['rol'] != 'lab' and klinik else ""
                        if st.checkbox(f"👤 {isim}{ek_bilgi}", key=f"sec_{row['id']}"):
                            secilen_kisiler.append(row['id'])
            
            st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
            if st.button("✅ Grubu Oluştur", type="primary", use_container_width=True):
                if not yeni_grup_adi: st.warning("Lütfen gruba bir isim verin!")
                elif len(secilen_kisiler) < 1: st.warning("Gruba en az bir kişi eklemelisiniz!")
                else:
                    if benim_id not in secilen_kisiler: secilen_kisiler.append(benim_id)
                    grup_olustur(yeni_grup_adi, benim_id, secilen_kisiler)
                    st.toast(f"'{yeni_grup_adi}' grubu kuruldu!", icon="✅")
                    st.session_state["grup_kurma_modu"] = False
                    st.rerun()

        else:
            st.markdown("<div style='padding: 0 5px;'>", unsafe_allow_html=True)
            arama_terimi = st.text_input("Arama", placeholder="🔍 Ağ'da Ara...", label_visibility="collapsed")

            col_p1, col_p2, col_p3 = st.columns(3)
            with col_p1:
                if st.button("Tümü", type="primary" if st.session_state["rehber_filtre"] == "Tümü" else "secondary", use_container_width=True):
                    st.session_state["rehber_filtre"] = "Tümü"; st.rerun()
            with col_p2:
                if st.button("Klinikler", type="primary" if st.session_state["rehber_filtre"] == "Klinikler" else "secondary", use_container_width=True):
                    st.session_state["rehber_filtre"] = "Klinikler"; st.rerun()
            with col_p3:
                if st.button("Ekipler", type="primary" if st.session_state["rehber_filtre"] == "Ekipler" else "secondary", use_container_width=True):
                    st.session_state["rehber_filtre"] = "Ekipler"; st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

            if not kullanicilar_df.empty:
                if st.session_state["rehber_filtre"] == "Klinikler":
                    kullanicilar_df = kullanicilar_df[kullanicilar_df['rol'] != 'lab'] 
                elif st.session_state["rehber_filtre"] == "Ekipler":
                    kullanicilar_df = kullanicilar_df[kullanicilar_df['rol'] == 'lab']
                
                if arama_terimi:
                    kullanicilar_df = kullanicilar_df[kullanicilar_df['isim'].str.contains(arama_terimi, case=False, na=False) | kullanicilar_df['klinik_ismi'].str.contains(arama_terimi, case=False, na=False)]

            with st.container(height=380):
                if kullanicilar_df.empty:
                    st.markdown("<div style='text-align: center; color: #65676B; font-size: 13px; margin-top: 50px;'>Ağda eşleşen kişi bulunamadı.</div>", unsafe_allow_html=True)
                else:
                    hizli_conn = db_baglanti.get_connection('dentflow.db')
                    hizli_cursor = hizli_conn.cursor()
                    for index, row in kullanicilar_df.iterrows():
                        isim = row["isim"]
                        rol = row["rol"]
                        klinik = row["klinik_ismi"]
                        ek_bilgi = f" ({klinik})" if rol != 'lab' and klinik else ""
                        tam_isim = f"{isim}{ek_bilgi}"
                        avatar = "👥" if rol == 'grup' else isim[0].upper()
                        
                        son_mesaj, zaman = son_mesaji_getir(benim_id, row['id'], hizli_cursor)
                        okunmamis_sayi = okunmamis_mesaj_sayisi_getir(benim_id, row['id'], hizli_cursor)
                        
                        rozet = f" 🔴{okunmamis_sayi}" if okunmamis_sayi > 0 else ""
                        etiket = f"_{avatar}_ **{tam_isim}** `{son_mesaj}` ~~{zaman}{rozet}~~"
                        
                        if st.button(etiket, key=f"btn_db_{row['id']}", use_container_width=True):
                            st.session_state["aktif_panel"] = tam_isim 
                            st.session_state["aktif_sohbet_id"] = row['id']
                            st.rerun() 
                    hizli_conn.close()

# ==================================================
    # EKRAN 3: SOHBET ODASI
    # ==================================================
    else:
        secili_oda = st.session_state["aktif_panel"]
        benim_id = str(aktif_id_bul(aktif_kullanici)).strip()
        karsi_id = str(st.session_state["aktif_sohbet_id"]).strip()
        
        conn = db_baglanti.get_connection('dentflow.db')
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS engellemeler (id SERIAL PRIMARY KEY, engelleyen_id TEXT, engellenen_id TEXT)")
        c.execute("SELECT COUNT(*) FROM engellemeler WHERE engelleyen_id = ? AND engellenen_id = ?", (benim_id, karsi_id))
        ben_engelledim = c.fetchone()[0] > 0
        c.execute("SELECT COUNT(*) FROM engellemeler WHERE engelleyen_id = ? AND engellenen_id = ?", (karsi_id, benim_id))
        o_beni_engelledi = c.fetchone()[0] > 0
        conn.close()

        # Öpüşme mesafesi 18px duruyor, alt boşluk korundu
        st.markdown('<style>div[data-testid="stPopoverBody"] { width: 360px !important; max-width: 95vw !important; padding: 10px 10px 15px 10px !important; transform: translateY(18px) !important; }</style>', unsafe_allow_html=True)
        st.markdown("""
<style>
            .chat-header { padding: 10px 5px 10px 0px; display: flex; align-items: center; border-bottom: 1px solid #E4E6EB; margin-top: -5px; margin-bottom: 10px; justify-content: flex-start; min-height: 46px; }
            .chat-header-left { display: flex; align-items: center; }
            .chat-avatar { width: 36px; height: 36px; border-radius: 50%; background-color: #E4E6EB; display: flex; align-items: center; justify-content: center; font-weight: bold; margin-right: 10px; color: #050505; font-size: 16px; }
            .chat-name { font-weight: 600; color: #050505; font-size: 16px; font-family: 'Inter', sans-serif; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; }
            
            div[data-testid="stHorizontalBlock"]:first-of-type { align-items: center !important; }
            div[data-testid="stHorizontalBlock"]:first-of-type button[kind="primary"] { background-color: #1877F2 !important; border: none !important; border-radius: 50% !important; width: 36px !important; min-width: 36px !important; height: 36px !important; padding: 0 !important; margin: 0 !important; margin-left: 5px !important; display: flex !important; align-items: center !important; justify-content: center !important; box-shadow: 0 2px 4px rgba(24,119,242,0.3) !important; transition: 0.2s !important; }
            div[data-testid="stHorizontalBlock"]:first-of-type button[kind="primary"] p { color: #ffffff !important; font-size: 18px !important; font-weight: 800 !important; line-height: 1 !important; margin: 0 !important; }
            div[data-testid="stHorizontalBlock"]:first-of-type button[kind="primary"]:hover { background-color: #166FE5 !important; transform: scale(1.05) !important; }
            div[data-testid="stHorizontalBlock"]:first-of-type button[kind="primary"]:disabled { background-color: #CED0D4 !important; cursor: not-allowed !important; box-shadow: none !important; transform: none !important;}
            
            div[data-testid="stHorizontalBlock"]:nth-of-type(n+2) button[kind="secondary"] { border-radius: 8px !important; height: 40px !important; min-height: 40px !important; font-weight: 700 !important; width: 100% !important; }
            
            /* 🚨 EKRANIN DIŞINA TAŞMAYI ENGELLEYEN KISALTMA (330px -> 290px) 🚨 */
            .chat-container-scroll { height: 290px; overflow-y: auto; display: flex; flex-direction: column-reverse; padding-right: 5px; margin-bottom: 5px; }
            .chat-container-scroll::-webkit-scrollbar { width: 5px; }
            .chat-container-scroll::-webkit-scrollbar-track { background: transparent; }
            .chat-container-scroll::-webkit-scrollbar-thumb { background-color: #CED0D4; border-radius: 10px; }
            div[data-testid="InputInstructions"] { display: none !important; }
            
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] { margin-bottom: 5px !important; padding-bottom: 0px !important; }
            
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="stHorizontalBlock"] { display: flex !important; align-items: center !important; gap: 12px !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-baseweb="input"] { background: transparent !important; border: none !important; box-shadow: none !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-baseweb="input"]:focus-within { box-shadow: none !important; border: none !important; }
            
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(1) { order: 1 !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] input { background-color: #F0F2F5 !important; border: 1px solid #CED0D4 !important; border-radius: 20px !important; height: 40px !important; font-size: 14px !important; color: #050505 !important; padding-left: 15px !important; outline: none !important; box-shadow: none !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] input::placeholder { color: #8C939D !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] input:focus { border: 1px solid #8C939D !important; box-shadow: none !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] input:disabled { background-color: #E4E6EB !important; color: #8C939D !important; cursor: not-allowed !important;}
            
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(2) button,
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(3) button { 
                width: 40px !important; height: 40px !important; min-width: 40px !important; 
                border-radius: 50% !important; padding: 0 !important; margin: 0 auto !important; 
                display: flex !important; justify-content: center !important; align-items: center !important; 
                transition: 0.2s !important; 
            }
            
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(2) button div,
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(3) button div,
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(2) button p,
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(3) button p {
                display: flex !important; justify-content: center !important; align-items: center !important;
                margin: 0 !important; padding: 0 !important; width: 100% !important; text-align: center !important;
                line-height: 1 !important;
            }

            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(2) { order: 2 !important; display: flex !important; justify-content: center !important; align-items: center !important; min-width: 40px !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(2) button { background: #1877F2 !important; border: none !important; box-shadow: 0 2px 4px rgba(24,119,242,0.3) !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(2) button p { color: #ffffff !important; font-size: 16px !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(2) button:hover { background: #166FE5 !important; transform: scale(1.05) !important;}
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(2) button:disabled { background: #CED0D4 !important; cursor: not-allowed !important; box-shadow: none !important; transform: none !important;}
            
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(3) { order: 3 !important; display: flex !important; justify-content: center !important; align-items: center !important; min-width: 40px !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(3) button { background: transparent !important; border: none !important; box-shadow: none !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(3) button p { color: #65676B !important; font-size: 22px !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(3) button:hover { background: #E7F3FF !important; transform: scale(1.1) !important; color: #1877F2 !important; }
            div[data-testid="stPopoverBody"] div[data-testid="stForm"] div[data-testid="column"]:nth-child(3) button:disabled { color: #CED0D4 !important; cursor: not-allowed !important; transform: none !important; background: transparent !important;}
            
            div[data-testid="stExpander"] { border: 1px solid #CED0D4 !important; border-radius: 10px !important; background: #ffffff !important; box-shadow: 0 4px 6px rgba(0,0,0,0.05) !important; margin-bottom: 5px !important; overflow: hidden !important; }
            div[data-testid="stExpander"] summary { padding: 8px 15px !important; background: #3A3B3C !important; border-radius: 0px !important; border-bottom: none !important; min-height: 36px !important; transition: 0.2s !important; display: flex !important; align-items: center !important; }
            div[data-testid="stExpander"] summary:hover { background: #242526 !important; }
            div[data-testid="stExpander"] summary p { font-weight: 800 !important; font-size: 14px !important; color: #ffffff !important; margin: 0 !important; letter-spacing: 0.5px !important;}
            div[data-testid="stExpander"] summary svg { color: #ffffff !important; fill: #ffffff !important; width: 22px !important; height: 22px !important; }
            div[data-testid="stExpanderDetails"] { padding: 10px !important; background: #ffffff !important; border-top: 1px solid #CED0D4 !important; }
            
            div[data-testid="stHorizontalBlock"]:has(.hm-sinyal) { gap: 4px !important; padding: 0 !important; margin-bottom: 0 !important; }
            div[data-testid="stHorizontalBlock"]:has(.hm-sinyal) button { background: #1877F2 !important; background-color: #1877F2 !important; border: none !important; border-radius: 8px !important; min-height: 32px !important; height: 32px !important; max-height: 32px !important; padding: 0 !important; box-shadow: 0 2px 4px rgba(24, 119, 242, 0.3) !important; transition: 0.2s !important; display: flex !important; align-items: center !important; justify-content: center !important; }
            div[data-testid="stHorizontalBlock"]:has(.hm-sinyal) button p { color: #ffffff !important; font-size: 11px !important; font-weight: 800 !important; margin: 0 !important; white-space: nowrap !important; line-height: 1 !important; display: flex !important; align-items: center !important; justify-content: center !important; }
            div[data-testid="stHorizontalBlock"]:has(.hm-sinyal) button:hover { background: #166FE5 !important; background-color: #166FE5 !important; transform: scale(1.05) !important; box-shadow: 0 4px 8px rgba(24, 119, 242, 0.4) !important; }
            div[data-testid="stHorizontalBlock"]:has(.hm-sinyal) button:disabled { background: #CED0D4 !important; background-color: #CED0D4 !important; cursor: not-allowed !important; box-shadow: none !important; transform: none !important;}
            div[data-testid="stToast"] { background-color: #F8F9FA !important; border: 2px solid #1877F2 !important; border-radius: 10px !important; box-shadow: 0 4px 12px rgba(24,119,242,0.15) !important; }
            div[data-testid="stToast"] * { color: #050505 !important; font-weight: 700 !important; font-size: 14px !important; }
            div[data-baseweb="tooltip"] > div { background-color: #050505 !important; color: #ffffff !important; border-radius: 6px !important; }
            div[data-baseweb="select"] svg { fill: #1877F2 !important; color: #1877F2 !important; }
</style>
        """, unsafe_allow_html=True)

        block_buton_metni = "✅ Engeli Aç" if ben_engelledim else "🚫 Engelle"
        
        mute_key = f"mute_{karsi_id}"
        is_muted = st.session_state.get(mute_key, False)
        mute_buton_metni = "🔔 Sesi Aç" if is_muted else "🔕 Sessiz"

        is_admin = False
        if str(karsi_id).startswith('g_'):
            try:
                conn = db_baglanti.get_connection('dentflow.db')
                c = conn.cursor()
                c.execute("SELECT kurucu_id FROM gruplar WHERE id = ?", (str(karsi_id).replace("g_", ""),))
                kurucu = c.fetchone()
                conn.close()
                if kurucu and str(kurucu[0]) == str(benim_id):
                    is_admin = True
            except: pass

        # ==========================================
        # 2. ÜST BAR (GERİ, BAŞLIK, EKLE BUTONU)
        # ==========================================
        col_geri, col_baslik, col_add = st.columns([1.2, 4.3, 1.2])
        with col_geri:
            if st.button("❮", key="kapat_btn_sohbet", type="primary", use_container_width=True):
                st.session_state["aktif_panel"] = "rehber"
                st.session_state["uye_ekle_acik"] = False 
                st.session_state["uye_cikar_acik"] = False 
                st.rerun()
                
        with col_baslik:
            st.markdown(f"<div class='chat-header'><div class='chat-header-left'><div class='chat-avatar'>{secili_oda[0].upper()}</div><div class='chat-name'>{secili_oda}</div></div></div>", unsafe_allow_html=True)
            
        with col_add:
            if str(karsi_id).startswith('g_'):
                if is_admin:
                    if st.button("➕", key="btn_add_member_toggle", help="Gruba kişi ekler.", type="primary", use_container_width=True):
                        st.session_state["uye_ekle_acik"] = not st.session_state.get("uye_ekle_acik", False)
                        st.session_state["uye_cikar_acik"] = False 
                        st.rerun()
                else:
                    st.button("➕", disabled=True, use_container_width=True)

        if st.session_state.get("uye_ekle_acik", False) and str(karsi_id).startswith('g_') and is_admin:
            st.markdown("<p style='font-size:14px; font-weight:800; color:#1877F2; padding-top:5px; margin-bottom:15px; border-top: 1px solid #E4E6EB;'>👥 Gruba Kişi Ekle</p>", unsafe_allow_html=True)
            try:
                gercek_g_id = str(karsi_id).replace("g_", "")
                conn = db_baglanti.get_connection('dentflow.db')
                disardakiler_df = pd.read_sql_query(f"SELECT id, isim FROM kullanicilar WHERE id NOT IN (SELECT kullanici_id FROM grup_uyeleri WHERE grup_id = '{gercek_g_id}') AND rol != 'grup'", conn)
                
                if not disardakiler_df.empty:
                    c_sec, c_ekle = st.columns([5, 3])
                    with c_sec:
                        secenekler = [None] + disardakiler_df['id'].tolist()
                        def format_isim(x):
                            if x is None: return "Kişi Seç"
                            return disardakiler_df[disardakiler_df['id']==x]['isim'].values[0]
                        secilen_kisi_id = st.selectbox("Kişi Seç", options=secenekler, format_func=format_isim, index=0, label_visibility="collapsed", key="ekle_selectbox")
                    with c_ekle:
                        if st.button("Ekle", key="grup_kisiyi_ekle", type="secondary", use_container_width=True):
                            if secilen_kisi_id is not None:
                                conn.execute("INSERT INTO grup_uyeleri (grup_id, kullanici_id) VALUES (?, ?)", (gercek_g_id, secilen_kisi_id))
                                conn.commit()
                                eklenen_isim = format_isim(secilen_kisi_id)
                                ozel_mesaj_gonder("system", karsi_id, f"Sistem: {eklenen_isim} gruba katıldı.")
                                st.session_state["uye_ekle_acik"] = False 
                                st.rerun()
                            else:
                                st.toast("Lütfen listeden bir kişi seçin!", icon="⚠️")
                else:
                    st.caption("Tüm ağ kullanıcıları zaten bu grupta.")
                conn.close()
            except Exception as e: 
                st.error("Bağlantı Hatası")
            st.markdown("<hr style='margin: 10px 0 15px 0; border:none; border-bottom:1px solid #E4E6EB;'>", unsafe_allow_html=True)

        if st.session_state.get("uye_cikar_acik", False) and str(karsi_id).startswith('g_') and is_admin:
            st.markdown("<p style='font-size:14px; font-weight:800; color:#ff4b4b; padding-top:5px; margin-bottom:15px; border-top: 1px solid #E4E6EB;'>🚨 Gruptan Kişi Çıkar</p>", unsafe_allow_html=True)
            try:
                gercek_g_id = str(karsi_id).replace("g_", "")
                conn = db_baglanti.get_connection('dentflow.db')
                iceridekiler_df = pd.read_sql_query(f"SELECT u.id, u.isim FROM kullanicilar u JOIN grup_uyeleri gu ON u.id = gu.kullanici_id WHERE gu.grup_id = '{gercek_g_id}' AND u.id != '{benim_id}'", conn)
                
                if not iceridekiler_df.empty:
                    c_sec, c_cikar = st.columns([5, 3])
                    with c_sec:
                        secenekler_cikar = [None] + iceridekiler_df['id'].tolist()
                        def format_isim_cikar(x):
                            if x is None: return "Kişi Seç"
                            return iceridekiler_df[iceridekiler_df['id']==x]['isim'].values[0]
                        cikarilacak_kisi_id = st.selectbox("Kişi Seç", options=secenekler_cikar, format_func=format_isim_cikar, index=0, label_visibility="collapsed", key="cikar_selectbox")
                    with c_cikar:
                        if st.button("Çıkar", key="grup_kisiyi_cikar_btn", type="secondary", use_container_width=True):
                            if cikarilacak_kisi_id is not None:
                                conn.execute("DELETE FROM grup_uyeleri WHERE grup_id = ? AND kullanici_id = ?", (gercek_g_id, cikarilacak_kisi_id))
                                conn.commit()
                                cikarilan_isim = format_isim_cikar(cikarilacak_kisi_id)
                                ozel_mesaj_gonder("system", karsi_id, f"Sistem: {cikarilan_isim} gruptan çıkarıldı.")
                                st.session_state["uye_cikar_acik"] = False 
                                st.rerun()
                            else:
                                st.toast("Lütfen listeden bir kişi seçin!", icon="⚠️")
                else:
                    st.caption("Grupta sizden başka kimse yok.")
                conn.close()
            except Exception as e: 
                st.error("Bağlantı Hatası")
            st.markdown("<hr style='margin: 10px 0 15px 0; border:none; border-bottom:1px solid #E4E6EB;'>", unsafe_allow_html=True)


        # ==========================================
        # 3. MESAJLARI GETİRME VE LİSTELEME
        # ==========================================
        mesajlari_okundu_isaretle(benim_id, karsi_id)
        mesajlar_df = sohbet_mesajlarini_getir(benim_id, karsi_id)
        
        tum_html = '<div class="chat-container-scroll">'
        
        if ben_engelledim:
            tum_html += '<div style="text-align:center; margin: 10px 0;"><span style="background-color:#F0F2F5; color:#65676B; padding:4px 12px; border-radius:12px; font-size:11px; font-weight:700; border:1px solid #E4E6EB;">Bu kişiyi engellediniz.</span></div>'

        if mesajlar_df.empty:
            tum_html += "<div style='text-align: center; color: #65676B; font-size: 13px; margin-top: 50px;'>Henüz mesajlaşma yok. İlk mesajı siz gönderin!</div>"
        else:
            import re 
            for index, row in mesajlar_df.iloc[::-1].iterrows():
                msg = str(row["icerik"])
                msg = re.sub(r'(#\w+)', r'<span style="background-color: #E7F3FF; color: #1877F2; padding: 2px 6px; border-radius: 6px; font-weight: 700; font-size: 13px; border: 1px solid #cce5ff;">\1</span>', msg)
                
                if str(row["gonderen_id"]) == "system":
                    if msg.startswith("SYS_BLOCK_"): continue 
                    tum_html += f'<div style="text-align:center; margin: 10px 0;"><span style="background-color:#F0F2F5; color:#65676B; padding:4px 12px; border-radius:12px; font-size:11px; font-weight:700; border:1px solid #E4E6EB;">{msg}</span></div>'
                    continue
                
                elif str(row["gonderen_id"]) == benim_id:
                    saat_etiketi = f'<span style="font-size: 10px; color: #ffffff; opacity: 0.8; margin-left: 10px; display: inline-block;">{row["zaman"]}</span>'
                    if row["okundu"] == -1:
                        tik = ' <span style="color: #ff4b4b; margin-left: 3px; font-weight: 800; font-size: 12px; text-shadow: 0px 0px 5px rgba(255,75,75,0.5);">✓</span>'
                    else:
                        tik = ' <span style="color: #4ade80; margin-left: 3px; font-weight: 800; font-size: 12px; text-shadow: 0px 0px 2px rgba(0,0,0,0.3);">✓✓</span>' if row["okundu"] == 1 else ' <span style="color: #CED0D4; margin-left: 3px; font-weight: 800; font-size: 12px;">✓</span>'
                    tum_html += f'<div class="mesaj-satiri"><div class="mesaj-kutusu mesaj-gonderen">{msg}{saat_etiketi}{tik}</div></div>'
                
                else:
                    if row["okundu"] == -1: continue
                    saat_etiketi = f'<span style="font-size: 10px; color: #65676B; font-weight: 500; margin-left: 10px; display: inline-block;">{row["zaman"]}</span>'
                    isim_etiketi = f'<div style="font-size: 11px; color: #1877F2; font-weight: 800; margin-bottom: 3px;">~ {row.get("gonderen_isim", "")}</div>' if str(karsi_id).startswith('g_') else ""
                    tum_html += f'<div class="mesaj-satiri"><div class="mesaj-kutusu mesaj-alici">{isim_etiketi}{msg}{saat_etiketi}</div></div>'
        
        tum_html += "<div style='text-align: center; color: #65676B; font-size: 12px; margin-top: 15px; margin-bottom: 10px;'>Ağ içi şifreli bağlantı</div></div>"
        st.markdown(tum_html, unsafe_allow_html=True)
        emoji_placeholder = st.empty()

        # ==========================================
        # 4. ÇEKMECE İŞLEMLERİ VE BUTONLAR
        # ==========================================
        with st.expander("⚡ İşlem Çekmecesi", expanded=False):
            if str(karsi_id).startswith('g_'):
                g1, g2, g3, g4 = st.columns(4)
                with g1:
                    st.markdown("<div class='hm-sinyal'></div>", unsafe_allow_html=True)
                    if st.button("ℹ️ Bilgi", key="btn_grp_info", use_container_width=True):
                        try:
                            gercek_g_id = str(karsi_id).replace("g_", "")
                            conn = db_baglanti.get_connection('dentflow.db')
                            uyeler_df = pd.read_sql_query("SELECT u.isim FROM kullanicilar u JOIN grup_uyeleri gu ON u.id = gu.kullanici_id WHERE gu.grup_id = ?", conn, params=(gercek_g_id,))
                            conn.close()
                            isimler = ", ".join(uyeler_df['isim'].tolist())
                            st.toast(f"👥 Üyeler: {isimler}", icon="ℹ️")
                        except: pass
                with g2:
                    if st.button(mute_buton_metni, key="btn_grp_mute", use_container_width=True):
                        st.session_state[mute_key] = not is_muted; st.rerun() 
                with g3:
                    if st.button("👢 Çıkar", key="btn_grp_kick", use_container_width=True, disabled=not is_admin):
                        st.session_state["uye_cikar_acik"] = not st.session_state.get("uye_cikar_acik", False)
                        st.session_state["uye_ekle_acik"] = False 
                        st.rerun()
                with g4:
                    if st.button("🚪 Ayrıl", key="btn_grp_leave", use_container_width=True):
                        try:
                            gercek_g_id = str(karsi_id).replace("g_", "")
                            conn = db_baglanti.get_connection('dentflow.db')
                            c = conn.cursor()
                            c.execute("DELETE FROM grup_uyeleri WHERE grup_id = ? AND kullanici_id = ?", (gercek_g_id, benim_id))
                            conn.commit(); conn.close()
                            ozel_mesaj_gonder("system", karsi_id, f"Sistem: {aktif_kullanici} gruptan ayrıldı.")
                            st.session_state["aktif_panel"] = "rehber"; st.rerun()
                        except: pass
            else:
                birebir_c1, birebir_c2, birebir_c3 = st.columns(3)
                with birebir_c1:
                    st.markdown("<div class='hm-sinyal'></div>", unsafe_allow_html=True)
                    if st.button("ℹ️ Bilgi", key="btn_user_info", use_container_width=True):
                        try:
                            conn = db_baglanti.get_connection('dentflow.db')
                            c = conn.cursor()
                            c.execute("SELECT u.isim, u.rol, k.isim FROM kullanicilar u LEFT JOIN klinikler k ON u.klinik_id = k.id WHERE u.id = ?", (karsi_id,))
                            bilgi = c.fetchone()
                            conn.close()
                            if bilgi:
                                klinik_metni = f" - {bilgi[2]}" if bilgi[2] else ""
                                rol_metni = "Lab" if bilgi[1] == 'lab' else "Klinik"
                                st.toast(f"👤 {bilgi[0]} | 🏷️ {rol_metni}{klinik_metni}", icon="ℹ️")
                        except: pass
                with birebir_c2:
                    if st.button(mute_buton_metni, key="btn_user_mute", use_container_width=True):
                        st.session_state[mute_key] = not is_muted; st.rerun() 
                with birebir_c3:
                    if st.button(block_buton_metni, key="btn_user_block", use_container_width=True):
                        conn = db_baglanti.get_connection('dentflow.db')
                        c = conn.cursor()
                        if ben_engelledim: c.execute("DELETE FROM engellemeler WHERE engelleyen_id = ? AND engellenen_id = ?", (benim_id, karsi_id))
                        else: c.execute("INSERT INTO engellemeler (engelleyen_id, engellenen_id) VALUES (?, ?)", (benim_id, karsi_id))
                        conn.commit(); conn.close()
                        st.rerun()

            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
            hm_c1, hm_c2, hm_c3, hm_c4 = st.columns(4)
            with hm_c1:
                st.markdown("<div class='hm-sinyal'></div>", unsafe_allow_html=True)
                if st.button("👍 Ölçü", key="hm1", use_container_width=True, disabled=ben_engelledim): ozel_mesaj_gonder(benim_id, karsi_id, "👍 Ölçünüz ulaştı, işleme alıyoruz."); st.rerun()
            with hm_c2:
                if st.button("🔥 Fırında", key="hm2", use_container_width=True, disabled=ben_engelledim): ozel_mesaj_gonder(benim_id, karsi_id, "🔥 İşleminiz şu an fırında pişiyor."); st.rerun()
            with hm_c3:
                if st.button("⏳ Onay", key="hm3", use_container_width=True, disabled=ben_engelledim): ozel_mesaj_gonder(benim_id, karsi_id, "⏳ Tasarım tamamlandı, onay bekliyoruz."); st.rerun()
            with hm_c4:
                if st.button("🛵 Kurye", key="hm4", use_container_width=True, disabled=ben_engelledim): ozel_mesaj_gonder(benim_id, karsi_id, "🛵 İşiniz kuryeye teslim edildi."); st.rerun()

        # ==========================================
        # 5. YENİ MESAJ YAZMA FORMU
        # ==========================================
        def form_gonder_motoru():
            msj = st.session_state.get("chat_mesaj_kutusu", "").strip()
            if msj:
                conn = db_baglanti.get_connection('dentflow.db')
                c = conn.cursor()
                from datetime import datetime
                zaman = datetime.now().strftime("%H:%M")
                okundu_durumu = -1 if o_beni_engelledi else 0
                c.execute("INSERT INTO mesajlar (gonderen_id, alici_id, icerik, zaman, okundu) VALUES (?, ?, ?, ?, ?)", (benim_id, karsi_id, msj, zaman, okundu_durumu))
                conn.commit(); conn.close()
                st.session_state["chat_mesaj_kutusu"] = ""

        with st.form("mesaj_yolla_sohbet", clear_on_submit=True):
            col_in, col_send, col_emoji = st.columns([7.0, 1.2, 1.2]) 
            p_text = "Bu kişiyi engellediniz." if ben_engelledim else "Aa (# ile vaka seçin)"
            
            y_mesaj = col_in.text_input("Mesaj", key="chat_mesaj_kutusu", label_visibility="collapsed", placeholder=p_text, disabled=ben_engelledim)
            btn_send = col_send.form_submit_button("➤", on_click=form_gonder_motoru if not ben_engelledim else None, disabled=ben_engelledim)
            btn_emoji = col_emoji.form_submit_button("😀", disabled=ben_engelledim)
            
            if btn_emoji: 
                animasyonlu_html = """
<style>
                @keyframes alttanDogus {
                    0% { transform: translateY(30px); opacity: 0; }
                    5% { transform: translateY(0px); opacity: 1; }
                    90% { transform: translateY(0px); opacity: 1; }
                    100% { transform: translateY(30px); opacity: 0; }
                }
                .sihirli-balon {
                    animation: alttanDogus 10s ease-in-out forwards;
                    background-color: #050505; color: #ffffff; font-size: 12px; font-weight: 600;
                    padding: 8px 12px; border-radius: 8px; text-align: center;
                    box-shadow: 0 4px 10px rgba(0,0,0,0.4); width: 80%;
                    pointer-events: none;
                }
</style>
                <div style='display: flex; justify-content: center; overflow: hidden; padding-bottom: 5px; margin-bottom: 5px;'>
                    <div class='sihirli-balon'>💡 Klavyeden Emojiler için: <b>Windows + .</b> (Nokta)</div>
                </div>
                """
                emoji_placeholder.markdown(animasyonlu_html, unsafe_allow_html=True)

