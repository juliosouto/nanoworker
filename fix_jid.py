import os

def fix_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # We need to replace the flawed logic blocks with the correct one.
    import re
    
    # We will look for: jid = phone_number.strip().replace("wa_web:", "")
    # and replace the whole block up to payload["jid"] = jid or audio_payload["jid"] = jid
    
    pattern1 = r'jid = phone_number\.strip\(\)\.replace\("wa_web:", ""\)\n\s*if "@" not in jid:\n\s*if "-" in jid or jid\.startswith\("120363"\):\n\s*jid = f"\{jid\}@g\.us"\n\s*else:\n\s*jid = jid\.replace\("\+", ""\)\.replace\(" ", ""\)\.replace\("-", ""\)\n\s*jid = f"\{jid\}@s\.whatsapp\.net"\n\s*(payload\["jid"\] = jid|audio_payload\["jid"\] = jid)'

    pattern2 = r'jid = phone_number\.strip\(\)\.replace\("\+", ""\)\.replace\(" ", ""\)\n\s*if "@" not in jid:\n\s*jid = jid\.replace\("-", ""\)\n\s*jid = f"\{jid\}@s\.whatsapp\.net"\n\s*(payload\["jid"\] = jid|audio_payload\["jid"\] = jid)'

    replacement = """jid = phone_number.strip().replace("wa_web:", "")
            if "@" not in jid:
                parts = jid.split("-")
                if jid.startswith("120363") or (len(parts) == 2 and parts[1].isdigit() and len(parts[1]) >= 8):
                    jid = jid.replace("+", "").replace(" ", "")
                    jid = f"{jid}@g.us"
                else:
                    jid = jid.replace("+", "").replace(" ", "").replace("-", "")
                    jid = f"{jid}@s.whatsapp.net"
            else:
                jid = jid.replace("+", "").replace(" ", "")
            \\1"""

    new_content = re.sub(pattern1, replacement, content)
    new_content = re.sub(pattern2, replacement, new_content)
    
    with open(filepath, 'w') as f:
        f.write(new_content)

fix_file('tools/windows/whatsapp.py')
fix_file('tools/macos/whatsapp.py')
fix_file('tools/linux/whatsapp.py')
print("Fixed files.")
