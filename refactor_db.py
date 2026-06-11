import re
import os

files_to_process = ['ana_program.py', 'veritabani_kur.py']

for file_path in files_to_process:
    if not os.path.exists(file_path):
        continue
        
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add imports
    if 'import db_baglanti' not in content:
        content = content.replace('import sqlite3', 'import sqlite3\nimport db_baglanti\nimport storage_utils')

    # Replace sqlite3.connect
    content = re.sub(r'sqlite3\.connect\((.*?)\)', r'db_baglanti.get_connection(\1)', content)

    # Comment out PRAGMA journal_mode=WAL
    content = re.sub(r'(conn\.execute\([\'"]PRAGMA journal_mode=WAL;[\'"]\))', r'# \1', content)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
        
print('Database connections updated successfully.')
