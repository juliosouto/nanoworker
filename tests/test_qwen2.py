from database import get_config
import openai

qwen_key = get_config("QWEN_API_KEY")
print(f"Key exists: {bool(qwen_key)}")

if qwen_key:
    client = openai.OpenAI(
        api_key=qwen_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    for model in ["qwen-plus", "qwen-flash", "qwen3.5-flash", "qwen-turbo"]:
        try:
            print(f"Testing {model}...")
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hello"}]
            )
            print(f"Success for {model}: {response.choices[0].message.content}")
        except Exception as e:
            print(f"Failed for {model}: {e}")

