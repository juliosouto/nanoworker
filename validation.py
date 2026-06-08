import requests
import json

urls = [
    "https://news.skhynix.com/",
    "https://www.linkedin.com/pulse/samsung-sk-hynix-push-70-dram-price-hikes-what-im-nantha-kumar-l-xxehc",
    "https://sudonull.com/samsung-and-sk-hynix-started-mass-production-of-hbm4-for-nvidia-ai-accelerators",
    "https://www.notebookcheck.net/SK-hynix-sells-out-its-DRAM-NAND-and-HBM-chip-supply-to-Nvidia-through-2026-as-AI-demand-outpaces-Samsung-and-Micron-s-capacity.1151402.0.html",
    "https://enkiai.com/data-center/hbm-supply-crisis-2026-the-bottleneck-redefining-ai/"
]

results = []
for url in urls:
    try:
        resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        results.append({'url': url, 'status': resp.status_code})
    except Exception as e:
        results.append({'url': url, 'status': 'Error'})

print(json.dumps(results))
