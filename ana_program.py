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
        c.execute("INSERT INTO okunan_duyurular VALUES (?, ?)", (str(kullanici_id), duyuru_id))
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
STOK_KATEGORILER = ["Zirkonyum Blok", "Frez", "Metal", "Porselen", "Sarf Malzeme", "Demirbaşlar"]

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


try:
    c.execute("SELECT id FROM sistem_loglari LIMIT 1")
except Exception:
    conn.rollback()
    print("ESKİ ŞEMA TESPİT EDİLDİ (id sütunu yok). VERİTABANI SIFIRLANIYOR...")
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    conn.commit()

c.execute('''CREATE TABLE IF NOT EXISTS cariler (id SERIAL PRIMARY KEY, Klinik_Unvani TEXT, Yetkili_Kisi TEXT, Telefon TEXT, Email TEXT, Bakiye REAL, Risk_Limiti REAL, Indirim_Orani REAL DEFAULT 0.0, Sifre TEXT DEFAULT '1234')''')
c.execute('''CREATE TABLE IF NOT EXISTS isler (id SERIAL PRIMARY KEY, Tarih TEXT, Klinik_Unvani TEXT, Hasta_Adi TEXT, Is_Turu TEXT, Renk TEXT, Asama TEXT, Tutar_TL REAL DEFAULT 0.0, Sorumlu_Personel TEXT DEFAULT '-', Harcanan_Malzeme TEXT DEFAULT '-', Teslim_Tarihi TEXT DEFAULT '2026-01-01', Barkod TEXT DEFAULT '-', Lot_Numarasi TEXT DEFAULT '-', Sertifika_No TEXT DEFAULT '-')''')
c.execute('''CREATE TABLE IF NOT EXISTS stok (id SERIAL PRIMARY KEY, Urun_Kodu TEXT, Urun_Adi TEXT, Kategori TEXT, Mevcut_Miktar REAL, Birim TEXT, Kritik_Sinir REAL, Satis_Fiyati REAL, Durum TEXT DEFAULT 'Aktif')''')
c.execute('''CREATE TABLE IF NOT EXISTS fiyat_listesi (id SERIAL PRIMARY KEY, Hizmet_Adi TEXT, Kategori TEXT, Fiyat REAL, Para_Birimi TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS personeller (id SERIAL PRIMARY KEY, Ad_Soyad TEXT, Gorevi TEXT, Telefon TEXT, Maas REAL, Baslama_Tarihi TEXT, Ayrilma_Tarihi TEXT, Durum TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS kullanicilar (id SERIAL PRIMARY KEY, Kullanici_Adi TEXT, Sifre TEXT, Rol TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS giderler (id SERIAL PRIMARY KEY, Tarih TEXT, Kategori TEXT, Aciklama TEXT, Tutar REAL)''')
c.execute('''CREATE TABLE IF NOT EXISTS tahsilatlar (id SERIAL PRIMARY KEY, Tarih TEXT, Klinik_Unvani TEXT, Odeme_Turu TEXT, Tutar REAL, Aciklama TEXT)''')
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
    c.execute("INSERT INTO ayarlar (Ayar_Adi, Ayar_Degeri) VALUES (?, ?)", (ayar_adi, str(deger)))
    conn.commit()

if not c.execute("SELECT count(*) FROM ayarlar").fetchone()[0] > 0:
    ayar_kaydet("Barkod_Onek", "OMG")
    ayar_kaydet("Para_Birimi", "TL")
    ayar_kaydet("KDV_Orani", "20")
    ayar_kaydet("Lobi_IP", "192.168.1.100")
    ayar_kaydet("Sms_Sessiz_Saatler", "22:00 - 08:00")
    ayar_kaydet("Kurye_Sablonu", "Sayın [Hekim_Adı],\nKurye talebiniz alınmıştır. Kuryemiz en kısa sürede adresinize yönlendirilecektir.\nTeşekkür ederiz.")
    ayar_kaydet("Sistem_Kilitli", "Hayır")

def tablo_yama_uygula(tablo_adi, sutun_adi, sutun_turu):
    try: c.execute(f"ALTER TABLE {tablo_adi} ADD COLUMN {sutun_adi} {sutun_turu}")
    except: pass

tablo_yama_uygula("cariler", "Indirim_Orani", "REAL DEFAULT 0.0")
tablo_yama_uygula("cariler", "Sifre", "TEXT DEFAULT '1234'")
tablo_yama_uygula("cariler", "Adres", "TEXT DEFAULT '-'")
tablo_yama_uygula("cariler", "Firma_Unvani", "TEXT DEFAULT '-'")
tablo_yama_uygula("cariler", "Vergi_Dairesi", "TEXT DEFAULT '-'")
tablo_yama_uygula("cariler", "Vergi_No", "TEXT DEFAULT '-'")
tablo_yama_uygula("cariler", "IBAN", "TEXT DEFAULT '-'")
tablo_yama_uygula("isler", "Barkod", "TEXT DEFAULT '-'")
tablo_yama_uygula("isler", "Lot_Numarasi", "TEXT DEFAULT '-'")
tablo_yama_uygula("isler", "Sertifika_No", "TEXT DEFAULT '-'")
tablo_yama_uygula("isler", "Aciklama", "TEXT DEFAULT '-'")
tablo_yama_uygula("stok", "Durum", "TEXT DEFAULT 'Aktif'")
tablo_yama_uygula("cihazlar", "Gorsel_Yolu", "TEXT DEFAULT '-'")
tablo_yama_uygula("cihazlar", "Haftalik_Hedef", f"TEXT DEFAULT '{datetime.now().strftime('%Y-%m-%d')}'")
tablo_yama_uygula("cihazlar", "Aylik_Hedef", f"TEXT DEFAULT '{datetime.now().strftime('%Y-%m-%d')}'")
tablo_yama_uygula("cihazlar", "Yillik_Hedef", f"TEXT DEFAULT '{datetime.now().strftime('%Y-%m-%d')}'")
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
    return pdf.output(dest='S').encode('latin1')

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

if rol == "Admin": menu = ["🏠 Komuta Merkezi", "📺 Lobi / TV Ekranı", "🤝 Hekim ve Cari Kayıt", "⚙️ İş Akışı", "👥 Personel Yönetimi", "📦 Stok Yönetimi", "💰 Finans & Analitik", "📉 Maliyet Analizi", "📱 Teknisyen Terminali", "📱 WhatsApp Entegrasyonu",  "🛵 Kurye Lojistik",  "🔧 Cihaz Bakımı", "📋 Fiyat Listesi",]
elif rol == "Sekreter": menu = ["🏠 Komuta Merkezi", "📺 Lobi / TV Ekranı", "🤝 Hekim ve Cari Kayıt", "⚙️ İş Akışı", "📱 WhatsApp Entegrasyonu", "💰 Finans & Analitik", "🛵 Kurye Lojistik", "📋 Fiyat Listesi"]
elif rol == "Teknisyen": menu = ["⚙️ İş Akışı", "📱 Teknisyen Terminali", "📦 Stok Yönetimi", "🔧 Cihaz Bakımı"]
elif rol == "Klinik": menu = ["🦷 Klinik Paneli", "📤 Yeni Sipariş (Reçete)", "🧾 Detaylı Ekstre"]
elif rol == "Klinik_Asistan": menu = ["🦷 Klinik Paneli", "📤 Yeni Sipariş (Reçete)"]
elif rol == "Kurye": menu = ["🛵 Kurye Mobil Terminali"]
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

def menu_guncelle(): st.session_state.aktif_sayfa = st.session_state.menu_secici
menu_idx = menu.index(st.session_state.aktif_sayfa) if st.session_state.aktif_sayfa in menu else 0
st.sidebar.selectbox("Modül Seçiniz:", menu, index=menu_idx, key="menu_secici", on_change=menu_guncelle)

st.sidebar.markdown("<br>", unsafe_allow_html=True)

if rol in ["Admin", "Sekreter"]:
    if st.sidebar.button("🤖 OMG AI Asistan", type="primary", use_container_width=True): st.session_state.aktif_sayfa = "🤖 OMG AI Asistan"; st.rerun()

st.sidebar.markdown("<br>", unsafe_allow_html=True)
if st.sidebar.button("🚪 Çıkış Yap / Kilitle", use_container_width=True): st.session_state.clear(); st.rerun()

if rol not in ["Teknisyen", "Kiosk", "Klinik_Asistan"]:
    st.sidebar.markdown("<hr style='border-color: rgba(56, 189, 248, 0.2); margin: 10px 0;'>", unsafe_allow_html=True)
    if st.sidebar.button("⚙️ Ayarlar (Sistem & Güvenlik)", key="btn_ayarlar_alt"):
        st.session_state.aktif_sayfa = "⚙️ Ayarlar"; st.rerun()

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
            anlik_bakiye = c.execute("SELECT Bakiye FROM cariler WHERE Klinik_Unvani=?", (ana_klinik,)).fetchone()[0]
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
            df_goster = df_isler[["Barkod", "Tarih", "Teslim_Tarihi", "Hasta_Adi", "Is_Turu", "Asama"]]
            st.dataframe(df_goster, hide_index=True, use_container_width=True)
        else: st.info("Henüz bir iş göndermediniz.")

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
        
        with st.form("klinik_yeni_is"):
            c1, c2 = st.columns(2)
            ha = c1.text_input("Hasta Adı / Dosya No")
            
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
                    c.execute("INSERT INTO isler (Tarih, Klinik_Unvani, Hasta_Adi, Is_Turu, Renk, Asama, Tutar_TL, Sorumlu_Personel, Harcanan_Malzeme, Teslim_Tarihi, Barkod, Lot_Numarasi, Sertifika_No, Aciklama) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (datetime.now().strftime("%Y-%m-%d"), ana_klinik, ha, secilen, renk, "Sipariş Alındı (Hekim Girdi)", 0.0, "-", "-", teslim_tarihi, "-", "-", "-", "-"))
                    yeni_id = c.lastrowid
                    onek = ayar_getir("Barkod_Onek", "OMG")
                    yeni_barkod = f"{onek}-{yeni_id:04d}"
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

    elif sayfa == "🧾 Detaylı Ekstre" and rol == "Klinik":
        banner_olustur("🧾", "Detaylı Hesap Ekstresi", "Borç ve ödeme geçmişinizi takip edin.")
        anlik_bakiye = c.execute("SELECT Bakiye FROM cariler WHERE Klinik_Unvani=?", (kullanici_adi,)).fetchone()[0]
        para_birimi = ayar_getir("Para_Birimi", "TL")
        st.markdown(f"<div class='glass-card' style='text-align:center;'><h2 style='color:#FFFFFF;'>Güncel Borcunuz</h2><h1 class='neon-text-red'>{anlik_bakiye:,.2f} {para_birimi}</h1></div>", unsafe_allow_html=True)
        
        df_borc = pd.read_sql(f"SELECT Tarih, Is_Turu || ' - ' || Hasta_Adi as Islem, Tutar_TL as Borc, 0.0 as Alacak FROM isler WHERE Klinik_Unvani='{kullanici_adi}' AND Tutar_TL > 0", conn)
        df_alacak = pd.read_sql(f"SELECT Tarih, Odeme_Turu || ' Ödemesi (' || Aciklama || ')' as Islem, 0.0 as Borc, Tutar as Alacak FROM tahsilatlar WHERE Klinik_Unvani='{kullanici_adi}'", conn)
        
        if not df_borc.empty or not df_alacak.empty:
            df_ekstre = pd.concat([df_borc, df_alacak]).sort_values(by="Tarih").reset_index(drop=True)
            toplam_yazilan_borc = df_ekstre['Borc'].sum() if not df_ekstre.empty else 0
            toplam_alinan_odeme = df_ekstre['Alacak'].sum() if not df_ekstre.empty else 0
            devreden_bakiye = anlik_bakiye - toplam_yazilan_borc + toplam_alinan_odeme
            
            ilk_satir = pd.DataFrame({"Tarih": ["-"], "Islem": ["Geçmişten Devreden Bakiye"], "Borc": [devreden_bakiye if devreden_bakiye > 0 else 0], "Alacak": [abs(devreden_bakiye) if devreden_bakiye < 0 else 0]})
            df_ekstre = pd.concat([ilk_satir, df_ekstre], ignore_index=True)
            df_ekstre['Kümülatif Bakiye'] = df_ekstre['Borc'].cumsum() - df_ekstre['Alacak'].cumsum()
            
            st.markdown("---")
            st.dataframe(df_ekstre.style.format({"Borc": "{:,.2f}", "Alacak": "{:,.2f}", "Kümülatif Bakiye": "{:,.2f}"}), hide_index=True, use_container_width=True)
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

elif rol in ["Admin", "Sekreter", "Teknisyen"]:

    if sayfa == "🏠 Komuta Merkezi":
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
            toplam_gelir = df_isler['Tutar_TL'].sum() if not df_isler.empty else 0
            bugun_gun = datetime.now().day
            if bugun_gun == 0: bugun_gun = 1
            ai_tahmin = (toplam_gelir / bugun_gun) * 30
            para_birimi = ayar_getir("Para_Birimi", "TL")
            
            f1, f2, f3, f4 = st.columns(4)
            f1.markdown(f"<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>Gerçekleşen Ciro</span><br><span class='neon-text-green' style='font-size:30px;'>{toplam_gelir:,.0f} {para_birimi}</span></div>", unsafe_allow_html=True)
            f2.markdown(f"<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>🤖 AI Ay Sonu Tahmini</span><br><span class='neon-text-blue' style='font-size:30px;'>{ai_tahmin:,.0f} {para_birimi}</span></div>", unsafe_allow_html=True)
            f3.markdown(f"<div class='glass-card' style='text-align:center;'><span style='color:#FFFFFF;'>Piyasadaki Alacak</span><br><span class='neon-text-red' style='font-size:30px;'>{df_cariler['Bakiye'].sum() if not df_cariler.empty else 0:,.0f} {para_birimi}</span></div>", unsafe_allow_html=True)
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
                
                gunluk_ciro = df_trend.groupby(df_trend['Tarih_Formatli'].dt.strftime('%Y-%m-%d'))['Tutar_TL'].sum().reset_index()
                
                if not gunluk_ciro.empty:
                    fig_line = px.area(gunluk_ciro, x="Tarih_Formatli", y="Tutar_TL", markers=True, color_discrete_sequence=["#10B981"])
                    fig_line.update_layout(height=260, template="plotly_dark", margin=dict(t=10, b=20, l=10, r=10), xaxis_title="", yaxis_title=f"Ciro ({ayar_getir('Para_Birimi', 'TL')})", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig_line, use_container_width=True)
                else:
                    st.info("Son 14 güne ait gelir verisi bulunmuyor.")

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
                k_veri = c.execute("SELECT Indirim_Orani, Sifre, Yetkili_Kisi, Telefon, Email, Adres, Firma_Unvani, Vergi_Dairesi, Vergi_No, IBAN FROM cariler WHERE Klinik_Unvani=?", (g_klinik,)).fetchone()
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

                    b1, b2 = st.columns(2)
                    yeni_indirim = b1.number_input("Yeni İndirim Oranı (%)", min_value=0.0, max_value=100.0, value=float(k_veri[0]))
                    yeni_sifre = b2.text_input("Yeni Giriş Şifresi", value=k_veri[1])

                    if st.form_submit_button("Bilgileri Güncelle"):
                        c.execute("UPDATE cariler SET Indirim_Orani=?, Sifre=?, Yetkili_Kisi=?, Telefon=?, Email=?, Adres=?, Firma_Unvani=?, Vergi_Dairesi=?, Vergi_No=?, IBAN=? WHERE Klinik_Unvani=?", 
                                  (yeni_indirim, yeni_sifre, yeni_yetkili, yeni_tel, yeni_email, yeni_adres, yeni_funvan, yeni_vdaire, yeni_vno, yeni_iban, g_klinik))
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
            
            df_is_f = pd.read_sql("SELECT Klinik_Unvani, Tutar_TL FROM isler", conn)
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

        tab_takip, tab_manuel_is = st.tabs(["🚀 Üretim Takibi & Güncelleme", "➕ Yeni Manuel İş Kaydı (Laboratuvar)"])
        
        with tab_manuel_is:
            st.markdown("### 📝 Laboratuvar İçi Reçete Kaydı")
            st.info("Hekim portalı kullanmayan klinikler için manuel iş girişi bu alandan yapılır.")
            
            # 🚨 FORM YAPISI KALDIRILDI, ALANLAR SIKIŞTIRILDI 🚨
            col_kat, col_kat_bos = st.columns([1.5, 3])
            kat_sec_lab = col_kat.selectbox("İşlem Kategorisi", KATEGORILER, key="lab_kat_sec")
            st.markdown("---")
            
            # 1. SATIR: Çok Daraltılmış ve Kısaltılmış Girdiler
            c1, c2, c3, c4 = st.columns([2.5, 1.5, 1, 1.2])
            k_secim = c1.selectbox("Klinik / Hekim", klinikler) if klinikler else c1.text_input("Klinik Adı (Kayıtlı Değil)")
            ha = c2.text_input("Hasta/Dosya No")
            renk = c3.text_input("Renk")
            teslim_tarihi = c4.date_input("Teslim").strftime("%Y-%m-%d")
            
            # 2. SATIR: İşlem Seçimi ve Açıklama (TextArea yerine dar Text Input)
            c5, c6 = st.columns([2.5, 3.7])
            hizmetler_lab = c.execute("SELECT Hizmet_Adi, Fiyat, Para_Birimi FROM fiyat_listesi WHERE Kategori=?", (kat_sec_lab,)).fetchall()
            if hizmetler_lab:
                h_dict_lab = {f"{h[0]}": h for h in hizmetler_lab}
                secilen_lab = c5.selectbox("Yapılacak İşlem", list(h_dict_lab.keys()))
            else:
                secilen_lab = "-"
                c5.warning("⚠️ Fiyat listesi yok.")
            
            aciklama = c6.text_input("Açıklama / Özel İstekler")
            
            # 🚨 MANUEL KAYIT İÇİNE ENTEGRE EDİLMİŞ CAM MODÜLÜ 🚨
            st.markdown("#### ⚙️ CAM İstasyonu Üretimi (Opsiyonel)")
            cam_kullan = st.checkbox("Bu işi şu an makineye gönderiyorum (Blok ve Frez sarfiyatını şimdi düş)", value=False)
            
            b_kodu = None; harcanan_uye_m = 0; secili_makine_m = None; frez_basina_dk_m = 0; sec_frezler_m = []; harcanan_dk_m = 0
            
            if cam_kullan:
                with st.container(border=True):
                    col_mak_m, col_uye_m, col_mbos_m = st.columns([2, 0.8, 3])
                    secili_makine_m = col_mak_m.selectbox("Kazıma Yapılan Makine", ["Redon GTR", "Redon Hybrid", "Roland DWX", "Diğer"], key="m_mak")
                    harcanan_uye_m = col_uye_m.number_input("Kazınan Üye", min_value=1, value=1, key="m_uye")
                    
                    cam_b_m = c.execute("SELECT Blok_Kodu, Urun_Adi, Boyut_Renk, Kalan_Uye FROM cam_bloklar WHERE Durum='Yarım'").fetchall()
                    cam_f_m = c.execute("SELECT frez_kod, frez_adi, yuva_no, toplam_omur_dk, kullanilan_dk FROM aktif_frezler WHERE makine_adi=? AND durum='Aktif'", (secili_makine_m,)).fetchall()
                    
                    if cam_b_m and cam_f_m:
                        c_bm, c_fm = st.columns(2)
                        sec_blok_m = c_bm.selectbox("İşlenen Zirkonyum Blok", [f"{b[0]} | {b[1]} {b[2]} (Kalan: {b[3]} Üye)" for b in cam_b_m], key="m_blok")
                        sec_frezler_m = c_fm.multiselect("Kullanılan Frezler", [f"{f[0]} | {f[2]} - {f[1]} (Kalan: {f[3]-f[4]} Dk)" for f in cam_f_m], key="m_frez")
                        
                        tm1_m, tm2_m, tm_bos_m = st.columns([1.2, 1.2, 4])
                        baslama_saati_m = tm1_m.time_input("Başlama", value=datetime.strptime("09:00", "%H:%M").time(), key="m_bas")
                        bitis_saati_m = tm2_m.time_input("Bitiş", value=datetime.strptime("09:45", "%H:%M").time(), key="m_bit")
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
                        
                        harcanan_m_metni = f"CAM: {b_kodu} ({harcanan_uye_m} Üye), Makine: {secili_makine_m}, Top. {harcanan_dk_m} Dk (Takım başı {frez_basina_dk_m} Dk)"

                    # Her şeyi ana tabloya kaydet
                    c.execute("INSERT INTO isler (Tarih, Klinik_Unvani, Hasta_Adi, Is_Turu, Renk, Asama, Tutar_TL, Sorumlu_Personel, Harcanan_Malzeme, Teslim_Tarihi, Barkod, Lot_Numarasi, Sertifika_No, Aciklama) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (tarih_saat, k_secim, ha, islem_adi, renk, "Sipariş Alındı (Hekim Girdi)", 0.0, "-", harcanan_m_metni, teslim_tarihi, "-", "-", "-", aciklama if aciklama else "-"))
                    yeni_id = c.lastrowid
                    onek = ayar_getir("Barkod_Onek", "OMG")
                    yeni_barkod = f"{onek}-{yeni_id:04d}"
                    c.execute("UPDATE isler SET Barkod=? WHERE id=?", (yeni_barkod, yeni_id))
                    conn.commit()
                    st.success(f"✅ Manuel iş oluşturuldu ve reçeteye eklendi! Barkod: {yeni_barkod}")

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

            df_isler = pd.read_sql('SELECT id, Barkod, Tarih as "Kayıt Zamanı", Teslim_Tarihi, Klinik_Unvani, Hasta_Adi, Is_Turu, Renk, Asama, Tutar_TL, Sorumlu_Personel, Harcanan_Malzeme, Aciklama, Lot_Numarasi, Sertifika_No FROM isler', conn)
            st.subheader("📋 Reçeteler ve Üretim Takibi")
            if not df_isler.empty:
                df_goster = df_isler.drop(columns=["id", "Lot_Numarasi", "Sertifika_No"])
                st.dataframe(df_goster, hide_index=True, use_container_width=True)
                st.markdown("---")
                is_secin = st.selectbox("İşlem Yapılacak Reçeteyi Seçin", ["-- Seçiniz --"] + [f"{r['Barkod']} | {r['Klinik_Unvani']} - {r['Hasta_Adi']} ({r['Is_Turu']})" for _, r in df_isler.iterrows()])
                if is_secin != "-- Seçiniz --":
                    secilen_index = [f"{r['Barkod']} | {r['Klinik_Unvani']} - {r['Hasta_Adi']} ({r['Is_Turu']})" for _, r in df_isler.iterrows()].index(is_secin)
                    s_rowid = int(df_isler.iloc[secilen_index]["id"])
                    s_barkod = df_isler.iloc[secilen_index]["Barkod"]
                    is_verisi = c.execute("SELECT Asama, Sorumlu_Personel, Lot_Numarasi, Sertifika_No, Klinik_Unvani, Hasta_Adi, Is_Turu, Tarih FROM isler WHERE id=?",(s_rowid,)).fetchone()
                    
                    t1, t2, t3, t4 = st.tabs(["🔄 Aşama Güncelle", "📸 Medya & Arşiv", "📜 Garanti", "⚙️ CAM Sarfiyatı"])
                    
                    with t1:
                        col_a, col_b = st.columns(2)
                        y_asama = col_a.selectbox("Yeni Aşama", ["Sipariş Alındı (Hekim Girdi)", "Tasarım Bekliyor", "Kazıma/Döküm", "Tesviye", "Seramik/Fırın", "Teslim Edildi"], index=["Sipariş Alındı (Hekim Girdi)", "Tasarım Bekliyor", "Kazıma/Döküm", "Tesviye", "Seramik/Fırın", "Teslim Edildi"].index(is_verisi[0]) if is_verisi[0] in ["Sipariş Alındı (Hekim Girdi)", "Tasarım Bekliyor", "Kazıma/Döküm", "Tesviye", "Seramik/Fırın", "Teslim Edildi"] else 1)
                        y_sorumlu = col_b.selectbox("Sorumlu Teknisyen", aktif_personeller, index=0)
                        if st.button("Güncelle", use_container_width=True):
                            c.execute("UPDATE isler SET Asama=?, Sorumlu_Personel=? WHERE id=?", (y_asama, y_sorumlu, s_rowid))
                            conn.commit(); st.rerun()
                            
                        st.markdown("---")
                        mevcut_fiyat = c.execute("SELECT Tutar_TL FROM isler WHERE id=?", (s_rowid,)).fetchone()[0]
                        if mevcut_fiyat == 0.0:
                            st.markdown("#### 💰 Faturalandırma")
                            # 🚨 FATURALANDIRMA BUTONU VE KUTUSU MİNİMUMA İNDİRİLDİ 🚨
                            c_fat1, c_fat2, c_fat_bos = st.columns([1, 1, 3])
                            with c_fat1: f_tutar = st.number_input("Tutar (TL)", min_value=0.0, value=0.0, step=100.0)
                            with c_fat2: 
                                st.markdown("<br>", unsafe_allow_html=True) # Butonu kutuyla hizalamak için boşluk
                                if st.button("💳 Bakiye'ye Ekle", type="primary", use_container_width=True):
                                    if f_tutar > 0:
                                        c.execute("UPDATE isler SET Tutar_TL=? WHERE id=?", (f_tutar, s_rowid))
                                        is_klinik = is_verisi[4] 
                                        try: c.execute("UPDATE cariler SET Bakiye = Bakiye + ? WHERE Klinik_Unvani = ?", (f_tutar, is_klinik))
                                        except: pass
                                        conn.commit(); st.success("İşlem faturalandırıldı!"); st.rerun()
                                    else: st.error("Tutar giriniz.")
                        else: st.success(f"✅ Bu iş **{mevcut_fiyat:,.2f} TL** olarak faturalandırılmıştır.")
                    
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
                        # 🚨 NORMAL STOK SİLİNDİ, SADECE HEKİM İŞLERİ İÇİN CAM SARFİYATI BIRAKILDI 🚨
                        col_mak, col_uye, col_mbos = st.columns([2, 0.8, 3])
                        secili_makine = col_mak.selectbox("Kazıma Yapılan Makine", ["Redon GTR", "Redon Hybrid", "Roland DWX", "Diğer"], key="t4_mak")
                        harcanan_uye = col_uye.number_input("Kazınan Üye", min_value=1, value=1, key="t4_uye")
                        
                        cam_b = c.execute("SELECT Blok_Kodu, Urun_Adi, Boyut_Renk, Kalan_Uye FROM cam_bloklar WHERE Durum='Yarım'").fetchall()
                        cam_f = c.execute("SELECT frez_kod, frez_adi, yuva_no, toplam_omur_dk, kullanilan_dk FROM aktif_frezler WHERE makine_adi=? AND durum='Aktif'", (secili_makine,)).fetchall()
                        
                        if cam_b and cam_f:
                            c_b, c_f = st.columns(2)
                            sec_blok = c_b.selectbox("İşlenen Zirkonyum Blok", [f"{b[0]} | {b[1]} {b[2]} (Kalan: {b[3]} Üye)" for b in cam_b], key="t4_blok")
                            sec_frezler = c_f.multiselect("Kullanılan Frezler (Çoklu Seçim)", [f"{f[0]} | {f[2]} - {f[1]} (Kalan: {f[3]-f[4]} Dk)" for f in cam_f], key="t4_frez")
                            
                            tm1, tm2, tm_bos = st.columns([1.2, 1.2, 4])
                            baslama_saati = tm1.time_input("Başlama", value=datetime.strptime("09:00", "%H:%M").time(), key="t4_bas")
                            bitis_saati = tm2.time_input("Bitiş", value=datetime.strptime("09:45", "%H:%M").time(), key="t4_bit")
                            tm1.caption("💡 Klavyeden yazabilirsiniz.")
                            
                            start_dt = datetime.combine(datetime.today(), baslama_saati); end_dt = datetime.combine(datetime.today(), bitis_saati)
                            if end_dt < start_dt: end_dt += timedelta(days=1) 
                            harcanan_dk = int((end_dt - start_dt).total_seconds() / 60)
                            frez_sayisi = len(sec_frezler) if len(sec_frezler) > 0 else 1
                            frez_basina_dk = int(harcanan_dk / frez_sayisi)
                            
                            if st.button("⚙️ CAM Sarfiyatını Kaydet", type="primary"):
                                if sec_frezler and harcanan_dk > 0:
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
                                    
                                    eski_m_row = c.execute("SELECT Harcanan_Malzeme FROM isler WHERE id=?", (s_rowid,)).fetchone()
                                    eski_m = eski_m_row[0] if eski_m_row else "-"
                                    yeni_cam_m = f"CAM: {b_kodu} ({harcanan_uye} Üye), Makine: {secili_makine}, Top. {harcanan_dk} Dk (Takım başı {frez_basina_dk} Dk)"
                                    c.execute("UPDATE isler SET Harcanan_Malzeme=? WHERE id=?", (yeni_cam_m if eski_m == "-" else f"{eski_m}, {yeni_cam_m}", s_rowid))
                                    conn.commit(); st.success("CAM Sarfiyatı İşlendi!"); st.rerun()
                                else:
                                    st.error("Lütfen en az bir frez seçin ve bitiş saatinin başlangıçtan sonra olduğundan emin olun.")
                        else:
                            st.warning("Seçilen makinede aktif frez veya sistemde yarım zirkonyum blok bulunamadı.")
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
                            <p><b>🆔 T.C. Kimlik:</b> {r['TC_No']}</p>
                            <p><b>📱 Telefon:</b> {r['Telefon']}</p>
                            <p><b>📧 E-Posta:</b> {r['Email']}</p>
                            <p><b>📍 Adres:</b> {r['Adres']}</p>
                            <p><b>🗓️ İşe Giriş:</b> {r['Baslama_Tarihi']}</p>
                            <p><b>🏖️ Kalan İzin:</b> {r['Kalan_Izin']} Gün</p>
                            <p><b>💳 IBAN:</b> <code style="color:#34d399;">{r['IBAN']}</code></p>
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
                            c.execute("INSERT INTO personel_izinler VALUES (?,?,?,?,?,?)", (datetime.now().strftime("%Y-%m-%d"), sec_per_izin, bas_tar.strftime("%Y-%m-%d"), bit_tar.strftime("%Y-%m-%d"), kullanilan_gun, izin_notu))
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
                    c.execute("INSERT INTO giderler VALUES (?,?,?,?)", (datetime.now().strftime("%Y-%m-%d"), "Maaş", gider_notu, net_odenecek))
                    c.execute("INSERT INTO personel_finans VALUES (?,?,?,?,?)", (datetime.now().strftime("%Y-%m-%d"), b_per, "Maaş Ödemesi", net_odenecek, "Ay Sonu Kapanışı"))
                    conn.commit(); st.success(f"{net_odenecek:,.2f} {para_birimi} Maaş ödemesi başarıyla Finans (Giderler) modülüne işlendi!"); st.balloons()
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
        t1, t2, t3, t4, t5 = st.tabs(["➕ Manuel Giriş / Çıkış", "📊 Mevcut Envanter (Aktif/Pasif)", "📥 Excel/CSV Yükle", "🤖 Akıllı Tedarik & AI", "💿 CAM Envanteri (Blok & Frez)"])
        with t1:
            is_yeni = st.checkbox("Sisteme Yepyeni Bir Ürün Tanımla")
            st.markdown("---")
            if not is_yeni:
                c1, c2 = st.columns(2)
                k_sec = c1.selectbox("Kategori Filtresi", STOK_KATEGORILER, key="manual_stok_kat")
                u_list = c.execute("SELECT Urun_Kodu, Urun_Adi, Mevcut_Miktar, Birim, Renk FROM stok WHERE Kategori=?", (k_sec,)).fetchall()
                if u_list:
                    u_dict = {f"{u[0]} | {u[1]}{f' (Renk: {u[4]})' if u[4] and u[4] != '-' else ''} (Mevcut: {u[2]:.0f} {u[3]})": u[0] for u in u_list}
                    s_u = c2.selectbox("İşlem Yapılacak Ürün", list(u_dict.keys()), key="manual_stok_urun")
                    
                    with st.form("manuel_stok_guncelleme_formu"):
                        girilen_renk = st.text_input("Renk Belirtin (Örn: A1, A2 - Yeni bir renk varyantı eklemek için buraya yazın)", value="-")
                        
                        col_y, col_m = st.columns(2)
                        i_yon = col_y.radio("Yön", ["➕ Ekle (Giriş)", "➖ Düş (Çıkış)"], horizontal=True)
                        m_mik = col_m.number_input("Miktar", min_value=1.0, value=1.0, key="manual_stok_mik")
                        
                        guncelle_btn = st.form_submit_button("Stoğu Güncelle")

                    if guncelle_btn:
                        sec_kod_guncelle = s_u.split("|")[0].strip()
                        
                        hedef_kod = sec_kod_guncelle
                        if girilen_renk.strip() != "" and girilen_renk.strip() != "-":
                            hedef_kod = f"{sec_kod_guncelle}-{girilen_renk.strip().upper()}"
                            
                        mevcut_urun = c.execute("SELECT Mevcut_Miktar, Urun_Adi, Kategori, Birim, Kritik_Sinir, Satis_Fiyati, Durum FROM stok WHERE Urun_Kodu=?", (hedef_kod,)).fetchone()
                        
                        try:
                            if not mevcut_urun:
                                if "➖" in i_yon:
                                    st.error(f"'{girilen_renk}' renginde stok kaydı bulunmuyor, çıkış yapılamaz!")
                                else:
                                    base_urun = c.execute("SELECT Urun_Adi, Kategori, Birim, Kritik_Sinir, Satis_Fiyati, Durum FROM stok WHERE Urun_Kodu=?", (sec_kod_guncelle,)).fetchone()
                                    if not base_urun:
                                        st.error("Ana ürün bulunamadı!")
                                    else:
                                        c.execute("INSERT INTO stok (Urun_Kodu, Urun_Adi, Kategori, Mevcut_Miktar, Birim, Kritik_Sinir, Satis_Fiyati, Durum, Renk) VALUES (?,?,?,?,?,?,?,?,?)", 
                                                  (hedef_kod, base_urun[0], base_urun[1], m_mik, base_urun[2], base_urun[3], base_urun[4], base_urun[5], girilen_renk.strip().upper()))
                                        conn.commit()
                                        st.success(f"Başarılı! Yeni Varyant Eklendi: {hedef_kod}")
                            else:
                                mevcut = mevcut_urun[0]
                                if "➖" in i_yon:
                                    if mevcut < m_mik: st.error("Stok Yetersiz!")
                                    else: 
                                        c.execute("UPDATE stok SET Mevcut_Miktar=? WHERE Urun_Kodu=?", (mevcut - m_mik, hedef_kod))
                                        conn.commit()
                                        st.success(f"Düşüldü! Kalan: {mevcut - m_mik}")
                                else: 
                                    c.execute("UPDATE stok SET Mevcut_Miktar=? WHERE Urun_Kodu=?", (mevcut + m_mik, hedef_kod))
                                    conn.commit()
                                    st.success(f"Eklendi! Yeni Miktar: {mevcut + m_mik}")
                        except Exception as e:
                            st.error(f"Veritabanı Hatası: {str(e)}")
                            
                        # Sayfayı yenileme butonu
                        if st.button("Sayfayı Yenile ve Sonucu Gör"):
                            st.rerun()
            else:
                with st.form("yeni_stok_formu"):
                    c1, c2, c3 = st.columns(3)
                    kod = c1.text_input("Yeni Ürün Kodu")
                    ad = c2.text_input("Yeni Ürün Adı")
                    renk = c3.text_input("Renk (Opsiyonel)", value="-")
                    
                    kat = c1.selectbox("Kategori", STOK_KATEGORILER)
                    durum = c2.selectbox("Ürün Durumu", ["Aktif (Alarm Verir)", "Pasif (Alarm Vermez)"])
                    fiy = c3.number_input("Satış Fiyatı (TL)", value=0.0)
                    
                    mik = c1.number_input("Miktar", value=1.0)
                    bir = c2.selectbox("Birim", ["Adet", "Gram", "Litre", "Kutu"])
                    sinir = c3.number_input("Kritik Sınır", value=5.0)
                    
                    if st.form_submit_button("Kaydet") and kod and ad:
                        d_str = "Aktif" if "Aktif" in durum else "Pasif"
                        hedef_kod = kod
                        if renk.strip() != "" and renk.strip() != "-":
                            hedef_kod = f"{kod}-{renk.strip().upper()}"
                            
                        c.execute("INSERT INTO stok (Urun_Kodu, Urun_Adi, Kategori, Mevcut_Miktar, Birim, Kritik_Sinir, Satis_Fiyati, Durum, Renk) VALUES (?,?,?,?,?,?,?,?,?)", 
                                  (hedef_kod, ad, kat, mik, bir, sinir, fiy, d_str, renk.strip().upper() if renk.strip() != "-" else "-"))
                        conn.commit(); st.success("Eklendi!"); st.rerun()
        with t2:
            st.info("Kullanmadığınız ürünleri 'Pasif' yaparak Stok Alarmından çıkarabilirsiniz. Pasif ürünler listenin en altına gri renkte yerleşir.")
            df_stok = pd.read_sql("SELECT * FROM stok ORDER BY Urun_Kodu ASC", conn)
            
            c_aktif1, c_aktif2 = st.columns(2)
            degisecek_urun = c_aktif1.selectbox("Durumunu Değiştirmek İstediğiniz Ürün", ["-- Seçiniz --"] + [f"{r['Urun_Kodu']} | {r['Urun_Adi']} (Şu an: {r['Durum']})" for _, r in df_stok.iterrows()])
            if degisecek_urun != "-- Seçiniz --":
                sec_kod = degisecek_urun.split("|")[0].strip()
                mevcut_sorgu = c.execute("SELECT Durum FROM stok WHERE Urun_Kodu=?", (sec_kod,)).fetchone()
                if mevcut_sorgu:
                    mevcut_d = mevcut_sorgu[0]
                    yeni_d = "Pasif" if mevcut_d == "Aktif" else "Aktif"
                    if c_aktif2.button(f"Durumu '{yeni_d}' Yap", use_container_width=True):
                        c.execute("UPDATE stok SET Durum=? WHERE Urun_Kodu=?", (yeni_d, sec_kod)); conn.commit(); st.rerun()
            
            st.markdown("---")
            
            # 🚨 AKILLI ARAMA MOTORU DARALTILDI (KOLON ZIRHI) 🚨
            st.markdown("<h4 style='color: #38bdf8; margin-top:-10px;'>🔍 Akıllı Envanter Radarı</h4>", unsafe_allow_html=True)
            
            # Ekranı bölüyoruz: Sadece sol köşede ufak bir alan kaplayacak
            col_ara, col_bosluk = st.columns([1.5, 4])
            with col_ara:
                stok_arama_terimi = st.text_input("Arama", label_visibility="collapsed", placeholder="Örn: 5DML, Frez...")
            
            st.markdown("<br>", unsafe_allow_html=True)

            df_stok.columns = ["id", "Ürün Kodu", "Ürün Adı", "Kategori", "Mevcut Miktar", "Birim", "Kritik Sınır", "Satış Fiyatı (TL)", "Durum", "Renk"]
            df_stok_gorsel = df_stok.drop(columns=["id", "Satış Fiyatı (TL)"]) 
            
            # SADECE STOKTA VAR OLANLARI GÖSTER (Mevcut Miktar > 0)
            df_stok_gorsel = df_stok_gorsel[df_stok_gorsel['Mevcut Miktar'] > 0]
            
            # ARAMA FİLTRESİNİ UYGULA
            if stok_arama_terimi:
                # Hem ürün kodunda hem de ürün adında küçük/büyük harf duyarsız arama yapar
                mask = df_stok_gorsel['Ürün Kodu'].str.contains(stok_arama_terimi, case=False, na=False) | \
                       df_stok_gorsel['Ürün Adı'].str.contains(stok_arama_terimi, case=False, na=False)
                df_stok_gorsel = df_stok_gorsel[mask]

            alt_sekmeler = st.tabs(STOK_KATEGORILER)
            for i, kat_adi in enumerate(STOK_KATEGORILER):
                with alt_sekmeler[i]:
                    df_filtre = df_stok_gorsel[df_stok_gorsel["Kategori"] == kat_adi].copy()
                    if not df_filtre.empty:
                        # 💎 ÇOKLU AKILLI SIRALAMA (AKTİFLİK -> ÜRÜN ADI -> ÜRÜN KODU) 💎
                        df_filtre['SortKey'] = df_filtre['Durum'].apply(lambda x: 0 if x == 'Aktif' else 1)
                        
                        # 🚨 İŞTE SİHİR BURADA: Önce Duruma, sonra isme ve koda göre A'dan Z'ye küçükten büyüğe dizer 🚨
                        df_filtre = df_filtre.sort_values(by=['SortKey', 'Ürün Adı', 'Ürün Kodu'], ascending=[True, True, True]).drop(columns=['SortKey'])
                        
                        # 🚨 ZARİF MAT GÜMÜŞ ZIRH 🚨
                        def satir_renk(row):
                            if row['Durum'] == 'Pasif': return ['background-color: rgba(51, 65, 85, 0.5); color: #CBD5E1; font-weight: 600; font-style: italic;'] * len(row) 
                            elif row['Mevcut Miktar'] <= row['Kritik Sınır']: return ['background-color: rgba(248, 113, 113, 0.2)'] * len(row) 
                            else: return [''] * len(row)
                            
                        col_tablo, col_islemler = st.columns([3.5, 1.5])
                        
                        with col_tablo:
                            st.dataframe(df_filtre.style.format({"Mevcut Miktar": "{:.0f}", "Kritik Sınır": "{:.0f}"}).apply(satir_renk, axis=1), hide_index=True, use_container_width=True)

                        with col_islemler:
                            # ✏️ İŞLEMLER PANELİ (Güncelle / Sil)
                            st.markdown("<h5 style='color:#38bdf8;margin-bottom:8px;'>⚡ İşlemler</h5>", unsafe_allow_html=True)
                            
                            islem_urun_secenekleri = [f"{r['Ürün Kodu']} | {r['Ürün Adı']}{f' (Renk: {r[chr(82)+chr(101)+chr(110)+chr(107)]}' if r.get('Renk') and r['Renk'] not in ['-',''] else ''}{')' if r.get('Renk') and r['Renk'] not in ['-',''] else ''} — Mevcut: {int(r['Mevcut Miktar'])}" for _, r in df_filtre.iterrows()]
                            
                            secilen_islem_urun = st.selectbox(
                                "İşlem Yapılacak Ürünü Seçin", 
                                ["— Seçiniz —"] + islem_urun_secenekleri,
                                key=f"islem_urun_{kat_adi}"
                            )
                            
                            if secilen_islem_urun != "— Seçiniz —":
                                secilen_kod = secilen_islem_urun.split("|")[0].strip()
                                mevcut_kayit = c.execute("SELECT Urun_Adi, Mevcut_Miktar, Renk FROM stok WHERE Urun_Kodu=?", (secilen_kod,)).fetchone()
                                
                                if mevcut_kayit:
                                    with st.form(f"guncelle_form_{kat_adi}_{secilen_kod}"):
                                        st.markdown(f"**✏️ Güncelle:** `{secilen_kod}`")
                                        yeni_miktar = st.number_input(
                                            "Yeni Miktar", 
                                            min_value=0.0, 
                                            value=float(mevcut_kayit[1]) if mevcut_kayit[1] else 0.0,
                                            step=1.0,
                                            key=f"yeni_mik_{kat_adi}_{secilen_kod}"
                                        )
                                        yeni_renk = st.text_input(
                                            "Yeni Renk (Örn: A1)",
                                            value=str(mevcut_kayit[2]) if mevcut_kayit[2] else "-",
                                            key=f"yeni_renk_{kat_adi}_{secilen_kod}"
                                        )
                                        if st.form_submit_button("💾 Güncelle", use_container_width=True):
                                            try:
                                                c.execute("UPDATE stok SET Mevcut_Miktar=?, Renk=? WHERE Urun_Kodu=?",
                                                         (yeni_miktar, yeni_renk.strip().upper() if yeni_renk.strip() != "" else "-", secilen_kod))
                                                conn.commit()
                                                st.success(f"✅ Güncellendi!")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"Hata: {e}")
                                                
                                    st.markdown("**🗑️ Sil**")
                                    if st.button("🗑️ Sil", key=f"sil_btn_{kat_adi}_{secilen_kod}", type="primary", use_container_width=True):
                                        try:
                                            c.execute("DELETE FROM stok WHERE Urun_Kodu=?", (secilen_kod,))
                                            conn.commit()
                                            st.success(f"✅ {secilen_kod} silindi!")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Hata: {e}")
                    else:
                        if stok_arama_terimi:
                            st.info(f"Arama sonucunda '{kat_adi}' kategorisinde '{stok_arama_terimi}' ile eşleşen bir ürün bulunamadı.")
                        else:
                            st.info(f"Bu kategoride henüz kayıtlı ürün bulunmuyor.")
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
                                    c.execute("INSERT INTO stok (Urun_Kodu, Urun_Adi, Kategori, Mevcut_Miktar, Birim, Kritik_Sinir, Satis_Fiyati, Durum) VALUES (?,?,?,?,?,?,?,'Aktif')", 
                                              (kodu, adi, kategorisi, 0.0, "Adet", 5.0, fiyati))
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

        with t5:
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
                st.info("Makinelerinizin magazinlerindeki aktif takımları buradan yönetin. Çıkardığınız frezler aşağıdaki 'Yedek İstasyonu'nda bekler.")
                # SESSİZ GÜNCELLEME: Senin eski taktığın T1, T2 kayıtlarını otomatik M1, M2 yapar
                c.execute("UPDATE aktif_frezler SET yuva_no = REPLACE(yuva_no, 'T', 'M') WHERE yuva_no LIKE 'T%'")
                conn.commit()

                # --- SIFIR FREZ TAKMA BÖLÜMÜ ---
                with st.expander("➕ Ana Stoktan SIFIR Frez Tak", expanded=False):
                    frez_stok = c.execute("SELECT Urun_Kodu, Urun_Adi, Satis_Fiyati FROM stok WHERE Kategori='Frez' AND Mevcut_Miktar > 0 AND Durum='Aktif'").fetchall()
                    
                    if frez_stok:
                        c1, c2, c3 = st.columns(3)
                        f_sec = c1.selectbox("Ana Stoktan Frez Seç", [f"{f[0]} | {f[1]} | {f[2]} TL" for f in frez_stok])
                        
                        makine = c2.selectbox("Makine Seç", ["Redon GTR", "Redon Hybrid", "Roland DWX", "Diğer"])
                        
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
                            oto_barkod = f"FRZ-{yuva.replace('M', 'T')}-{datetime.now().strftime('%M%S')}"
                            
                            c4, c5, c_bos = st.columns([1, 1, 1])
                            frez_kod = c4.text_input("Frez Takip Kodu", value=oto_barkod)
                            omur = c5.number_input("Beklenen Toplam Ömür (Dakika)", min_value=1, value=1500, step=100)
                            
                            st.markdown("---")
                            if st.button("🚀 SIFIR Frezi Tak ve Stoğu Düş", type="primary", use_container_width=True):
                                f_kod_stok = f_sec.split("|")[0].strip()
                                f_ad_stok = f_sec.split("|")[1].strip() 
                                f_fiyat_tl = float(f_sec.split("|")[2].replace("TL", "").strip())
                                f_fiyat_euro = f_fiyat_tl / 35.0 
                                
                                c.execute("INSERT INTO aktif_frezler (makine_adi, yuva_no, frez_kod, toplam_omur_dk, kullanilan_dk, birim_fiyat_euro, durum, frez_adi) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                                          (makine, yuva, frez_kod, omur, 0, f_fiyat_euro, "Aktif", f_ad_stok))
                                c.execute("UPDATE stok SET Mevcut_Miktar = Mevcut_Miktar - 1 WHERE Urun_Kodu=?", (f_kod_stok,))
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
                    df_aktif = pd.read_sql("SELECT * FROM aktif_frezler WHERE durum='Aktif'", conn)
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
                                            yeni_dk = st.number_input("Dk Ekle", min_value=1, step=15, value=15, key=f"dk_{r['id']}")
                                            if st.button("⏱️ İşle", key=f"btn_dk_{r['id']}"):
                                                c.execute("UPDATE aktif_frezler SET kullanilan_dk = kullanilan_dk + ? WHERE id=?", (yeni_dk, r['id']))
                                                conn.commit(); st.rerun()
                                            st.markdown("---")
                                            if st.button("💥 Kırıldı", type="primary", use_container_width=True, key=f"btn_kirildi_{r['id']}"):
                                                c.execute("UPDATE aktif_frezler SET durum='Kırıldı' WHERE id=?", (r['id'],))
                                                conn.commit(); st.rerun()
                                            if st.button("✅ Arşive Kaldır", use_container_width=True, key=f"btn_doldu_{r['id']}"):
                                                c.execute("UPDATE aktif_frezler SET durum='Ömrü Doldu' WHERE id=?", (r['id'],))
                                                conn.commit(); st.rerun()
                else:
                    st.info("Magazinlerde tanımlı aktif frez yok.")

                st.markdown("---")
                
                # --- 🚨 YEDEKTE BEKLEYEN (KULLANILMIŞ) FREZLER İSTASYONU 🚨 ---
                st.markdown("---")
                st.markdown("#### ⏸️ Yedekte Bekleyen (Kullanılmış) Frezler")
                st.caption("Daha önce magazinden çıkardığınız yarı-ömürlü frezler burada bekler. Bunları tekrar herhangi bir makineye atayabilirsiniz.")
                
                try: 
                    df_yedek = pd.read_sql("SELECT * FROM aktif_frezler WHERE durum='Yedekte'", conn)
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
                                    makine_geri = st.selectbox("Hedef Makine", ["Redon GTR", "Redon Hybrid", "Roland DWX", "Diğer"], key=f"mak_geri_{r['id']}")
                                    
                                    # SEÇİLEN MAKİNEDEKİ BOŞ MAGAZİNLERİ BUL
                                    d_yuv = c.execute("SELECT yuva_no FROM aktif_frezler WHERE makine_adi=? AND durum='Aktif'", (makine_geri,)).fetchall()
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
                    
                    zirkon_stok = c.execute("SELECT Urun_Kodu, Urun_Adi FROM stok WHERE Kategori='Zirkonyum Blok' AND Mevcut_Miktar > 0 AND Durum='Aktif'").fetchall()
                    if zirkon_stok:
                        z_sec = c_blok1.selectbox("Açılacak Blok (Stoktan Düşer)", [f"{z[0]} | {z[1]}" for z in zirkon_stok])
                        b_renk = c_blok2.text_input("Renk ve Boyut")
                        
                        c_blok3.markdown("<br>", unsafe_allow_html=True) # Butonu hizalamak için boşluk
                        if c_blok3.button("🚀 Aç ve CAM'e Ekle", type="primary", use_container_width=True):
                            z_kod = z_sec.split("|")[0].strip()
                            z_ad = z_sec.split("|")[1].strip()
                            yeni_b_kod = f"BLK-{datetime.now().strftime('%M%S')}"
                            c.execute("INSERT INTO cam_bloklar VALUES (?,?,?,?,?,?)", (yeni_b_kod, z_ad, b_renk, 22, 22, "Yarım"))
                            c.execute("UPDATE stok SET Mevcut_Miktar = Mevcut_Miktar - 1 WHERE Urun_Kodu=?", (z_kod,))
                            conn.commit(); st.success(f"Blok Açıldı: {yeni_b_kod}"); st.rerun()
                    else: 
                        st.warning("Ana stokta kullanıma hazır Aktif Zirkonyum Blok kalmamış.")

                st.markdown("---")
                
                # 🚨 FİLTRE DARALTILDI 🚨
                col_filtre, col_fbos = st.columns([1.5, 4])
                min_uye_filtre = col_filtre.number_input("🔍 Min Kalan Üye Filtresi:", min_value=1, max_value=22, value=1)
                
                # 🚨 TABLO YERİNE DİNAMİK YÖNETİM KARTLARI (İLAVE/ÇÖPE AT) 🚨
                df_bloklar = pd.read_sql("SELECT Blok_Kodu, Urun_Adi, Boyut_Renk, Kalan_Uye, Durum FROM cam_bloklar WHERE Durum='Yarım'", conn)
                
                if not df_bloklar.empty: 
                    gosterilecekler = df_bloklar[df_bloklar['Kalan_Uye'] >= min_uye_filtre]
                    for _, r in gosterilecekler.iterrows():
                        with st.container(border=True):
                            cb1, cb2, cb3 = st.columns([2, 1.5, 2])
                            cb1.markdown(f"🧱 **{r['Blok_Kodu']}** | 🏷️ {r['Boyut_Renk']}")
                            cb1.caption(f"Ürün: {r['Urun_Adi']}")
                            
                            yuzde = int((r['Kalan_Uye'] / 22.0) * 100) if r['Kalan_Uye'] <= 22 else 100
                            cb2.progress(yuzde / 100.0, text=f"Kalan: {r['Kalan_Uye']} Üye")
                            
                            with cb3:
                                with st.expander("⚙️ Blok Yönetimi"):
                                    st.caption("Tahmininizden fazla/az üye sığdıysa buradan düzeltebilirsiniz.")
                                    
                                    # Üye ekleme / çıkarma (Mesela +2 yazıp güncelleyebilirsin)
                                    col_y1, col_y2 = st.columns([1.5, 1.5])
                                    ekle_cikar = col_y1.number_input("Miktar Ekle/Çıkar", value=0, step=1, key=f"uye_ayar_{r['Blok_Kodu']}")
                                    
                                    if col_y2.button("💾 Kalanı Güncelle", key=f"btn_uye_{r['Blok_Kodu']}"):
                                        yeni_uye = r['Kalan_Uye'] + ekle_cikar
                                        if yeni_uye <= 0:
                                            # Eğer eksiye düşer veya sıfırlanırsa direkt çöpe atar
                                            c.execute("UPDATE cam_bloklar SET Kalan_Uye=0, Durum='Bitti' WHERE Blok_Kodu=?", (r['Blok_Kodu'],))
                                        else:
                                            c.execute("UPDATE cam_bloklar SET Kalan_Uye=? WHERE Blok_Kodu=?", (yeni_uye, r['Blok_Kodu']))
                                        conn.commit(); st.rerun()
                                    
                                    st.markdown("---")
                                    # Direkt çöpe atma butonu
                                    if st.button("🗑️ Çöpe At (Arşive Kaldır)", type="primary", use_container_width=True, key=f"btn_cop_{r['Blok_Kodu']}"):
                                        c.execute("UPDATE cam_bloklar SET Durum='Bitti', Kalan_Uye=0 WHERE Blok_Kodu=?", (r['Blok_Kodu'],))
                                        conn.commit(); st.success("Blok çöpe atıldı/arşive kaldırıldı!"); st.rerun()
                else:
                    st.info("Kriterlere uygun aktif yarım blok bulunmuyor.")

    elif sayfa == "💰 Finans & Analitik":
        banner_olustur("💰", "Finans ve Analitik Merkezi", "Tahsilatları girin, cari ekstreleri çıkarın ve laboratuvarınızın kârlılığını analiz edin.")
        
        try:
            klinik_liste = c.execute("SELECT Klinik_Unvani FROM cariler WHERE Durum='Aktif'").fetchall()
            klinikler = [k[0] for k in klinik_liste]
        except:
            klinikler = []

        tab_tahsilat, tab_ekstre, tab_gider, tab_analitik, tab_nakit = st.tabs(["💵 Tahsilat Gir", "🧾 Cari Ekstre", "💸 Giderler", "📈 Gerçek Kârlılık (CFO)", "🌊 Nakit Radarı & FP&A Tahminleme"])
        
        with tab_tahsilat:
            if klinikler:
                with st.form("tahsilat_form"):
                    c1, c2 = st.columns(2)
                    t_klinik = c1.selectbox("Ödeme Yapan Klinik", klinikler, key="tah_klinik")
                    t_turu = c2.selectbox("Ödeme Türü", ["Havale / EFT", "Nakit", "Kredi Kartı", "Çek / Senet"], key="tah_tur")
                    t_tutar = c1.number_input("Alınan Tutar (TL)", min_value=0.0, value=0.0, step=100.0, key="tah_tutar")
                    t_aciklama = c2.text_input("Açıklama / Dekont No", key="tah_aciklama")
                    
                    if st.form_submit_button("Tahsilatı Kaydet ve Bakiyeden Düş", type="primary") and t_tutar > 0:
                        c.execute("INSERT INTO tahsilatlar VALUES (?,?,?,?,?)", (datetime.now().strftime("%Y-%m-%d"), t_klinik, t_turu, t_tutar, t_aciklama))
                        c.execute("UPDATE cariler SET Bakiye = Bakiye - ? WHERE Klinik_Unvani = ?", (t_tutar, t_klinik))
                        conn.commit(); st.success("✅ Tahsilat işlendi, cari bakiye güncellendi!"); st.rerun()

        with tab_ekstre:
            if klinikler:
                secilen_klinik_ekstre = st.selectbox("Ekstresini Çıkarmak İstediğiniz Klinik", klinikler, key="ekstre_klinik")
                if st.button("📊 Ekstreyi Hazırla", use_container_width=True):
                    anlik_bakiye = c.execute("SELECT Bakiye FROM cariler WHERE Klinik_Unvani=?", (secilen_klinik_ekstre,)).fetchone()[0]
                    df_borc = pd.read_sql(f"SELECT Tarih, Is_Turu || ' - ' || Hasta_Adi as Islem, Tutar_TL as Borc, 0.0 as Alacak FROM isler WHERE Klinik_Unvani='{secilen_klinik_ekstre}' AND Tutar_TL > 0", conn)
                    df_alacak = pd.read_sql(f"SELECT Tarih, Odeme_Turu || ' Ödemesi (' || Aciklama || ')' as Islem, 0.0 as Borc, Tutar as Alacak FROM tahsilatlar WHERE Klinik_Unvani='{secilen_klinik_ekstre}'", conn)
                    
                    df_ekstre = pd.concat([df_borc, df_alacak]).sort_values(by="Tarih").reset_index(drop=True)
                    toplam_yazilan_borc = df_ekstre['Borc'].sum() if not df_ekstre.empty else 0
                    toplam_alinan_odeme = df_ekstre['Alacak'].sum() if not df_ekstre.empty else 0
                    devreden_bakiye = anlik_bakiye - toplam_yazilan_borc + toplam_alinan_odeme
                    
                    ilk_satir = pd.DataFrame({"Tarih": ["-"], "Islem": ["Devreden Bakiyesi"], "Borc": [devreden_bakiye if devreden_bakiye > 0 else 0], "Alacak": [abs(devreden_bakiye) if devreden_bakiye < 0 else 0]})
                    df_ekstre = pd.concat([ilk_satir, df_ekstre], ignore_index=True)
                    df_ekstre['Kümülatif Bakiye'] = df_ekstre['Borc'].cumsum() - df_ekstre['Alacak'].cumsum()
                    
                    st.dataframe(df_ekstre.style.format({"Borc": "{:,.2f}", "Alacak": "{:,.2f}", "Kümülatif Bakiye": "{:,.2f}"}), hide_index=True, use_container_width=True)
                    try:
                        pdf_dosyasi_admin = ekstre_pdf_uret(secilen_klinik_ekstre, df_ekstre, anlik_bakiye)
                        st.download_button("📥 PDF Olarak İndir & Yazdır", data=pdf_dosyasi_admin, file_name=f"{secilen_klinik_ekstre}_Ekstre.pdf", mime="application/pdf", use_container_width=True)
                    except: pass

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
                        c.execute("INSERT INTO giderler VALUES (?,?,?,?)", (datetime.now().strftime("%Y-%m-%d"), kat, acik, tut))
                        conn.commit(); st.success("✅ Gider kaydedildi!"); st.rerun()
            
            st.markdown("#### 📑 Son Gider Hareketleri")
            df_giderler = pd.read_sql("SELECT * FROM giderler ORDER BY Tarih DESC", conn)
            st.dataframe(df_giderler, hide_index=True, use_container_width=True)
            
        with tab_analitik:
            st.markdown("""<style>.cfo-card { background: linear-gradient(145deg, rgba(15, 23, 42, 0.8) 0%, rgba(30, 41, 59, 0.4) 100%); border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 16px; padding: 25px 15px; text-align: center; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.4); backdrop-filter: blur(10px); transition: transform 0.3s ease, border-color 0.3s ease; margin-bottom: 20px; } .cfo-card:hover { transform: translateY(-5px); border-color: rgba(56, 189, 248, 0.8); } .cfo-title { color: #94a3b8; font-size: 15px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 10px; } .cfo-val-blue { color: #38bdf8; font-size: 38px; font-weight: 900; text-shadow: 0 0 15px rgba(56,189,248,0.4); } .cfo-val-red { color: #f87171; font-size: 38px; font-weight: 900; text-shadow: 0 0 15px rgba(248,113,113,0.4); } .cfo-val-green { color: #34d399; font-size: 38px; font-weight: 900; text-shadow: 0 0 15px rgba(52,211,153,0.4); } .cfo-val-gray { color: #cbd5e1; font-size: 38px; font-weight: 900; } .cfo-sub { color: #64748b; font-size: 14px; font-weight: 600; margin-top: 8px; } .cfo-sub-down { color: #f87171; font-weight: bold; } .cfo-sub-up { color: #34d399; font-weight: bold; }</style>""", unsafe_allow_html=True)
            
            euro_kuru = 53.0
            try:
                df_is_f = pd.read_sql("SELECT Klinik_Unvani, Is_Turu, Tutar_TL FROM isler", conn)
                toplam_gelir = df_is_f['Tutar_TL'].sum() if not df_is_f.empty else 0
            except: df_is_f = pd.DataFrame(); toplam_gelir = 0
            
            try:
                df_tum_giderler = pd.read_sql("SELECT * FROM giderler", conn)
                if not df_tum_giderler.empty:
                    gider_tur_kolonu = df_tum_giderler.columns[1] 
                    gider_tutar_kolonu = df_tum_giderler.columns[3]
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

        with tab_nakit:
            st.markdown("### 🌊 CFO Radarı: Nakit Akışı ve Gelecek Tahminleme (FP&A)")
            st.info("2. Madde (Bütçe Tahminleme) ve 3. Madde (Likidite/Tahsilat Yönetimi) prensiplerine göre çalışır.")
            
            euro_kuru = 53.0
            mevcut_ay = datetime.now().strftime("%Y-%m")
            bugun_gun = datetime.now().day
            
            try:
                toplam_alacak = c.execute("SELECT sum(Bakiye) FROM cariler WHERE Bakiye > 0").fetchone()[0] or 0
                bu_ay_tahsilat = c.execute(f"SELECT sum(Tutar) FROM tahsilatlar WHERE Tarih LIKE '{mevcut_ay}%'").fetchone()[0] or 0
                bu_ay_fatura = c.execute(f"SELECT sum(Tutar_TL) FROM isler WHERE Tarih LIKE '{mevcut_ay}%'").fetchone()[0] or 0
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

    elif sayfa == "📋 Fiyat Listesi":
            banner_olustur("📋", "Fiyat Listesi & Döküman Merkezi", "Hizmet bedellerini yönetin ve kurumsal dökümanları (Katalog, Fatura vb.) yükleyin.")
            
            # 🚨 4 ANA SEKME BURADA BAŞLIYOR 🚨
            tab1, tab2, tab3, tab4 = st.tabs(["➕ Yeni Hizmet Ekle", "📊 Hizmet Listesi", "💎 BGS Blok Fiyatları", "📁 Dökümanlar & Katalog"])
            
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
                            c.execute("INSERT INTO fiyat_listesi VALUES (?,?,?,?)", (kat_sec, h_ad, h_fiyat, h_doviz))
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
                                col_t_ana, col_t_bos = st.columns([3, 1.5])
                                
                                with col_t_ana:
                                    # 🚨 BOL SIFIRLARI KALDIRAN ( {:,.2f} ) VE ORTALAYAN KOD 🚨
                                    st.dataframe(
                                        df_kat[["Hizmet_Adi", "Fiyat", "Para_Birimi"]]
                                        .style.format({"Fiyat": "{:,.2f}"})
                                        .set_properties(**{'text-align': 'center'}),
                                        hide_index=True, 
                                        use_container_width=True
                                    )
                else:
                    st.info("Sistemde henüz kayıtlı hizmet fiyatı bulunamadı.")

            # ==========================================
            # TAB 3: BGS BLOK FİYATLARI (EURO)
            # ==========================================
            with tab3:
                st.markdown("### 💎 BGS Blok Satış Fiyatları (Euro)")
                
                st.markdown("#### ✏️ Fiyat Güncelleme")
                col_b1, col_b2, col_b_bos = st.columns([2, 1.2, 2.5])
                
                df_bgs_mevcut = pd.read_sql("SELECT Urun_Adi, Satis_Fiyati, Birim FROM stok WHERE Kategori LIKE '%Blok%'", conn)
                
                with st.form("bgs_fiyat_form"):
                    blok_listesi = df_bgs_mevcut["Urun_Adi"].tolist() if not df_bgs_mevcut.empty else []
                    secilen_bgs = col_b1.selectbox("Blok Seçin", ["-- Seçiniz --"] + blok_listesi)
                    
                    yeni_bgs_fiyat = col_b2.number_input("Yeni Birim Fiyat (Euro)", min_value=0.0, step=5.0)
                    
                    if st.form_submit_button("💾 Fiyatı Güncelle", type="primary"):
                        if secilen_bgs != "-- Seçiniz --":
                            c.execute("UPDATE stok SET Satis_Fiyati=? WHERE Urun_Adi=?", (yeni_bgs_fiyat, secilen_bgs))
                            conn.commit(); st.success(f"✅ {secilen_bgs} fiyatı {yeni_bgs_fiyat} € olarak güncellendi."); st.rerun()

                st.markdown("---")
                st.markdown("#### 📊 Güncel Blok Fiyat Listesi")
                
                # Tablo sola yaslandı ve daraltıldı
                col_t_ana, col_t_bos = st.columns([2, 4])
                
                with col_t_ana:
                    if not df_bgs_mevcut.empty:
                        st.dataframe(
                            df_bgs_mevcut.style.format({"Satis_Fiyati": "{:,.2f} €"}).set_properties(**{'text-align': 'center'}),
                            hide_index=True,
                            use_container_width=True
                        )
                    else:
                        st.info("Sistemde henüz kayıtlı blok fiyatı bulunamadı.")

            # ==========================================
            # TAB 4: DÖKÜMANLAR & KATALOG
            # ==========================================
            with tab4:
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

    elif sayfa == "📉 Maliyet Analizi":
        banner_olustur("📉", "Birim Maliyet & Kârlılık Analizi", "Aylık bazda üretim maliyetlerinizi hesaplayın ve gerçek kâr marjınızı görün.")
        
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
            
        euro_kuru = 35.0 
        
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
        tab_m1, tab_m2 = st.tabs(["📊 Dönemsel Maliyet Motoru", "⚙️ Değişken Ayarları"])

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
                # Artık manuel değil, seçilen aydaki gerçek iş sayısını varsayılan getiriyoruz!
                aylik_is_adedi = st.number_input(f"{secilen_ay} Üretim Hacmi (Üye)", min_value=1, value=gercek_is_adedi, help="Seçilen dönemde yapılan toplam gerçek iş sayınız. Giderler buna bölünür.")
                blok_verim = st.number_input("1 Bloktan Çıkan Üye", value=22)
                uye_kazima_dk = st.number_input("1 Üye Ortalama Kazıma (Dakika)", value=15.0, step=1.0)
                
                st.markdown("---")
                st.markdown("#### 🔄 Frez Algoritması")
                st.text_input("Frez Dakika Maliyeti", value=f"{ortalama_dk_maliyet_tl:,.2f} TL / Dk", disabled=True)

        with tab_m1:
            # --- HESAPLAMA MOTORU ---
            # BUG DÜZELTİLDİ: tab_m2'de tanımlanan değişkenler burada kullanılır;
            # eğer tab_m2 hiç açılmadıysa varsayılan değerler atanır.
            if 'total_sabit_gider' not in dir(): total_sabit_gider = toplam_maas + toplam_finans_gideri
            if 'aylik_is_adedi' not in dir(): aylik_is_adedi = gercek_is_adedi
            if 'blok_verim' not in dir(): blok_verim = 22
            if 'uye_kazima_dk' not in dir(): uye_kazima_dk = 15.0
            birim_sabit_maliyet = total_sabit_gider / aylik_is_adedi if aylik_is_adedi > 0 else 0
            birim_blok_maliyeti = bgs_blok_tl / blok_verim if blok_verim > 0 else 0
            birim_frez_maliyeti = uye_kazima_dk * ortalama_dk_maliyet_tl
            birim_sarf_maliyet = 50.0 
            
            toplam_birim_maliyet = birim_sabit_maliyet + birim_blok_maliyeti + birim_frez_maliyeti + birim_sarf_maliyet
            
            st.markdown(f"### 🎯 1 Üye (Diş) Gerçek Maliyet Analizi - Dönem: {secilen_ay}")
            
            m_col1, m_col2, m_col3 = st.columns(3)
            m_col1.metric("İşletme Sabit Payı", f"{birim_sabit_maliyet:,.2f} TL")
            m_col2.metric("Üretim Sarfiyatı", f"{(birim_blok_maliyeti + birim_frez_maliyeti + birim_sarf_maliyet):,.2f} TL")
            m_col3.metric("BİRİM MALİYET", f"{toplam_birim_maliyet:,.2f} TL", delta_color="inverse")
            
            st.markdown("---")
            
            # --- KÂRLILIK TESTİ ---
            st.markdown(f"#### 💰 Satış ve Kâr Simülasyonu ({secilen_ay})")
            c_test1, c_test2 = st.columns([2, 1])
            
            with c_test1:
                satis_fiyati = st.slider("Hedef Satış Fiyatı (Üye Başı)", min_value=0, max_value=5000, value=1200)
            
            net_kar = satis_fiyati - toplam_birim_maliyet
            kar_orani = (net_kar / satis_fiyati) * 100 if satis_fiyati > 0 else 0
            
            with c_test2:
                if net_kar > 0:
                    st.success(f"Net Kâr: {net_kar:,.2f} TL\n\nMarj: %{kar_orani:.1f}")
                else:
                    st.error(f"Zarar: {net_kar:,.2f} TL")
            
            if kar_orani > 0 and kar_orani < 30:
                st.warning("⚠️ Kâr marjınız kritik seviyede (%30 altı). Giderleri veya üretim süresini gözden geçirin.")
            elif kar_orani >= 30:
                st.info("✅ Operasyonel kârlılığınız hedeflenen laboratuvar standartlarındadır.")       
    elif sayfa == "🔧 Cihaz Bakımı":
        banner_olustur("🔧", "Cihaz Bakımı ve Makine Parkuru", "Makine ömürlerini uzatın, periyodik bakımları yönetin ve akıllı mühendislik asistanından yararlanın.")
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
                            st.caption(row['Kategori'])
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
                            c.execute("INSERT INTO cihaz_bakim_gecmisi VALUES (?,?,?,?,?)", (secilen_cihaz, bugun_str, yapilan_islem_metni, bakim_maliyeti, "Sistem Onaylı"))
                            if bakim_maliyeti > 0: c.execute("INSERT INTO giderler VALUES (?,?,?,?)", (bugun_str, "Fatura/Bakım", f"{secilen_cihaz}: {yapilan_islem_metni}", bakim_maliyeti))
                        
                        conn.commit(); st.success("✅ Makine bakımı başarıyla veri tabanına işlendi!"); st.rerun()

        with tab_yeni:
            with st.form("yeni_cihaz_formu"):
                c1, c2 = st.columns(2)
                c_adi = c1.text_input("Cihaz Adı / Markası")
                c_kat = c2.selectbox("Kategori", ["Kazıma Makinesi (Milling)", "Fırın (Sinter/Porselen)", "3D Yazıcı", "Tarayıcı (Scanner)", "Yardımcı Ekipman"])
                c_bakim_siniri = c1.number_input("Spindle/Parça Ömrü (Saat veya Döngü)", min_value=1.0, value=500.0)
                yuklenen_cihaz_gorsel = st.file_uploader("Makinenin Fotoğrafını Seç", type=["png", "jpg", "jpeg"])
                if st.form_submit_button("Cihazı Sisteme Ekle") and c_adi:
                    dosya_yolu = "-"
                    if yuklenen_cihaz_gorsel:
                        dosya_yolu = os.path.join("uploads", "cihazlar", f"{datetime.now().strftime('%H%M%S')}_{yuklenen_cihaz_gorsel.name}")
                        dosya_yolu = storage_utils.dosya_kaydet(os.path.dirname(dosya_yolu), os.path.basename(dosya_yolu), yuklenen_cihaz_gorsel)
                    bugun_str = datetime.now().strftime('%Y-%m-%d')
                    c.execute("INSERT INTO cihazlar (Cihaz_Adi, Kategori, Calisma_Saati, Bakim_Siniri, Son_Bakim_Tarihi, Durum, Gorsel_Yolu, Haftalik_Hedef, Aylik_Hedef, Yillik_Hedef) VALUES (?,?,?,?,?,?,?,?,?,?)", 
                              (c_adi, c_kat, 0.0, c_bakim_siniri, bugun_str, "Aktif", dosya_yolu, (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d'), (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'), (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d')))
                    conn.commit(); st.rerun()

        with tab_guncelle:
            st.markdown("<h4 style='color: #38BDF8;'>✏️ Kayıtlı Cihazı Düzenle</h4>", unsafe_allow_html=True)
            cihaz_listesi_guncelle = [row[0] for row in c.execute("SELECT Cihaz_Adi FROM cihazlar").fetchall()]
            if cihaz_listesi_guncelle:
                secilen_guncelle = st.selectbox("Düzenlenecek Cihazı Seçin", cihaz_listesi_guncelle, key="guncelle_secim")
                g_veri = c.execute("SELECT Cihaz_Adi, Kategori, Bakim_Siniri, Gorsel_Yolu FROM cihazlar WHERE Cihaz_Adi=?", (secilen_guncelle,)).fetchone()
                
                with st.form("cihaz_guncelle_formu"):
                    c1, c2 = st.columns(2)
                    yeni_adi = c1.text_input("Cihaz Adı / Markası", value=g_veri[0])
                    
                    kategoriler_list = ["Kazıma Makinesi (Milling)", "Fırın (Sinter/Porselen)", "3D Yazıcı", "Tarayıcı (Scanner)", "Yardımcı Ekipman"]
                    idx_kat = kategoriler_list.index(g_veri[1]) if g_veri[1] in kategoriler_list else 0
                    yeni_kat = c2.selectbox("Kategori", kategoriler_list, index=idx_kat)
                    
                    yeni_sinir = c1.number_input("Spindle/Parça Ömrü (Saat veya Döngü)", min_value=1.0, value=float(g_veri[2]))
                    yeni_gorsel = st.file_uploader("Yeni Fotoğraf Seç (Sadece değiştirmek istiyorsanız)", type=["png", "jpg", "jpeg"])
                    
                    if st.form_submit_button("💾 Değişiklikleri Kaydet"):
                        guncel_yol = g_veri[3]
                        if yeni_gorsel:
                            guncel_yol = os.path.join("uploads", "cihazlar", f"{datetime.now().strftime('%H%M%S')}_{yeni_gorsel.name}")
                            guncel_yol = storage_utils.dosya_kaydet(os.path.dirname(guncel_yol), os.path.basename(guncel_yol), yeni_gorsel)
                        
                        c.execute("UPDATE cihazlar SET Cihaz_Adi=?, Kategori=?, Bakim_Siniri=?, Gorsel_Yolu=? WHERE Cihaz_Adi=?", (yeni_adi, yeni_kat, yeni_sinir, guncel_yol, secilen_guncelle))
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
                        else: c.execute("INSERT INTO engellemeler VALUES (?, ?)", (benim_id, karsi_id))
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