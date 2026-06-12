FROM python:3.10-slim

WORKDIR /app

# Sistem bağımlılıkları (psycopg2 için)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Gereksinimleri kopyala ve yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Tüm dosyaları kopyala
COPY . .

# Port ayarı
EXPOSE 8501

# Start komutu - Exec form kullanıyoruz ki CRLF sorunu olmasın
# Veritabanı kur betiğini ayrıca çağırıyoruz. Eğer o patlarsa streamlit yine de çalışsın.
CMD ["sh", "-c", "python veritabani_kur.py || true; streamlit run ana_program.py --server.port=8501 --server.address=0.0.0.0"]
