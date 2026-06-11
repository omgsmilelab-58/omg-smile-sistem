from dotenv import load_dotenv
load_dotenv()
import os
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
            _pg_pool_erp = psycopg2.pool.SimpleConnectionPool(
                1, 20, user=db_user, password=db_pass, host=db_host, port=db_port, database=pg_db_name
            )
        return _pg_pool_erp
    else:
        if _pg_pool_dentflow is None:
            _pg_pool_dentflow = psycopg2.pool.SimpleConnectionPool(
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

    def execute(self, query, parameters=None):
        pg_query = self._convert_query(query)
        if parameters:
            self.cursor.execute(pg_query, parameters)
        else:
            self.cursor.execute(pg_query)
        
        self.rowcount = self.cursor.rowcount
        try:
            # Sadece insert işlemlerinde çalışır
            if "INSERT" in query.upper() and "RETURNING" not in query.upper():
                # PostgreSQL'de lastrowid doğrudan yok, ancak bu yapıda geçici olarak pass geçiyoruz
                self.lastrowid = None
        except:
            pass
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
        self.pool_obj.putconn(self.conn)


def get_connection(db_name="omg_smile_erp.db", check_same_thread=False, timeout=20):
    """
    Bulut modundaysa PostgreSQL bağlantısı (Sarmalanmış halde),
    Yerel moddaysa standart SQLite bağlantısı döner.
    """
    if USE_POSTGRES:
        pool_obj = get_pg_pool(db_name)
        pg_conn = pool_obj.getconn()
        return ConnectionWrapper(pg_conn, pool_obj)
    else:
        # Standart SQLite bağlantısı
        kwargs = {}
        if check_same_thread is not None:
            kwargs['check_same_thread'] = check_same_thread
        if timeout is not None:
            kwargs['timeout'] = timeout
            
        return sqlite3.connect(db_name, **kwargs)
