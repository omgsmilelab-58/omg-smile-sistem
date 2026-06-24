from dotenv import load_dotenv
load_dotenv()
import os
case_map = {'email': 'Email', 'kategori': 'Kategori', 'baslama_tarihi': 'Baslama_Tarihi', 'aciklama': 'Aciklama', 'telefon': 'Telefon', 'kalan_uye': 'Kalan_Uye', 'alici': 'Alici', 'id': 'id', 'barkod': 'Barkod', 'tutar_tl': 'Tutar_TL', 'ayrilma_tarihi': 'Ayrilma_Tarihi', 'maas': 'Maas', 'klinik_id': 'klinik_id', 'kurucu_id': 'kurucu_id', 'engellenen_id': 'engellenen_id', 'asistan_kadi': 'Asistan_Kadi', 'risk_limiti': 'Risk_Limiti', 'birim': 'Birim', 'bitis_tarihi': 'Bitis_Tarihi', 'ayar_degeri': 'Ayar_Degeri', 'baslangic_tarihi': 'Baslangic_Tarihi', 'kullanici': 'Kullanici', 'klinik_unvani': 'Klinik_Unvani', 'gun_sayisi': 'Gun_Sayisi', 'zaman': 'zaman', 'is_turu': 'Is_Turu', 'isim': 'isim', 'mevcut_miktar': 'Mevcut_Miktar', 'blok_kodu': 'Blok_Kodu', 'aksiyon': 'Aksiyon', 'toplam_omur_dk': 'toplam_omur_dk', 'sifre': 'Sifre', 'teslim_tarihi': 'Teslim_Tarihi', 'lot_numarasi': 'Lot_Numarasi', 'ad_soyad': 'Ad_Soyad', 'calisma_saati': 'Calisma_Saati', 'yillik_hedef': 'Yillik_Hedef', 'cihaz_adi': 'Cihaz_Adi', 'goruldu': 'Goruldu', 'is_id': 'Is_ID', 'tarih': 'Tarih', 'islem_turu': 'Islem_Turu', 'bakim_siniri': 'Bakim_Siniri', 'alici_id': 'alici_id', 'kullanici_adi': 'Kullanici_Adi', 'gorsel_yolu': 'Gorsel_Yolu', 'kritik_sinir': 'Kritik_Sinir', 'gonderen_id': 'gonderen_id', 'tutar': 'Tutar', 'urun_kodu': 'Urun_Kodu', 'max_omur_dk': 'Max_Omur_Dk', 'durum': 'Durum', 'aylik_hedef': 'Aylik_Hedef', 'frez_kod': 'frez_kod', 'dokuman_adi': 'Dokuman_Adi', 'dosya_turu': 'Dosya_Turu', 'sorumlu_personel': 'Sorumlu_Personel', 'kullanici_id': 'kullanici_id', 'hizmet_adi': 'Hizmet_Adi', 'makine_adi': 'makine_adi', 'yuva_no': 'yuva_no', 'mesaj': 'Mesaj', 'icerik': 'icerik', 'bakiye': 'Bakiye', 'sertifika_no': 'Sertifika_No', 'personel_adi': 'Personel_Adi', 'kullanilan_dk': 'kullanilan_dk', 'gorevi': 'Gorevi', 'harcanan_malzeme': 'Harcanan_Malzeme', 'boyut_renk': 'Boyut_Renk', 'islem': 'Islem', 'kapasite_uye': 'Kapasite_Uye', 'fiyat': 'Fiyat', 'duyuru_id': 'duyuru_id', 'urun_adi': 'Urun_Adi', 'kalan_omur_dk': 'Kalan_Omur_Dk', 'hasta_adi': 'Hasta_Adi', 'odeme_turu': 'Odeme_Turu', 'frez_kodu': 'Frez_Kodu', 'uyumlu_makine': 'Uyumlu_Makine', 'para_birimi': 'Para_Birimi', 'engelleyen_id': 'engelleyen_id', 'son_bakim_tarihi': 'Son_Bakim_Tarihi', 'renk': 'Renk', 'grup_adi': 'grup_adi', 'ayar_adi': 'Ayar_Adi', 'satis_fiyati': 'Satis_Fiyati', 'indirim_orani': 'Indirim_Orani', 'grup_id': 'grup_id', 'dosya_yolu': 'Dosya_Yolu', 'haftalik_hedef': 'Haftalik_Hedef', 'saat': 'Saat', 'maliyet': 'Maliyet', 'tarih_saat': 'Tarih_Saat', 'asama': 'Asama', 'yetkili_kisi': 'Yetkili_Kisi', 'birim_fiyat_euro': 'birim_fiyat_euro', 'tip': 'tip', 'gonderen': 'Gonderen', 'tc_no': 'TC_No', 'iban': 'IBAN', 'kalan_izin': 'Kalan_Izin', 'foto_yolu': 'Foto_Yolu', 'cv_yolu': 'CV_Yolu', 'firma_unvani': 'Firma_Unvani', 'vergi_dairesi': 'Vergi_Dairesi', 'vergi_no': 'Vergi_No', 'vip_seviye': 'VIP_Seviye', 'bildirim_kurye': 'Bildirim_Kurye', 'bildirim_fatura': 'Bildirim_Fatura', 'bildirim_asama': 'Bildirim_Asama', 'otopilot_kategori': 'Otopilot_Kategori', 'otopilot_islem': 'Otopilot_Islem', 'otopilot_renk': 'Otopilot_Renk', 'adres': 'Adres', 'marka': 'Marka', 'malzeme': 'Malzeme', 'kalinlik': 'Kalinlik'}
import sqlite3
import re
import streamlit as st

USE_POSTGRES = os.getenv("USE_POSTGRES", "False").lower() == "true"

if USE_POSTGRES:
    try:
        import psycopg2
        from psycopg2 import pool
    except ImportError:
        st.error("psycopg2 yüklü değil. Bulut bağlantısı çalışmaz.")

# PostgreSQL bağlantı havuzları
_pg_pool_erp = None
_pg_pool_dentflow = None

def get_pg_pool(db_name):
    global _pg_pool_erp, _pg_pool_dentflow
    
    # Render, Cloud SQL veya doğrudan IP bağlantı string'leri kullanılabilir
    db_host = os.getenv("DB_HOST", "localhost")
    db_user = os.getenv("DB_USER", "postgres")
    db_pass = os.getenv("DB_PASS", "postgres")
    db_port = os.getenv("DB_PORT", "5432")
    
    # Hangi DB?
    pg_db_name = "omg_smile_erp" if "erp" in db_name.lower() else "dentflow"
    
    if pg_db_name == "omg_smile_erp":
        if _pg_pool_erp is None:
            _pg_pool_erp = psycopg2.pool.ThreadedConnectionPool(
                1, 20, user=db_user, password=db_pass, host=db_host, port=db_port, database=pg_db_name
            )
        return _pg_pool_erp
    else:
        if _pg_pool_dentflow is None:
            _pg_pool_dentflow = psycopg2.pool.ThreadedConnectionPool(
                1, 20, user=db_user, password=db_pass, host=db_host, port=db_port, database=pg_db_name
            )
        return _pg_pool_dentflow

class CursorWrapper:
    """
    Bu sınıf, PostgreSQL cursor'ını sarmalar ve SQLite'ın '?' parametrelerini
    PostgreSQL'in '%s' parametrelerine dönüştürür. 
    Böylece ana kodda hiçbir SQL sorgusunu elle değiştirmek gerekmez.
    """
    def __init__(self, pg_cursor):
        self.cursor = pg_cursor
        self.rowcount = -1
        self.lastrowid = None

    def _convert_query(self, query):
        # ? işaretlerini %s ile değiştirir. 
        # NOT: Eğer string içinde ? varsa bu da değişir (örneğin "Nasılsın?"). 
        # Omg Smile Sisteminde genelde ? sadece parametre olarak kullanılıyor.
        return query.replace("?", "%s")

    @property
    def description(self):
        desc = self.cursor.description
        if not desc:
            return None
        
        # case_map moved to top level
        
        new_desc = []
        for col in desc:
            col_name = col[0]
            mapped_name = case_map.get(col_name.lower(), col_name)
            new_col = (mapped_name,) + col[1:]
            new_desc.append(new_col)
        
        return new_desc

    def execute(self, query, parameters=None):
        pg_query = self._convert_query(query)
        is_insert = "INSERT " in pg_query.upper()
        needs_returning = is_insert and "RETURNING" not in pg_query.upper() and any(t in pg_query.upper() for t in ["INTO ISLER", "INTO KURYE_ISLEMLERI", "INTO GRUPLAR", "INTO AKTIF_FREZLER"])
        
        if needs_returning:
            pg_query += " RETURNING id"

        if parameters:
            self.cursor.execute(pg_query, parameters)
        else:
            self.cursor.execute(pg_query)
        
        self.rowcount = self.cursor.rowcount
        try:
            if needs_returning:
                self.lastrowid = self.cursor.fetchone()[0]
            elif is_insert:
                self.lastrowid = None
        except:
            self.lastrowid = None
            
        return self

    def executemany(self, query, seq_of_parameters):
        pg_query = self._convert_query(query)
        self.cursor.executemany(pg_query, seq_of_parameters)
        return self

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()
        
    def close(self):
        self.cursor.close()


class ConnectionWrapper:
    """
    PostgreSQL bağlantısını sarmalar.
    """
    def __init__(self, pg_conn, pool_obj):
        self.conn = pg_conn
        self.pool_obj = pool_obj
        self._closed = False

    def __del__(self):
        try:
            self.close()
        except:
            pass

    def cursor(self):
        return CursorWrapper(self.conn.cursor())

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def execute(self, query, parameters=None):
        cur = self.cursor()
        return cur.execute(query, parameters)

    def close(self):
        # Bağlantıyı kapatmak yerine havuza geri koy
        if not getattr(self, '_closed', False):
            try:
                self.pool_obj.putconn(self.conn)
            except:
                pass
            self._closed = True


def get_connection(db_name="omg_smile_erp.db", check_same_thread=False, timeout=20):
    """
    Bulut modundaysa PostgreSQL bağlantısı (Sarmalanmış halde),
    Yerel moddaysa standart SQLite bağlantısı döner.
    """
    if USE_POSTGRES:
        pool_obj = get_pg_pool(db_name)
        pg_conn = pool_obj.getconn()
        pg_conn.autocommit = True
        return ConnectionWrapper(pg_conn, pool_obj)
    else:
        # Standart SQLite bağlantısı
        kwargs = {}
        if check_same_thread is not None:
            kwargs['check_same_thread'] = check_same_thread
        if timeout is not None:
            kwargs['timeout'] = timeout
            
        return sqlite3.connect(db_name, **kwargs)
