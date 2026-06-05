import os

def fix_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    
    new_content = content.replace("config.get('allow_mentions')", "config['allow_mentions']")
    
    with open(filepath, 'w') as f:
        f.write(new_content)

fix_file('tools/windows/whatsapp.py')
fix_file('tools/macos/whatsapp.py')
fix_file('tools/linux/whatsapp.py')
print("Fixed config error.")
