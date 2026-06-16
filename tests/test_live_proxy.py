import requests
from utils.proxy_manager import enable_proxy, disable_proxy

proxy = enable_proxy()
print(f"Got proxy: {proxy}")

print("\n--- Testing api.ipify.org ---")
try:
    res = requests.get('https://api.ipify.org', timeout=10)
    print("Status:", res.status_code)
    print("Text:", res.text)
except Exception as e:
    print("Failed to get IP:", e)

print("\n--- Testing Wikimedia ---")
try:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    url = "https://en.wikipedia.org/w/api.php?action=query&format=json&prop=pageimages&generator=search&gsrsearch=dog&gsrlimit=1&pithumbsize=500"
    res = requests.get(url, headers=headers, timeout=10)
    print("Status:", res.status_code)
    try:
        print("JSON:", res.json())
    except Exception as je:
        print("Failed to decode JSON:", je)
        print("Text snippet:", res.text[:200])
except Exception as e:
    print("Failed Wikimedia:", e)

disable_proxy()
