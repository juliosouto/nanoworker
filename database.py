import os
import sqlite3

from cryptography.fernet import Fernet

DB_PATH = 'nanoworker.db'
KEY_PATH = 'encryption.key'

def get_encryption_key() -> bytes:
    """
    Obtém ou gera uma chave de criptografia Fernet.
    Se o arquivo da chave não existir, gera uma nova chave e salva no arquivo.
    
    Retorna:
        bytes: A chave de criptografia.
    """
    if not os.path.exists(KEY_PATH):
        key = Fernet.generate_key()
        with open(KEY_PATH, 'wb') as f:
            f.write(key)
        return key
    else:
        with open(KEY_PATH, 'rb') as f:
            return f.read()

try:
    cipher_suite = Fernet(get_encryption_key())
except Exception as e:
    print(f"Failed to initialize encryption: {e}")
    cipher_suite = None

def is_sensitive_key(key: str) -> bool:
    """
    Verifica se uma determinada chave de configuração contém informações sensíveis.
    As chaves sensíveis incluem substrings como 'API_KEY', 'TOKEN', 'PASSWORD' ou 'SECRET'.
    
    Argumentos:
        key (str): O nome da chave a ser verificada.
        
    Retorna:
        bool: True se for sensível, False caso contrário.
    """
    k = key.upper()
    return 'API_KEY' in k or 'TOKEN' in k or 'PASSWORD' in k or 'SECRET' in k

def encrypt_value(value: str) -> str:
    """
    Criptografa um valor em string usando a chave configurada.
    
    Argumentos:
        value (str): O valor em texto plano.
        
    Retorna:
        str: O valor criptografado, ou o valor original caso a criptografia não esteja inicializada.
    """
    if not value or not cipher_suite:
        return value
    return cipher_suite.encrypt(str(value).encode('utf-8')).decode('utf-8')

def decrypt_value(value: str) -> str:
    """
    Descriptografa um valor previamente criptografado.
    
    Argumentos:
        value (str): O valor criptografado em formato Fernet.
        
    Retorna:
        str: O texto plano resultante da descriptografia, ou o próprio valor de entrada em caso de erro.
    """
    if not value or not cipher_suite:
        return value
    try:
        # Fernet tokens typically start with 'gAAAA'
        if value.startswith('gAAAA'):
            return cipher_suite.decrypt(value.encode('utf-8')).decode('utf-8')
    except Exception:
        pass
    return value

def get_db() -> sqlite3.Connection:
    """
    Estabelece e retorna uma conexão com o banco de dados SQLite.
    
    Retorna:
        sqlite3.Connection: Conexão ativa com o banco.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def get_config(key: str, default=None) -> str:
    """
    Recupera um valor de configuração geral da tabela app_config.
    Descriptografa automaticamente caso a chave seja identificada como sensível.
    
    Argumentos:
        key (str): O nome da configuração.
        default (any, opcional): O valor padrão a retornar se não encontrado.
        
    Retorna:
        str: O valor da configuração (descriptografado se aplicável) ou default.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM app_config WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        val = row['value']
        if is_sensitive_key(key):
            decrypted_val = decrypt_value(val)
            # Migration check: if we retrieved a plain value but it should be encrypted, update DB
            if val == decrypted_val and val and cipher_suite and not val.startswith('gAAAA'):
                set_config(key, val)
            return decrypted_val
        return val
    return default

def get_all_configs() -> dict:
    """
    Retorna todas as configurações da tabela app_config em formato de dicionário.
    Valores de chaves sensíveis são retornados já descriptografados.
    
    Retorna:
        dict: Dicionário contendo todas as chaves e valores.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT key, value FROM app_config')
    rows = cursor.fetchall()
    conn.close()
    result = {}
    for row in rows:
        key = row['key']
        val = row['value']
        if is_sensitive_key(key):
            result[key] = decrypt_value(val)
        else:
            result[key] = val
    return result

def set_config(key: str, value: any):
    """
    Salva ou atualiza uma configuração na tabela app_config.
    Criptografa automaticamente o valor se a chave for identificada como sensível.
    
    Argumentos:
        key (str): O nome da configuração.
        value (any): O valor a ser salvo (será convertido para string).
    """
    conn = get_db()
    cursor = conn.cursor()
    val_to_save = str(value) if value is not None else ""
    if is_sensitive_key(key) and val_to_save:
        val_to_save = encrypt_value(val_to_save)
    cursor.execute('INSERT OR REPLACE INTO app_config (key, value) VALUES (?, ?)', (key, val_to_save))
    conn.commit()
    conn.close()

def get_ide_config(key: str, default=None) -> str:
    """
    Recupera uma configuração específica do ambiente da IDE da tabela ide_settings.
    
    Argumentos:
        key (str): A chave da configuração da IDE.
        default (any, opcional): Valor padrão retornado caso a chave não exista.
        
    Retorna:
        str: O valor correspondente armazenado ou o default.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT value FROM ide_settings WHERE key = ?', (key,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return row['value']
    except sqlite3.OperationalError:
        conn.close()
    return default

def set_ide_config(key: str, value: any):
    """
    Salva ou atualiza uma configuração de ambiente da IDE na tabela ide_settings.
    
    Argumentos:
        key (str): O nome da configuração.
        value (any): O valor a ser armazenado.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR REPLACE INTO ide_settings (key, value) VALUES (?, ?)', (key, str(value) if value is not None else ""))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()

def add_user_memory(instruction: str) -> int:
    """
    Adiciona uma nova instrução à memória do usuário (user_memory).
    
    Argumentos:
        instruction (str): O texto da instrução.
        
    Retorna:
        int: O ID da memória recém-inserida.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO user_memory (instruction) VALUES (?)', (instruction,))
    conn.commit()
    inserted_id = cursor.lastrowid
    conn.close()
    return inserted_id

def get_all_user_memories() -> list:
    """
    Recupera todas as memórias gravadas pelo usuário.
    
    Retorna:
        list: Lista de dicionários contendo os IDs e instruções.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT id, instruction FROM user_memory')
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

def delete_user_memory(memory_id: int) -> bool:
    """
    Remove uma memória de usuário específica pelo seu ID.
    
    Argumentos:
        memory_id (int): O ID da memória a ser removida.
        
    Retorna:
        bool: True se a exclusão foi bem-sucedida, False caso contrário.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM user_memory WHERE id = ?', (memory_id,))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    return success

def update_user_memory(memory_id: int, instruction: str) -> bool:
    """
    Atualiza o texto da instrução de uma memória existente identificada pelo ID.
    
    Argumentos:
        memory_id (int): O ID da memória.
        instruction (str): O novo texto da instrução.
        
    Retorna:
        bool: True se a atualização teve sucesso, False caso contrário.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE user_memory SET instruction = ? WHERE id = ?', (instruction, memory_id))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    return success

def init_db():
    """
    Inicializa o banco de dados SQLite, criando as tabelas necessárias caso
    elas ainda não existam. Também realiza algumas migrações de esquema e 
    de conteúdo (.env, chaves não criptografadas, etc).
    """
    conn = get_db()
    cursor = conn.cursor()

    # App Config Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS app_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    ''')

    # IDE Settings Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ide_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    ''')

    # Migrate .env to app_config if empty
    cursor.execute('SELECT COUNT(*) FROM app_config')
    if cursor.fetchone()[0] == 0:
        try:
            from dotenv import dotenv_values
            env_vars = dotenv_values('.env')
            for k, v in env_vars.items():
                if v is not None:
                    # Encrypt sensitive keys during .env migration
                    val_to_save = str(v)
                    if is_sensitive_key(k) and val_to_save:
                        val_to_save = encrypt_value(val_to_save)
                    cursor.execute('INSERT INTO app_config (key, value) VALUES (?, ?)', (k, val_to_save))
        except Exception as e:
            print(f"Failed to migrate .env: {e}")
    else:
        # Migrate existing unencrypted sensitive keys in DB
        cursor.execute('SELECT key, value FROM app_config')
        for row in cursor.fetchall():
            k = row['key']
            v = row['value']
            if is_sensitive_key(k) and v and cipher_suite and not v.startswith('gAAAA'):
                encrypted_v = encrypt_value(v)
                cursor.execute('UPDATE app_config SET value = ? WHERE key = ?', (encrypted_v, k))

    # Default Agent Name Config
    cursor.execute("SELECT value FROM app_config WHERE key = 'agent_name'")
    row = cursor.fetchone()
    if not row or not row['value']:
        import random
        random_id = str(random.randint(0, 999999)).zfill(6)
        default_name = f"Agent-{random_id}"
        cursor.execute("INSERT OR REPLACE INTO app_config (key, value) VALUES ('agent_name', ?)", (default_name,))

    # LLM Config Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS llm_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_name TEXT NOT NULL,
        provider TEXT NOT NULL,
        api_key TEXT,
        enabled BOOLEAN DEFAULT 1,
        json_output BOOLEAN DEFAULT 0,
        thinking BOOLEAN DEFAULT 0,
        function_calling BOOLEAN DEFAULT 0,
        context_window INTEGER,
        max_output_tokens INTEGER,
        text_input BOOLEAN DEFAULT 1,
        image_input BOOLEAN DEFAULT 0,
        audio_input BOOLEAN DEFAULT 0,
        video_input BOOLEAN DEFAULT 0,
        document_input BOOLEAN DEFAULT 0,
        rate_tpm INTEGER,
        rate_rpm INTEGER,
        rate_rpd INTEGER,
        text_output BOOLEAN DEFAULT 1,
        image_output BOOLEAN DEFAULT 0,
        audio_output BOOLEAN DEFAULT 0,
        video_output BOOLEAN DEFAULT 0,
        document_output BOOLEAN DEFAULT 0
    )
    ''')

    try:
        cursor.execute("ALTER TABLE llm_config ADD COLUMN api_key TEXT")
    except sqlite3.OperationalError:
        pass

    # Agents Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS agents (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Sessions Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        project_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (agent_id) REFERENCES agents(id)
    )
    ''')
    
    # Check if project_path column exists (for existing databases)
    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN project_path TEXT")
    except sqlite3.OperationalError:
        # Column already exists
        pass

    # Cron Jobs Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS cron_jobs (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        description TEXT NOT NULL,
        content TEXT NOT NULL,
        cron_expression TEXT,
        next_run TIMESTAMP NOT NULL,
        is_active BOOLEAN DEFAULT 1,
        execution_count INTEGER DEFAULT 0,
        max_executions INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    ''')

    # Add columns if they don't exist for existing databases
    try:
        cursor.execute("ALTER TABLE cron_jobs ADD COLUMN execution_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            pass
    try:
        cursor.execute("ALTER TABLE cron_jobs ADD COLUMN max_executions INTEGER")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            pass

    # Messages In Table (Inbound DB equivalent)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages_in (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        content TEXT NOT NULL,
        sender_id TEXT,
        image_base64 TEXT,
        file_mime_type TEXT,
        file_name TEXT,
        gemini_file_uri TEXT,
        processed BOOLEAN DEFAULT 0,
        process_after TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        recurrence TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    ''')

    # Add columns if they don't exist for existing databases
    try:
        cursor.execute("ALTER TABLE messages_in ADD COLUMN image_base64 TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            pass
    try:
        cursor.execute("ALTER TABLE messages_in ADD COLUMN file_mime_type TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            pass
    try:
        cursor.execute("ALTER TABLE messages_in ADD COLUMN file_name TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            pass
    try:
        cursor.execute("ALTER TABLE messages_in ADD COLUMN process_after TIMESTAMP")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            pass # Ignore if column already exists
    try:
        cursor.execute("ALTER TABLE messages_in ADD COLUMN recurrence TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            pass
    try:
        cursor.execute("ALTER TABLE messages_in ADD COLUMN gemini_file_uri TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            pass

    # Messages Out Table (Outbound DB equivalent)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages_out (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        in_reply_to TEXT,
        content TEXT NOT NULL,
        delivered BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    ''')

    # IDE Messages In Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ide_messages_in (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        content TEXT NOT NULL,
        sender_id TEXT,
        file_mime_type TEXT,
        file_name TEXT,
        processed BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    ''')

    # IDE Messages Out Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ide_messages_out (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        in_reply_to TEXT,
        content TEXT NOT NULL,
        delivered BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )
    ''')

    try:
        cursor.execute("ALTER TABLE ide_messages_in ADD COLUMN file_mime_type TEXT")
    except sqlite3.OperationalError as e:
        pass
    try:
        cursor.execute("ALTER TABLE ide_messages_in ADD COLUMN file_name TEXT")
    except sqlite3.OperationalError as e:
        pass

    # Seed an initial agent if none exist
    cursor.execute('SELECT COUNT(*) FROM agents')
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO agents (id, name, description) VALUES ('agent-1', 'Default NanoWorker Agent', 'A simple agent for MVP testing')")

    # WhatsApp Config Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS whatsapp_config (
        id INTEGER PRIMARY KEY,
        allowed_from TEXT,
        allowed_to TEXT,
        bot_enabled BOOLEAN DEFAULT 1
    )
    ''')
    cursor.execute('SELECT COUNT(*) FROM whatsapp_config')
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO whatsapp_config (id, allowed_from, allowed_to, bot_enabled) VALUES (1, '', '', 1)")

    try:
        cursor.execute("ALTER TABLE whatsapp_config ADD COLUMN allow_mentions BOOLEAN DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE whatsapp_config ADD COLUMN allow_audio_mentions BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE whatsapp_config ADD COLUMN rate_limit_per_minute INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Rate Limit Usage Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rate_limit_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # User Memory Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        instruction TEXT NOT NULL
    )
    ''')

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
