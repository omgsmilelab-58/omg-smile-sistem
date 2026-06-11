import re

file_path = 'ana_program.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Regular expression to match the very uniform file write pattern:
# with open(VAR_PATH, "wb") as f: f.write(VAR_FILE.getbuffer())
# Group 1: Leading whitespace
# Group 2: Path variable name
# Group 3: File variable name

pattern = r'(\s*)with open\(([^,]+), ["\']wb["\']\) as f:\s*f\.write\(([^.]+)\.getbuffer\(\)\)'

def replacer(match):
    indent = match.group(1)
    path_var = match.group(2).strip()
    file_var = match.group(3).strip()
    
    # We replace it with the storage_utils call.
    # Note: os is imported.
    replacement = f"{indent}{path_var} = storage_utils.dosya_kaydet(os.path.dirname({path_var}), os.path.basename({path_var}), {file_var})"
    return replacement

new_content = re.sub(pattern, replacer, content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print('Storage logic updated successfully.')
