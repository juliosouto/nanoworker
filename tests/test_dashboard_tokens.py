from app import app
from database import set_config, get_config
import sqlite3

# Limpar db
conn = sqlite3.connect('nanoworker.db')
cursor = conn.cursor()
cursor.execute("DELETE FROM app_config WHERE key LIKE 'TOOL_%'")
conn.commit()
conn.close()

with app.test_client() as client:
    resp1 = client.get('/dashboard')
    content1 = resp1.data.decode()
    
    import re
    match1 = re.search(r'<span>OS Tools:</span>\s*<span[^>]*>(.*?)</span>', content1)
    tokens1 = match1.group(1) if match1 else "Not found"
    print(f"All tools enabled tokens: {tokens1}")
    
    # Disable two tools
    set_config('TOOL_SCHEDULE_TASK', 'false')
    set_config('TOOL_READ_FILE', 'false')
    
    resp2 = client.get('/dashboard')
    content2 = resp2.data.decode()
    match2 = re.search(r'<span>OS Tools:</span>\s*<span[^>]*>(.*?)</span>', content2)
    tokens2 = match2.group(1) if match2 else "Not found"
    print(f"Two tools disabled tokens: {tokens2}")
