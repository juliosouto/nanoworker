import sys
from google import genai
from google.genai import types
from database import get_config

def do_task():
    """Do a task silently."""
    return "Task done."

if __name__ == "__main__":
    api_key = get_config("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    chat = client.chats.create(model="gemini-2.5-flash", config=types.GenerateContentConfig(tools=[do_task], temperature=0.0))
    response = chat.send_message("Please call do_task and then DO NOT say anything else. Just stop.")
    print("TEXT:", response.text)
    if not response.text:
        print("Empty response, which would trigger 'Executed tool calls successfully.'")
