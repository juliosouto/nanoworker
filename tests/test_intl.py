from database import get_db, decrypt_value
import openai

conn = get_db()
c = conn.cursor()
c.execute("SELECT api_key FROM llm_config WHERE provider = 'qwen' OR provider = 'Qwen' LIMIT 1")
row = c.fetchone()
conn.close()

if row and row['api_key']:
    api_key = decrypt_value(row['api_key'])
    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    for model in ["qwen-plus", "qwen-flash", "qwen3.5-flash"]:
        try:
            print(f"Testing {model}...")
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hello"}]
            )
            print(f"  Success! Response: {response.choices[0].message.content}")
        except Exception as e:
            print(f"  Failed: {e}")
