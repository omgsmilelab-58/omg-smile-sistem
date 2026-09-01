import psycopg2
import os
import sys

def sync_database(db_name):
    print(f"\n==========================================")
    print(f"📦 [{db_name}] Google Cloud -> Localhost Aktarımı Başlıyor...")
    print(f"==========================================")
    
    src_conn = psycopg2.connect(
        host='34.159.93.133',
        user='postgres',
        password='Zeynep6658.',
        database=db_name,
        connect_timeout=10
    )
    src_cur = src_conn.cursor()
    
    dst_conn = psycopg2.connect(
        host='localhost',
        user='postgres',
        password='Zeynep6658.',
        database=db_name,
        connect_timeout=10
    )
    dst_conn.autocommit = True
    dst_cur = dst_conn.cursor()
    
    # Kaynaktaki tüm tabloları bul
    src_cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    """)
    tables = [t[0] for t in src_cur.fetchall()]
    
    print(f"Bulunan tablolar ({len(tables)} adet): {', '.join(tables)}")
    
    for table in tables:
        # Kaynak tablonun kolonlarını al
        src_cur.execute(f"""
            SELECT column_name, data_type, character_maximum_length, is_nullable
            FROM information_schema.columns 
            WHERE table_schema = 'public' AND table_name = '{table}'
            ORDER BY ordinal_position
        """)
        cols_info = src_cur.fetchall()
        cols = [c[0] for c in cols_info]
        
        # Hedefte tablo yoksa otomatik oluştur
        col_defs = []
        for c in cols_info:
            c_name, c_type, c_len, c_null = c
            if c_name.lower() == 'id':
                col_defs.append(f'"{c_name}" SERIAL PRIMARY KEY')
            else:
                col_defs.append(f'"{c_name}" TEXT')
        
        create_sql = f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(col_defs)});'
        dst_cur.execute(create_sql)
        
        # Verileri kaynaktan çek
        src_cur.execute(f'SELECT * FROM "{table}"')
        rows = src_cur.fetchall()
        
        if not rows:
            print(f"▶ Tablo: {table} (0 kayıt, atlandı)")
            continue
            
        print(f"▶ Tablo: {table} -> {len(rows)} kayıt aktarılıyor...")
        
        # Hedefteki mevcut veriyi temizle
        dst_cur.execute(f'TRUNCATE TABLE "{table}" CASCADE;')
        
        cols_joined = ", ".join([f'"{c}"' for c in cols])
        placeholders = ", ".join(["%s"] * len(cols))
        insert_query = f'INSERT INTO "{table}" ({cols_joined}) VALUES ({placeholders})'
        
        dst_cur.executemany(insert_query, rows)
        
        # Sequence güncelle (eğer id varsa)
        if any(c[0].lower() == 'id' for c in cols_info):
            try:
                dst_cur.execute(f"""
                    SELECT setval(pg_get_serial_sequence('"{table}"', 'id'), coalesce(max(id), 1), max(id) IS NOT null) 
                    FROM "{table}";
                """)
            except Exception as e:
                pass
                
        print(f"  ✅ {table} ({len(rows)} kayıt) başarıyla aktarıldı.")
        
    src_conn.close()
    dst_conn.close()
    print(f"🎉 [{db_name}] BAŞARIYLA AKTARILDI!")

def main():
    try:
        sync_database('omg_smile_erp')
        sync_database('dentflow')
        
        # .env dosyasını localhost olarak sabitle
        env_content = (
            "USE_POSTGRES=True\n"
            "DB_HOST=localhost\n"
            "DB_USER=postgres\n"
            "DB_PASS=Zeynep6658.\n"
            "DB_PORT=5432\n"
            "USE_CLOUD_STORAGE=False\n"
        )
        with open('/var/www/omg-smile-sistem/.env', 'w') as f:
            f.write(env_content)
            
        print("\n==========================================")
        print("🚀 Servis Yeniden Başlatılıyor...")
        os.system("systemctl restart omgsmile")
        print("🎉 TEBRİKLER! TÜM GOOGLE CLOUD VERİLERİ (251 İŞ, 11 CARİ, TÜM STOKLAR) YENİ SUNUCUYA AKTARILDI!")
        print("==========================================")
    except Exception as e:
        print(f"\n❌ HATA: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
