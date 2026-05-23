import openai
from dotenv import load_dotenv
import os
import sqlite3

load_dotenv(override=True)

conn = sqlite3.connect('nanoworker.db')
cursor = conn.cursor()
cursor.execute("SELECT api_key FROM llm_config WHERE model_name='qwen-flash'")
row = cursor.fetchone()
qwen_key = row[0] if row else None
print(f"Key exists: {qwen_key}")

if qwen_key:
    client = openai.OpenAI(
        api_key=qwen_key,
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    for model in ["qwen-turbo"]:
        try:
            print(f"Testing {model}...")
            response = client.chat.completions.create(
                model=f'qwen/{model}',
                messages=[{"role": "user", "content": "Hello"}]
            )
            print(f"Success for {model}: {response.choices[0].message.content}")
        except Exception as e:
            print(f"Failed for {model}: {e}")

