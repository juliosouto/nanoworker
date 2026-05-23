import sys
from google import genai
from google.genai import types
from database import get_config

api_key = get_config("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

def do_task():
    """Do a task silently."""
    return "Task done."

chat = client.chats.create(model="gemini-2.5-flash", config=types.GenerateContentConfig(tools=[do_task], temperature=0.0))
response = chat.send_message("Please call do_task and then DO NOT say anything else. Just stop.")
print("TEXT:", response.text)
print("HAS AUTO FUNC HISTORY:", hasattr(response, 'automatic_function_calling_history'))
if hasattr(response, 'automatic_function_calling_history') and response.automatic_function_calling_history:
    for h in response.automatic_function_calling_history:
        print("HIST ROLE:", h.role)
        for p in h.parts:
            if p.function_call:
                print("  FUNC CALL:", p.function_call.name)
            elif p.function_response:
                print("  FUNC RESP:", p.function_response.name)
            else:
                print("  TEXT:", p.text)
