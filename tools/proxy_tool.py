from utils.proxy_manager import enable_proxy, disable_proxy, status_proxy

def manage_proxy(action: str) -> str:
    """
    Gerencia o interceptador de Proxy Global que afeta todas as requisições HTTP feitas pelo agente.
    Use isso para contornar bloqueios de IP, rate limits em APIs ou web scraping.
    
    Args:
        action (str): A ação desejada. Aceita:
            - 'enable': Busca um novo proxy gratuito, habilita e retorna o IP.
            - 'disable': Desliga o proxy e volta a usar a conexão direta do servidor.
            - 'status': Verifica qual é o proxy atualmente em uso.
            
    Returns:
        str: O resultado da operação com informações do proxy atual.
    """
    action = action.lower().strip()
    
    if action == 'enable':
        proxy = enable_proxy()
        if proxy:
            return f"Proxy habilitado com sucesso. Todas as requisições futuras usarão: {proxy}"
        else:
            return "Falha ao buscar e habilitar um proxy gratuito disponível no momento."
            
    elif action == 'disable':
        disable_proxy()
        return "Proxy desabilitado. Requisições agora usarão a rede direta."
        
    elif action == 'status':
        status = status_proxy()
        return f"Status do Proxy Global: {status}"
        
    else:
        return f"Ação desconhecida: '{action}'. Ações suportadas: 'enable', 'disable', 'status'."
