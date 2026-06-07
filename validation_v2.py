import requests
import json

urls = [
    "https://www.siamnews.net/pr-news/sk-hynix-to-establish-u-s-arm-specialized-in-ai-solutions/",
    "https://spoonai.me/posts/2026-05-12-sk-hynix-record-high-1-9m-krw-kiwoom-target-may11-en"
]

results = []
for url in urls:
    try:
        resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        results.append({'url': url, 'status': resp.status_code})
    except Exception as e:
        results.append({'url': url, 'status': 'Error'})

print(json.dumps(results))
