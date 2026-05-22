import sys
from google import genai
from google.genai import types
from database import get_config

api_key = get_config("GEMINI_API_KEY")
if not api_key:
    print("NO API KEY")
    sys.exit(1)

client = genai.Client(api_key=api_key)
def my_tool():
    """Returns a magic word."""
    return "abracadabra"

chat = client.chats.create(model="gemini-2.5-flash", config=types.GenerateContentConfig(tools=[my_tool], temperature=0.0))
response = chat.send_message("Please use my_tool and tell me the magic word.")
print("TEXT:", response.text)
if response.candidates:
    print("PARTS:", response.candidates[0].content.parts)
