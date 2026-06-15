import requests
import json

def search_wikimedia_images(query: str, limit: int = 5) -> str:
    """
    Pesquisa por imagens no Wikimedia Commons usando a MediaWiki API.
    Use essa tool quando precisar encontrar URLs de imagens sobre algum assunto.
    
    Args:
        query: O termo de busca (ex: 'dog', 'Eiffel Tower').
        limit: O número máximo de imagens a retornar (padrão 5, máximo 50).
        
    Returns:
        str: Uma string JSON contendo uma lista de URLs de imagens e seus títulos, ou uma mensagem de erro.
    """
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,  # 6 is the File namespace on MediaWiki
        "prop": "imageinfo",
        "iiprop": "url",
        "gsrlimit": min(limit, 50)
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return f"Nenhuma imagem encontrada para a busca: '{query}'"
            
        results = []
        for page_id, page_info in pages.items():
            title = page_info.get("title", "").replace("File:", "")
            imageinfo = page_info.get("imageinfo", [])
            if imageinfo:
                img_url = imageinfo[0].get("url", "")
                if img_url:
                    results.append({
                        "title": title,
                        "url": img_url
                    })
                    
        return json.dumps(results, indent=2, ensure_ascii=False)
        
    except Exception as e:
        return f"Erro ao pesquisar no Wikimedia Commons: {str(e)}"
