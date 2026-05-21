import os
import shutil

ICLOUD_DRIVE_PATH = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs")

def _get_absolute_icloud_path(path_relative: str) -> str:
    """Helper to resolve a relative path to the absolute iCloud Drive path, ensuring it stays within iCloud."""
    if not os.path.exists(ICLOUD_DRIVE_PATH):
        raise Exception(f"iCloud Drive folder not found at: {ICLOUD_DRIVE_PATH}")
    
    # Strip leading slashes to prevent absolute path evaluation by os.path.join
    path_relative = path_relative.lstrip("/")
    abs_path = os.path.abspath(os.path.join(ICLOUD_DRIVE_PATH, path_relative))
    
    # Ensure it doesn't break out of iCloud Drive
    if not abs_path.startswith(ICLOUD_DRIVE_PATH):
        raise ValueError("Access to paths outside of iCloud Drive is restricted.")
    
    return abs_path

def list_icloud_files(path_relative: str = "") -> list:
    """
    Lista arquivos e diretórios dentro de uma pasta no iCloud Drive.
    
    Args:
        path_relative: Caminho relativo da pasta (ex: 'Documentos' ou ''). 
                       Vazio para a raiz do iCloud Drive.
    """
    target_path = _get_absolute_icloud_path(path_relative)
    
    if not os.path.isdir(target_path):
        raise NotADirectoryError(f"O caminho não é um diretório ou não existe: {target_path}")
        
    try:
        items = []
        for item in os.listdir(target_path):
            item_path = os.path.join(target_path, item)
            items.append({
                "name": item,
                "is_dir": os.path.isdir(item_path),
                "size": os.path.getsize(item_path) if os.path.isfile(item_path) else None
            })
        return items
    except PermissionError as e:
        raise PermissionError(f"Permissão negada ao acessar {target_path}. Verifique se o processo tem Full Disk Access.") from e

def read_icloud_file(file_path_relative: str) -> str:
    """
    Lê o conteúdo de um arquivo de texto no iCloud Drive.
    
    Args:
        file_path_relative: Caminho do arquivo relativo à raiz do iCloud Drive (ex: 'Notas/texto.txt').
    """
    target_path = _get_absolute_icloud_path(file_path_relative)
    
    if not os.path.isfile(target_path):
        raise FileNotFoundError(f"Arquivo não encontrado: {target_path}")
        
    try:
        with open(target_path, 'r', encoding='utf-8') as f:
            return f.read()
    except PermissionError as e:
        raise PermissionError(f"Permissão negada ao ler {target_path}. Verifique as permissões do macOS.") from e
    except UnicodeDecodeError as e:
        raise ValueError(f"O arquivo parece ser binário ou não está codificado em UTF-8: {target_path}") from e

def write_icloud_file(file_path_relative: str, content: str) -> str:
    """
    Escreve conteúdo (texto) em um arquivo no iCloud Drive. 
    Se a pasta pai não existir, ela será criada.
    
    Args:
        file_path_relative: Caminho relativo do arquivo (ex: 'Notas/novo_texto.txt').
        content: O conteúdo de texto a ser escrito no arquivo.
    """
    target_path = _get_absolute_icloud_path(file_path_relative)
    parent_dir = os.path.dirname(target_path)
    
    try:
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
            
        with open(target_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Arquivo salvo com sucesso em: {target_path}"
    except PermissionError as e:
        raise PermissionError(f"Permissão negada ao escrever em {target_path}. Verifique as permissões do macOS.") from e
