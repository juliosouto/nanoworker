from database import get_db, decrypt_value
conn = get_db()
c = conn.cursor()
c.execute("SELECT id, model_name, api_key FROM llm_config WHERE provider = 'qwen' OR provider = 'Qwen'")
rows = c.fetchall()
conn.close()

for r in rows:
    enc = r['api_key']
    dec = decrypt_value(enc) if enc else 'None'
    print(f"ID {r['id']}, Model {r['model_name']}, Key: {dec[:8]}...")
