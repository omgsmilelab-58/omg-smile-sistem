from dotenv import load_dotenv
load_dotenv()
import os
import io
import streamlit as st
from google.cloud import storage

# Local vs Cloud modu
USE_CLOUD_STORAGE = os.getenv("USE_CLOUD_STORAGE", "False").lower() == "true"
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "omg-smile-uploads")

# GCS İstemcisi (Sadece Cloud modu açıksa yüklenir)
_storage_client = None
def _get_storage_client():
    global _storage_client
    if _storage_client is None:
        try:
            _storage_client = storage.Client()
        except Exception as e:
            st.error(f"GCS Bağlantı Hatası: {e}")
    return _storage_client

def dosya_kaydet(hedef_dizin, dosya_adi, dosya_objesi):
    """
    Dosyayı kaydeder. Cloud modu açıksa GCS'ye, kapalıysa lokale kaydeder.
    dosya_objesi: st.file_uploader'dan gelen obje (BytesIO)
    Returns: Dosyanın URL'si veya lokal yolu
    """
    if USE_CLOUD_STORAGE:
        try:
            client = _get_storage_client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            
            # GCS'de hedef_dizin/dosya_adi şeklinde yol (slash'li)
            blob_path = f"{hedef_dizin}/{dosya_adi}".replace("\\", "/")
            # Eğer başta / varsa kaldır (GCS sevmez)
            if blob_path.startswith("/"): blob_path = blob_path[1:]
                
            blob = bucket.blob(blob_path)
            
            # Dosyayı byte olarak yükle
            dosya_byte = dosya_objesi.getbuffer() if hasattr(dosya_objesi, 'getbuffer') else dosya_objesi.read()
            blob.upload_from_string(dosya_byte)
            
            # Public okuma izni ver (eğer bucket uniform access ise bu patlayabilir, o yüzden bucket ayarlarında public access verilmeli)
            try:
                blob.make_public()
            except:
                pass
                
            return blob.public_url
        except Exception as e:
            st.error(f"Dosya Cloud'a yüklenemedi: {e}")
            return f"{hedef_dizin}/{dosya_adi}"
    else:
        # Lokal Kayıt
        if not os.path.exists(hedef_dizin):
            os.makedirs(hedef_dizin, exist_ok=True)
            
        tam_yol = os.path.join(hedef_dizin, dosya_adi)
        # Windows yollarını normalize et
        tam_yol = tam_yol.replace("\\", "/")
        
        with open(tam_yol, "wb") as f:
            if hasattr(dosya_objesi, 'getbuffer'):
                f.write(dosya_objesi.getbuffer())
            else:
                f.write(dosya_objesi.read())
                
        return tam_yol

import requests
import tempfile

def yerel_yol_getir(yol_veya_url):
    """
    Eğer gelen yol bir URL ise (GCS), bunu /tmp içine indirir ve yerel yolunu döner.
    STL okuma gibi sadece yerel dosya kabul eden kütüphaneler için kullanılır.
    """
    if yol_veya_url.startswith("http"):
        try:
            response = requests.get(yol_veya_url)
            response.raise_for_status()
            fd, temp_path = tempfile.mkstemp(suffix=".stl")
            with os.fdopen(fd, "wb") as out:
                out.write(response.content)
            return temp_path
        except Exception as e:
            st.error(f"STL indirilemedi: {e}")
            return yol_veya_url
    return yol_veya_url

