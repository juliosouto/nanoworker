from database import get_db, decrypt_value
import openai
import os

conn = get_db()
c = conn.cursor()
c.execute("SELECT model_name, api_key FROM llm_config WHERE provider = 'qwen' OR provider = 'Qwen'")
rows = c.fetchall()
conn.close()

if not rows:
    print("No qwen models found in llm_config.")
else:
    for r in rows:
        model_name = r['model_name']
        enc_key = r['api_key']
        if not enc_key:
            print(f"No key for {model_name}")
            continue
        api_key = decrypt_value(enc_key)
        print(f"Testing {model_name} with key {api_key[:8]}...")
        
        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "Hello"}]
            )
            print(f"  Success! Response: {response.choices[0].message.content}")
        except Exception as e:
            print(f"  Failed: {e}")
