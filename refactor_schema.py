import re

file_path = 'veritabani_kur.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace INTEGER PRIMARY KEY AUTOINCREMENT with SERIAL PRIMARY KEY
content = re.sub(r'INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY', content, flags=re.IGNORECASE)

# In SQLite, "id INTEGER PRIMARY KEY" is automatically autoincrementing. 
# In Postgres, we need SERIAL PRIMARY KEY for autoincrementing primary keys if we don't insert them manually.
# Let's replace "id INTEGER PRIMARY KEY" with "id SERIAL PRIMARY KEY" 
# Be careful not to replace foreign keys or normal integers.
content = re.sub(r'\bid INTEGER PRIMARY KEY\b', 'id SERIAL PRIMARY KEY', content, flags=re.IGNORECASE)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Schema syntax updated successfully.')
