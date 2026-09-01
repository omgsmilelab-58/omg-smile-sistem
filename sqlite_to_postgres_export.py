import sqlite3
import os

def export_sqlite_to_sql():
    dbs = {
        'omg_smile_erp': 'omg_smile_erp.db',
        'dentflow': 'dentflow.db'
    }
    
    for db_name, db_file in dbs.items():
        if not os.path.exists(db_file):
            print(f"{db_file} bulunamadı, atlanıyor.")
            continue
            
        conn = sqlite3.connect(db_file)
        cur = conn.cursor()
        
        output_sql = f"{db_name}_data.sql"
        print(f"[{db_name}] Aktarılıyor -> {output_sql}...")
        
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [t[0] for t in cur.fetchall()]
        
        with open(output_sql, 'w', encoding='utf-8') as f:
            f.write(f"-- {db_name} Veri Yedek / Aktarım Dosyası\n")
            f.write("SET client_encoding = 'UTF8';\n")
            f.write("SET standard_conforming_strings = on;\n\n")
            
            for table in tables:
                cur.execute(f"PRAGMA table_info(\"{table}\")")
                columns_info = cur.fetchall()
                cols = [c[1] for c in columns_info]
                
                cur.execute(f"SELECT * FROM \"{table}\"")
                rows = cur.fetchall()
                
                if not rows:
                    continue
                    
                table_lower = table.lower()
                cols_joined = ", ".join([f'"{c.lower()}"' for c in cols])
                
                f.write(f"-- Tablo: {table_lower} ({len(rows)} satır)\n")
                
                for row in rows:
                    vals = []
                    for val in row:
                        if val is None:
                            vals.append("NULL")
                        elif isinstance(val, (int, float)):
                            vals.append(str(val))
                        elif isinstance(val, bytes):
                            hex_val = val.hex()
                            vals.append(f"decode('{hex_val}', 'hex')")
                        else:
                            clean_str = str(val).replace("'", "''")
                            vals.append(f"'{clean_str}'")
                    vals_joined = ", ".join(vals)
                    f.write(f"INSERT INTO \"{table_lower}\" ({cols_joined}) VALUES ({vals_joined}) ON CONFLICT DO NOTHING;\n")
                
                # Auto increment sequence düzeltme
                has_id = any(c[1].lower() == 'id' for c in columns_info)
                if has_id:
                    f.write(f"SELECT setval(pg_get_serial_sequence('\"{table_lower}\"', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM \"{table_lower}\";\n")
                f.write("\n")
                
        conn.close()
        print(f"✅ {db_name} başarıyla {output_sql} dosyasına aktarıldı.")

if __name__ == "__main__":
    export_sqlite_to_sql()
