import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.macos.whatsapp import send_whatsapp_file

file_path = os.path.abspath("temp/mp3/test.mp3")
group_id = "5519991732206-1423590162@g.us"

print(f"Sending {file_path} to {group_id}...")
result = send_whatsapp_file(group_id, file_path)
print(f"Result: {result}")
