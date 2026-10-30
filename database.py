import json
import logging
import os
import sqlite3

from cryptography.fernet import Fernet

DB_PATH = 'nanoworker.db'
KEY_PATH = '.store/encryption.key'
OLD_KEY_PATH = 'encryption.key'

def get_encryption_key() -> bytes:
    """
    Obtém ou gera uma chave de criptografia Fernet.
    Se o arquivo da chave não existir, gera uma nova chave e salva no arquivo.
    
    Retorna:
        bytes: A chave de criptografia.
    """
    # Migrate old key if it exists
    if os.path.exists(OLD_KEY_PATH) and not os.path.exists(KEY_PATH):
        os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
        os.rename(OLD_KEY_PATH, KEY_PATH)

    if not os.path.exists(KEY_PATH):
        os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
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

# ---------------------------------------------------------------------------
# sqlite-vec (vector search extension)
#
# Availability is probed once per process: -1 = not probed yet, 0 = unusable
# (package missing, wheel mismatch, or a Python build without
# enable_load_extension), 1 = working. The extension is per-connection, so it
# must be loaded again on every new connection. Any failure degrades
# gracefully: the app keeps working, only the vector table
# (message_history_vec) becomes unavailable.
# ---------------------------------------------------------------------------
_SQLITE_VEC_STATE = -1


def _load_sqlite_vec(conn) -> bool:
    """Carrega a extensão sqlite-vec na conexão. Retorna True quando disponível."""
    global _SQLITE_VEC_STATE
    if _SQLITE_VEC_STATE == 0:
        return False
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _SQLITE_VEC_STATE = 1
        return True
    except Exception:
        if _SQLITE_VEC_STATE != 1:
            _SQLITE_VEC_STATE = 0
        return False


def sqlite_vec_available() -> bool:
    """True quando a extensão sqlite-vec pode ser carregada neste ambiente."""
    global _SQLITE_VEC_STATE
    if _SQLITE_VEC_STATE == -1:
        probe = sqlite3.connect(':memory:')
        try:
            _SQLITE_VEC_STATE = 1 if _load_sqlite_vec(probe) else 0
        except Exception:
            _SQLITE_VEC_STATE = 0
        finally:
            probe.close()
    return _SQLITE_VEC_STATE == 1


def get_db() -> sqlite3.Connection:
    """
    Estabelece e retorna uma conexão com o banco de dados SQLite.

    Quando a extensão sqlite-vec está disponível ela é carregada na conexão,
    habilitando as tabelas virtuais de busca vetorial (message_history_vec).

    Retorna:
        sqlite3.Connection: Conexão ativa com o banco.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    _load_sqlite_vec(conn)
    return conn

def get_config(key: str, default=None) -> str|None:
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

def get_all_workers_with_capabilities() -> list:
    """
    Retorna uma lista de todos os workers e as capacidades de seus respectivos modelos (input e output).
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT w.worker_name, w.worker_model, 
                   MAX(l.text_input) as text_input, MAX(l.image_input) as image_input, 
                   MAX(l.audio_input) as audio_input, MAX(l.video_input) as video_input, MAX(l.document_input) as document_input,
                   MAX(l.text_output) as text_output, MAX(l.image_output) as image_output, 
                   MAX(l.audio_output) as audio_output, MAX(l.video_output) as video_output, MAX(l.document_output) as document_output
            FROM workers_config w
            LEFT JOIN llm_config l ON w.worker_model = l.model_name
            GROUP BY w.id
        ''')
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

def get_tool_enabled(tool_name: str) -> bool:
    """
    Returns whether a tool is enabled or not based on tools_config.
    Defaults to True.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT enabled FROM tools_config WHERE tool_name = ?', (tool_name.lower(),))
        row = cursor.fetchone()
        conn.close()
        if row is not None:
            return bool(row['enabled'])
    except sqlite3.OperationalError:
        conn.close()
    return True

def get_tool_config(tool_name: str) -> dict:
    """
    Returns the full configuration for a tool from tools_config.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT enabled, allow_others_from_direct_msgs, allow_others_from_group_msgs, config_data FROM tools_config WHERE tool_name = ?', (tool_name.lower(),))
        row = cursor.fetchone()
        conn.close()
        if row is not None:
            settings = {}
            try:
                raw = row['config_data']
                if raw:
                    settings = json.loads(raw)
                    if not isinstance(settings, dict):
                        settings = {}
            except (ValueError, TypeError, KeyError):
                settings = {}
            return {
                'enabled': bool(row['enabled']),
                'allow_others_from_direct_msgs': bool(row['allow_others_from_direct_msgs']),
                'allow_others_from_group_msgs': bool(row['allow_others_from_group_msgs']),
                'settings': settings
            }
    except sqlite3.OperationalError:
        conn.close()

    return {
        'enabled': True,
        'allow_others_from_direct_msgs': False,
        'allow_others_from_group_msgs': False,
        'settings': {}
    }

def update_tool_config(tool_name: str, updates: dict):
    """
    Updates one or more configuration fields for a tool.
    """
    if not updates:
        return

    conn = get_db()
    cursor = conn.cursor()
    try:
        tool_name_lower = tool_name.lower()
        cursor.execute('SELECT COUNT(*) FROM tools_config WHERE tool_name = ?', (tool_name_lower,))
        exists = cursor.fetchone()[0] > 0

        if not exists:
            cursor.execute('INSERT INTO tools_config (tool_name) VALUES (?)', (tool_name_lower,))

        set_clauses = []
        values = []
        for key, value in updates.items():
            if key == 'config_data':
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                set_clauses.append("config_data = ?")
                values.append(value)
            elif key in ['enabled', 'allow_others_from_direct_msgs', 'allow_others_from_group_msgs']:
                set_clauses.append(f"{key} = ?")
                values.append(value)

        if set_clauses:
            values.append(tool_name_lower)
            query = f"UPDATE tools_config SET {', '.join(set_clauses)} WHERE tool_name = ?"
            cursor.execute(query, tuple(values))

        conn.commit()
    finally:
        conn.close()



def init_db():
    """
    Inicializa o banco de dados SQLite, criando as tabelas necessárias caso
    elas ainda não existam. Também realiza algumas migrações de esquema e 
    de conteúdo (.env, chaves não criptografadas, etc).
    """
    conn = get_db()
    cursor = conn.cursor()

    # WAL: readers never block the writer and vice versa, so concurrent
    # agents do not wait on each other's reads. The mode is stored in the
    # database file, so setting it once here covers every connection.
    try:
        cursor.execute('PRAGMA journal_mode=WAL')
    except sqlite3.OperationalError as exc:
        logging.warning(f"Could not enable SQLite WAL mode: {exc}")

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

    # Default Use Recipes as Tools Config
    cursor.execute("SELECT value FROM app_config WHERE key = 'USE_RECIPES_AS_TOOLS'")
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT OR REPLACE INTO app_config (key, value) VALUES ('USE_RECIPES_AS_TOOLS', 'true')")

    # Default Plan Before Execution Config
    cursor.execute("SELECT value FROM app_config WHERE key = 'PLAN_BEFORE_EXECUTION'")
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT OR REPLACE INTO app_config (key, value) VALUES ('PLAN_BEFORE_EXECUTION', 'false')")

    # Default Autonomous Mode Config
    cursor.execute("SELECT value FROM app_config WHERE key = 'AUTONOMOUS_MODE'")
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT OR REPLACE INTO app_config (key, value) VALUES ('AUTONOMOUS_MODE', '1')")

    # Default LangChain integration flags (agent.lc)
    cursor.execute("SELECT value FROM app_config WHERE key = 'LLM_STACK'")
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT OR REPLACE INTO app_config (key, value) VALUES ('LLM_STACK', 'langchain')")

    cursor.execute("SELECT value FROM app_config WHERE key = 'LC_TOKEN_COUNTER'")
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT OR REPLACE INTO app_config (key, value) VALUES ('LC_TOKEN_COUNTER', 'tiktoken')")

    cursor.execute("SELECT value FROM app_config WHERE key = 'LC_STRUCTURED_OUTPUT'")
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT OR REPLACE INTO app_config (key, value) VALUES ('LC_STRUCTURED_OUTPUT', 'auto')")

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

    # Session summary cache for the phase-3 progressive summarization.
    # Idempotent: if the column already exists, the ALTER raises OperationalError
    # and the column is left untouched.
    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN summary TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN summary_until TEXT")
    except sqlite3.OperationalError:
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
        client_message_id TEXT,
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
    try:
        cursor.execute("ALTER TABLE messages_in ADD COLUMN client_message_id TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            pass
    try:
        cursor.execute("ALTER TABLE messages_in ADD COLUMN sender_name TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            pass
    try:
        cursor.execute("ALTER TABLE messages_in ADD COLUMN sender_id_alt TEXT")
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

    # Message History Table: canonical timeline of TEXT messages per channel.
    # Group messages that never mention the worker are recorded here too (they
    # used to be discarded in the Baileys worker). Media is never saved — text
    # only. The date/hour/minute/second columns are derived from the original
    # WhatsApp epoch (msg_timestamp) at insert time.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS message_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT UNIQUE,
        channel_id TEXT NOT NULL,
        remote_jid TEXT,
        is_group BOOLEAN DEFAULT 0,
        sender_id TEXT,
        sender_id_alt TEXT,
        sender_name TEXT,
        from_me BOOLEAN DEFAULT 0,
        is_bot BOOLEAN DEFAULT 0,
        content TEXT NOT NULL,
        msg_timestamp INTEGER,
        msg_date TEXT,
        msg_hour INTEGER,
        msg_minute INTEGER,
        msg_second INTEGER,
        was_processed BOOLEAN DEFAULT 0,
        worker_mentioned BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_msg_history_channel_ts
        ON message_history (channel_id, msg_timestamp DESC)
    ''')

    # Migration guard for databases that already ran the pre-is_bot build:
    # from_me covers BOTH the human owner (typing on their own phone) and bot
    # replies, so the LLM role mapping needs the explicit is_bot flag.
    try:
        cursor.execute("ALTER TABLE message_history ADD COLUMN is_bot BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Vector index over the message history (sqlite-vec):
    #   id         -> message_history.id (FK semantics)
    #   channel_id -> partition key: KNN is scoped per chat (privacy)
    #   +payload   -> auxiliary JSON snapshot (render without JOIN)
    #   vector     -> embedding, cosine distance; dims follow the active
    #                 embeddings provider (gemini=768, openai=1536).
    # The previous (never-populated) schema is dropped on upgrade.
    if sqlite_vec_available():
        try:
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='message_history_vec'")
            existing = cursor.fetchone()
            existing_sql = existing['sql'] if existing else None
            needs_rebuild = False
            if existing_sql is not None:
                if 'partition key' not in existing_sql:
                    needs_rebuild = True  # legacy (pre-RAG) schema
                else:
                    # Provider switch (dims change) leaves the old table
                    # permanently rejecting inserts/KNN: drop and let the boot
                    # backfill re-embed from message_history.
                    stored_dims = _vec_table_dims_from_sql(existing_sql)
                    if stored_dims is not None and stored_dims != get_history_vec_dims():
                        needs_rebuild = True
            if needs_rebuild:
                logging.getLogger(__name__).info(
                    "message_history_vec schema/dims changed; dropping and recreating. "
                    "Existing vectors are dropped — the boot backfill re-embeds them."
                )
                cursor.execute('DROP TABLE message_history_vec')
                existing_sql = None
            if existing_sql is None:
                cursor.execute(f'''
                CREATE VIRTUAL TABLE message_history_vec USING vec0(
                    id INTEGER PRIMARY KEY,
                    channel_id TEXT partition key,
                    +payload TEXT,
                    vector float[{get_history_vec_dims()}] distance_metric=cosine
                )
                ''')
        except sqlite3.OperationalError:
            pass

    # BM25 keyword index over the message history (FTS5, always available in
    # standard SQLite builds). rowid mirrors message_history.id and channel_id
    # is stored UNINDEXED so every keyword query (and cleanup) is scoped to a
    # single chat. The backfill is idempotent: pre-existing rows (stored before
    # this index existed) are indexed on the first boot.
    try:
        cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS message_history_fts USING fts5(
            content,
            channel_id UNINDEXED,
            tokenize='porter unicode61'
        )
        ''')
        cursor.execute('''
        INSERT INTO message_history_fts(rowid, content, channel_id)
            SELECT id, content, channel_id FROM message_history
            WHERE id NOT IN (SELECT rowid FROM message_history_fts)
        ''')
    except sqlite3.OperationalError:
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
        # DEFAULT 1 preserves the legacy behavior (inbound audios were processed without an
        # opt-in gate before this column existed). DEFAULT 0 silently disabled received audios
        # on existing installs after a deploy that applied this migration.
        cursor.execute("ALTER TABLE whatsapp_config ADD COLUMN allow_audio_mentions BOOLEAN DEFAULT 1")
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

    # Extracted Documents Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS extracted_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_hash TEXT NOT NULL,
        file_name TEXT NOT NULL,
        category TEXT,
        extracted_data TEXT,
        metadata TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Workers Config Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS workers_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_name TEXT NOT NULL,
        worker_model TEXT NOT NULL,
        worker_instructions TEXT,
        is_default BOOLEAN DEFAULT 0,
        thinking_enabled BOOLEAN DEFAULT 0,
        tools_enabled BOOLEAN DEFAULT 1,
        show_tools_results BOOLEAN DEFAULT 1,
        temperature REAL
    )
    ''')

    try:
        cursor.execute("ALTER TABLE workers_config ADD COLUMN thinking_enabled BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        cursor.execute("ALTER TABLE workers_config ADD COLUMN tools_enabled BOOLEAN DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        cursor.execute("ALTER TABLE workers_config ADD COLUMN show_tools_results BOOLEAN DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        cursor.execute("ALTER TABLE workers_config ADD COLUMN temperature REAL")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Tools Config Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tools_config (
        tool_name TEXT PRIMARY KEY,
        private_key TEXT,
        config_data TEXT,
        enabled BOOLEAN DEFAULT 1,
        allow_others_from_direct_msgs BOOLEAN DEFAULT 0,
        allow_others_from_group_msgs BOOLEAN DEFAULT 0
    )
    ''')

    try:
        cursor.execute("ALTER TABLE tools_config ADD COLUMN enabled BOOLEAN DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        cursor.execute("ALTER TABLE tools_config ADD COLUMN allow_others_from_direct_msgs BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE tools_config ADD COLUMN allow_others_from_group_msgs BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Per-tool custom settings (JSON). Present in CREATE TABLE above; the
    # ALTER keeps databases created by older builds working.
    try:
        cursor.execute("ALTER TABLE tools_config ADD COLUMN config_data TEXT")
    except sqlite3.OperationalError:
        pass

    # Migrate tool configurations from app_config to tools_config
    cursor.execute("SELECT key, value FROM app_config WHERE key LIKE 'TOOL_%'")
    tools_app_configs = cursor.fetchall()
    for row in tools_app_configs:
        key = row['key']
        # Convert the value string to boolean
        val_bool = 1 if str(row['value']).lower() == 'true' else 0
        tool_name = key[5:].lower()  # strip 'TOOL_' and lower it
        
        # Insert or update in tools_config
        cursor.execute('SELECT COUNT(*) FROM tools_config WHERE tool_name = ?', (tool_name,))
        if cursor.fetchone()[0] > 0:
            cursor.execute('UPDATE tools_config SET enabled = ? WHERE tool_name = ?', (val_bool, tool_name))
        else:
            cursor.execute('INSERT INTO tools_config (tool_name, enabled) VALUES (?, ?)', (tool_name, val_bool))
            
        # Delete old key from app_config
        cursor.execute('DELETE FROM app_config WHERE key = ?', (key,))

    # LLM Usage Table (Fase 6): token accounting per agent turn, collected from
    # usage_metadata (LangChain runner) and the native usage fields of the
    # legacy provider loops. The `stack` column ('legacy' | 'langchain') powers
    # the before/after comparison shown on the dashboard.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS llm_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        message_in_id TEXT,
        stack TEXT NOT NULL DEFAULT 'legacy',
        model TEXT,
        input_tokens INTEGER,
        output_tokens INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage (created_at)
    ''')
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_llm_usage_stack_created ON llm_usage (stack, created_at)
    ''')

    conn.commit()
    conn.close()


def clear_session_summary(session_id: str) -> None:
    """Clears the progressive summarization cache for a session (e.g. after
    '/new' resets messages_in/messages_out) so a stale summary cannot leak
    into a fresh conversation.
    """
    from database import get_db
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'UPDATE sessions SET summary = NULL, summary_until = NULL WHERE id = ?',
            (session_id,),
        )
        conn.commit()
    except sqlite3.OperationalError:
        # Column does not exist on very old databases: nothing to clear.
        pass
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Message history (message_history / message_history_vec)
# ---------------------------------------------------------------------------

def get_message_history_size(default: int = 10000) -> int:
    """Número de mensagens mantidas por canal (campo History Size, Agent
    Behavior). 0 = não manter histórico (linhas e vetores são apagados)."""
    try:
        n = int(get_config("MESSAGE_HISTORY_SIZE", str(default)))
    except (TypeError, ValueError):
        n = default
    return max(0, n)


def get_prompt_history_size(default: int = 20) -> int:
    """Número de mensagens do canal enviadas verbatim ao LLM (PROMPT_HISTORY_SIZE).

    É a janela de continuidade do prompt. Independe da retenção do banco
    (MESSAGE_HISTORY_SIZE), que continua guardando o histórico cru e vetorizado.
    O History RAG busca apenas o que ficou fora desta janela.
    """
    try:
        n = int(get_config("PROMPT_HISTORY_SIZE", str(default)))
    except (TypeError, ValueError):
        n = default
    return max(0, n)


def insert_message_history(message_id=None, channel_id=None, remote_jid=None,
                           is_group=0, sender_id=None, sender_id_alt=None,
                           sender_name=None, from_me=0, is_bot=0, content='',
                           msg_timestamp=None, was_processed=0,
                           worker_mentioned=0):
    """
    Grava uma mensagem de TEXTO na linha do tempo do canal.

    - Deduplica reentregas via message_id UNIQUE (message key do WhatsApp).
    - Deriva data/hora/minuto/segundo do epoch original do WhatsApp
      (msg_timestamp); sem epoch, usa o horário atual do servidor.
    - Apara o canal para manter apenas as MESSAGE_HISTORY_SIZE mensagens
      mais recentes (também limpa as linhas vetoriais órfãs).

    Retorna:
        int: O id da nova linha, ou None quando o insert foi ignorado
        (message_id duplicado) ou a linha é inválida (sem canal/conteúdo).
    """
    if not channel_id or content is None or not str(content).strip():
        return None

    ts = None
    if msg_timestamp is not None:
        try:
            ts = int(msg_timestamp)
        except (TypeError, ValueError):
            ts = None
    from datetime import datetime
    dt = datetime.fromtimestamp(ts) if ts else datetime.now()

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO message_history
                (message_id, channel_id, remote_jid, is_group, sender_id,
                 sender_id_alt, sender_name, from_me, is_bot, content,
                 msg_timestamp, msg_date, msg_hour, msg_minute, msg_second,
                 was_processed, worker_mentioned)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            message_id, channel_id, remote_jid,
            1 if is_group else 0,
            sender_id, sender_id_alt, sender_name,
            1 if from_me else 0,
            1 if is_bot else 0,
            str(content), ts,
            dt.strftime('%Y-%m-%d'),
            dt.hour, dt.minute, dt.second,
            1 if was_processed else 0,
            1 if worker_mentioned else 0,
        ))
        if cursor.rowcount == 0:
            return None  # duplicate message_id -> ignored
        row_id = cursor.lastrowid
        try:
            cursor.execute('''
                INSERT INTO message_history_fts(rowid, content, channel_id)
                VALUES (?, ?, ?)
            ''', (row_id, str(content), channel_id))
        except sqlite3.OperationalError:
            pass  # FTS unavailable: keyword leg degrades, history is kept
        _trim_message_history_cursor(cursor, channel_id)
        conn.commit()
        return row_id
    finally:
        conn.close()


def _trim_message_history_cursor(cursor, channel_id) -> int:
    """Mantém apenas as MESSAGE_HISTORY_SIZE linhas mais recentes do canal e
    remove as linhas vetoriais órfãs (escopadas por canal). Usa o cursor/txn do
    chamador.

    Early-exit: quando o canal está dentro do limite nenhum DELETE roda — o
    trim é executado a cada mensagem inserida, então o custo precisa ser
    proporcional só ao canal que cresceu.
    """
    keep_n = get_message_history_size()
    try:
        cursor.execute(
            'SELECT COUNT(*) FROM message_history WHERE channel_id = ?',
            (channel_id,),
        )
        if cursor.fetchone()[0] <= keep_n:
            return 0
    except sqlite3.OperationalError:
        pass  # table missing: nothing to trim

    cursor.execute('''
        DELETE FROM message_history
        WHERE channel_id = ?
          AND id NOT IN (
              SELECT id FROM message_history
              WHERE channel_id = ?
              ORDER BY msg_timestamp DESC, id DESC
              LIMIT ?
          )
    ''', (channel_id, channel_id, keep_n))
    deleted = cursor.rowcount
    if deleted > 0 and sqlite_vec_available():
        try:
            cursor.execute('''
                DELETE FROM message_history_vec
                WHERE channel_id = ?
                  AND id NOT IN (SELECT id FROM message_history WHERE channel_id = ?)
            ''', (channel_id, channel_id))
        except sqlite3.OperationalError:
            pass
    if deleted > 0:
        try:
            cursor.execute('''
                DELETE FROM message_history_fts
                WHERE channel_id = ?
                  AND rowid NOT IN (SELECT id FROM message_history WHERE channel_id = ?)
            ''', (channel_id, channel_id))
        except sqlite3.OperationalError:
            pass
    return deleted


def mark_message_history_processed(message_id) -> None:
    """Marca uma linha do histórico como processada pelo worker.

    NÃO grava worker_mentioned: mensagens podem ser processadas sem menção
    (chats privados, note-to-self, installs com allow_mentions=false).
    """
    if not message_id:
        return
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE message_history
            SET was_processed = 1
            WHERE message_id = ?
        ''', (message_id,))
        conn.commit()
    finally:
        conn.close()


def clear_channel_history(channel_id) -> int:
    """Remove toda a linha do tempo de um canal (usado pelo comando '/new')."""
    if not channel_id:
        return 0
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM message_history WHERE channel_id = ?', (channel_id,))
        deleted = cursor.rowcount
        if deleted > 0 and sqlite_vec_available():
            try:
                cursor.execute('''
                    DELETE FROM message_history_vec
                    WHERE channel_id = ?
                      AND id NOT IN (SELECT id FROM message_history WHERE channel_id = ?)
                ''', (channel_id, channel_id))
            except sqlite3.OperationalError:
                pass
        try:
            cursor.execute('''
                DELETE FROM message_history_fts
                WHERE channel_id = ?
                  AND rowid NOT IN (SELECT id FROM message_history WHERE channel_id = ?)
            ''', (channel_id, channel_id))
        except sqlite3.OperationalError:
            pass
        conn.commit()
        return deleted
    finally:
        conn.close()


def get_recent_message_history(cursor, channel_id, limit=None, exclude_message_id=None):
    """
    Retorna as últimas `limit` linhas da linha do tempo do canal, da MAIS
    ANTIGA para a MAIS RECENTE (ordem cronológica).

    Usa o cursor do chamador para rodar dentro da mesma transação.
    `exclude_message_id` pula a mensagem que está sendo processada agora.
    """
    if limit is None:
        limit = get_prompt_history_size()
    query = '''
        SELECT id, message_id, channel_id, remote_jid, is_group, sender_id,
               sender_id_alt, sender_name, from_me, is_bot, content,
               msg_timestamp, msg_date, msg_hour, msg_minute, msg_second,
               was_processed, worker_mentioned, created_at
        FROM message_history
        WHERE channel_id = ?
    '''
    params = [channel_id]
    if exclude_message_id:
        query += ' AND (message_id IS NULL OR message_id != ?)'
        params.append(exclude_message_id)
    query += ' ORDER BY msg_timestamp DESC, id DESC LIMIT ?'
    params.append(limit)
    cursor.execute(query, params)
    rows = list(cursor.fetchall())
    rows.reverse()
    return rows


# ---------------------------------------------------------------------------
# Message history vectors (message_history_vec / sqlite-vec)
# ---------------------------------------------------------------------------

def get_history_vec_dims(default: int = 768) -> int:
    """Dimensão dos vetores de message_history_vec.

    Resolução: env NW_HISTORY_VEC_DIMS (testes/deploys) > mapa do provider de
    embeddings local (all-MiniLM-L6-v2 = 384, agent.lc.embeddings.LOCAL_DIMS).
    """
    env = os.environ.get('NW_HISTORY_VEC_DIMS')
    if env:
        try:
            return max(1, int(env))
        except (TypeError, ValueError):
            pass
    try:
        from agent.lc.embeddings import LOCAL_DIMS
        return LOCAL_DIMS
    except Exception:
        return default


def _vec_table_dims_from_sql(sql):
    """Extrai as dims declaradas (``vector float[N]``) do CREATE da tabela
    vec0 em sqlite_master. None quando não é possível parsear."""
    if not sql:
        return None
    import re
    match = re.search(r'vector\s+float\[(\d+)\]', sql)
    return int(match.group(1)) if match else None


def insert_message_vector(row_id, channel_id, payload, vector) -> bool:
    """
    Grava/atualiza o vetor de uma mensagem do histórico.

    Args:
        row_id: message_history.id correspondente.
        channel_id: canal (partition key da tabela vec0).
        payload: dict (serializado em JSON) com os metadados de renderização.
        vector: embedding como lista/JSON ou blob float32 little-endian.

    Retorna False quando o sqlite-vec não está disponível ou falhou
    (fail-open: a mensagem continua salva, só fica sem vetor).
    """
    if row_id is None or not channel_id or vector is None:
        return False
    if not sqlite_vec_available():
        logging.getLogger(__name__).warning(
            "sqlite-vec is not loaded; message %s was embedded but its vector was not stored", row_id
        )
        return False
    payload_json = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    # vec0 accepts the vector as JSON text or a float32 blob; sqlite3 cannot
    # bind Python lists directly.
    if isinstance(vector, (list, tuple)):
        vector = json.dumps([float(x) for x in vector])
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM message_history_vec WHERE id = ?', (row_id,))
        cursor.execute('''
            INSERT INTO message_history_vec (id, channel_id, payload, vector)
            VALUES (?, ?, ?, ?)
        ''', (row_id, channel_id, payload_json, vector))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.DatabaseError as exc:
        # DatabaseError é pai de OperationalError e IntegrityError: cobre locks,
        # dims inválidas e colisão de PK em corrida (INSERT é idempotente via
        # DELETE+INSERT, então regravar é sempre seguro).
        logging.getLogger(__name__).warning(
            "Failed to store message vector for row %s: %s", row_id, exc
        )
        return False
    finally:
        conn.close()


def get_missing_vector_ids(limit: int = 200) -> list:
    """Ids de message_history (mais recentes primeiro) sem vetor gravado."""
    if not sqlite_vec_available():
        return []
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id FROM message_history
            WHERE id NOT IN (SELECT id FROM message_history_vec)
            ORDER BY id DESC
            LIMIT ?
        ''', (limit,))
        return [r['id'] for r in cursor.fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def get_history_window_cutoff(cursor, channel_id, limit=None):
    """msg_timestamp mais antigo dentro da janela N do canal (None se vazia).

    Usado pelo retriever para não devolver mensagens que já entram verbatim
    no contexto (janela de N mensagens do prompt).
    """
    if limit is None:
        limit = get_prompt_history_size()
    try:
        cursor.execute('''
            SELECT MIN(msg_timestamp) FROM (
                SELECT msg_timestamp FROM message_history
                WHERE channel_id = ?
                ORDER BY msg_timestamp DESC, id DESC
                LIMIT ?
            )
        ''', (channel_id, limit))
        row = cursor.fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


# ---------------------------------------------------------------------------
# Messages page: browse, duplicate/similar detection and deletion
# ---------------------------------------------------------------------------

# Most recent vectorized rows scanned for near-duplicates. Each scanned row
# costs one KNN query, so the cap keeps the Messages page responsive.
SIMILAR_SCAN_LIMIT = 1000
SIMILAR_NEIGHBORS = 5
MESSAGES_MAX_PER_PAGE = 200
MESSAGE_LIST_MODES = ('all', 'duplicates', 'similar')
_MESSAGE_COLUMNS = (
    'h.id, h.message_id, h.channel_id, h.remote_jid, h.is_group, h.sender_name, '
    'h.sender_id, h.from_me, h.is_bot, h.content, h.msg_timestamp, h.msg_date, '
    'h.msg_hour, h.msg_minute, h.msg_second, h.was_processed, h.created_at'
)


def _messages_scope_sql(channel_id=None, query=None, alias='h'):
    """WHERE clause (and params) shared by every Messages listing."""
    clauses, params = [], []
    if channel_id:
        clauses.append(f'{alias}.channel_id = ?')
        params.append(channel_id)
    if query:
        escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        clauses.append(f"{alias}.content LIKE ? ESCAPE '\\'")
        params.append(f'%{escaped}%')
    return (' AND '.join(clauses) or '1=1'), params


def _message_row_to_dict(row, has_vector: bool, score=None, best_match_id=None) -> dict:
    data = dict(row)
    data['has_vector'] = bool(has_vector)
    data['is_bot'] = bool(data.get('is_bot'))
    data['from_me'] = bool(data.get('from_me'))
    if score is not None:
        data['similarity'] = round(score, 4)
        data['best_match_id'] = best_match_id
    return data


def _fetch_messages_by_ids(cursor, ids, has_vec: bool) -> dict:
    """Returns {id: row_dict} for the given message_history ids."""
    if not ids:
        return {}
    select_vec = 'EXISTS (SELECT 1 FROM message_history_vec v WHERE v.id = h.id)' if has_vec else '0'
    placeholders = ','.join('?' * len(ids))
    cursor.execute(
        f'SELECT {_MESSAGE_COLUMNS}, {select_vec} AS has_vector '
        f'FROM message_history h WHERE h.id IN ({placeholders})',
        list(ids),
    )
    return {row['id']: _message_row_to_dict(row, row['has_vector']) for row in cursor.fetchall()}


def _find_similar_message_groups(cursor, channel_id, threshold):
    """Connected components of messages whose embeddings are close enough.

    Scans the most recent SIMILAR_SCAN_LIMIT vectorized rows and asks the
    sqlite-vec index for each one's nearest neighbours inside its own channel
    (the partition key keeps the search scoped per chat). Two rows are linked
    when cosine similarity >= threshold.

    Returns (groups, best): groups is a list of id lists (size >= 2), best maps
    each linked id to (similarity, other_id) of its closest match.
    """
    max_distance = 1.0 - threshold
    cursor.execute(
        '''
        SELECT v.id, v.channel_id, v.vector
        FROM message_history_vec v
        JOIN message_history h ON h.id = v.id
        WHERE (? IS NULL OR v.channel_id = ?)
        ORDER BY v.id DESC
        LIMIT ?
        ''',
        (channel_id, channel_id, SIMILAR_SCAN_LIMIT),
    )
    rows = cursor.fetchall()

    parent = {}

    def find(node):
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    best = {}
    for row in rows:
        cursor.execute(
            '''
            SELECT id, distance FROM message_history_vec
            WHERE channel_id = ? AND vector MATCH ? AND k = ?
            ''',
            (row['channel_id'], row['vector'], SIMILAR_NEIGHBORS + 1),
        )
        for neighbour in cursor.fetchall():
            if neighbour['id'] == row['id'] or neighbour['distance'] > max_distance:
                continue
            score = 1.0 - neighbour['distance']
            if score > best.get(row['id'], (-1.0, None))[0]:
                best[row['id']] = (score, neighbour['id'])
            root_a, root_b = find(row['id']), find(neighbour['id'])
            if root_a != root_b:
                parent[root_b] = root_a

    components = {}
    for node in best:
        components.setdefault(find(node), []).append(node)
    groups = [sorted(ids, reverse=True) for ids in components.values() if len(ids) >= 2]
    return groups, best


def list_messages_admin(channel_id=None, query=None, mode='all', threshold=0.9,
                        page=1, per_page=50) -> dict:
    """
    Lists message_history rows for the Messages page.

    mode:
        'all'        -> paginated messages, newest first.
        'duplicates' -> groups of messages with identical text (case and
                        surrounding whitespace ignored).
        'similar'    -> groups of messages whose embeddings have cosine
                        similarity >= threshold (see _find_similar_message_groups).

    Duplicate and similar listings are paginated by group.
    """
    if mode not in MESSAGE_LIST_MODES:
        mode = 'all'
    page = max(1, int(page))
    per_page = min(max(1, int(per_page)), MESSAGES_MAX_PER_PAGE)
    offset = (page - 1) * per_page
    has_vec = sqlite_vec_available()

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT channel_id FROM message_history ORDER BY channel_id')
        channels = [r['channel_id'] for r in cursor.fetchall()]
        where, params = _messages_scope_sql(channel_id, query)

        result = {
            'mode': mode,
            'threshold': threshold,
            'page': page,
            'per_page': per_page,
            'channels': channels,
            'groups': [],
            'messages': [],
        }

        if mode == 'duplicates':
            cursor.execute(
                f'''
                SELECT COUNT(*) FROM (
                    SELECT 1 FROM message_history h WHERE {where}
                    GROUP BY lower(trim(h.content)) HAVING COUNT(*) > 1
                )
                ''',
                params,
            )
            result['total'] = cursor.fetchone()[0]
            cursor.execute(
                f'''
                SELECT lower(trim(h.content)) AS norm, COUNT(*) AS n, MAX(h.id) AS newest
                FROM message_history h WHERE {where}
                GROUP BY norm HAVING COUNT(*) > 1
                ORDER BY n DESC, newest DESC
                LIMIT ? OFFSET ?
                ''',
                params + [per_page, offset],
            )
            for group in cursor.fetchall():
                cursor.execute(
                    f'''
                    SELECT {_MESSAGE_COLUMNS},
                           {'EXISTS (SELECT 1 FROM message_history_vec v WHERE v.id = h.id)' if has_vec else '0'} AS has_vector
                    FROM message_history h
                    WHERE {where} AND lower(trim(h.content)) = ?
                    ORDER BY h.id DESC
                    ''',
                    params + [group['norm']],
                )
                members = [_message_row_to_dict(r, r['has_vector']) for r in cursor.fetchall()]
                result['groups'].append({'key': group['norm'], 'count': group['n'], 'messages': members})

        elif mode == 'similar':
            if has_vec:
                groups, best = _find_similar_message_groups(cursor, channel_id, threshold)
            else:
                groups, best = [], {}
            if query and groups:
                # Keyword filter for similar groups: keep groups with a matching member.
                needle = query.lower()
                texts = _fetch_messages_by_ids(cursor, [mid for ids in groups for mid in ids], False)
                groups = [
                    ids for ids in groups
                    if any(needle in texts[mid]['content'].lower() for mid in ids if mid in texts)
                ]
            groups.sort(key=lambda ids: (-len(ids), -ids[0]))
            result['total'] = len(groups)
            result['scanned'] = SIMILAR_SCAN_LIMIT
            for ids in groups[offset:offset + per_page]:
                by_id = _fetch_messages_by_ids(cursor, ids, has_vec)
                members = []
                for mid in ids:
                    if mid not in by_id:
                        continue
                    score, other = best.get(mid, (None, None))
                    members.append(_message_row_to_dict(
                        by_id[mid], by_id[mid]['has_vector'], score, other,
                    ))
                result['groups'].append({'key': f'similar-{ids[0]}', 'count': len(ids), 'messages': members})

        else:
            cursor.execute(f'SELECT COUNT(*) FROM message_history h WHERE {where}', params)
            result['total'] = cursor.fetchone()[0]
            select_vec = 'EXISTS (SELECT 1 FROM message_history_vec v WHERE v.id = h.id)' if has_vec else '0'
            cursor.execute(
                f'''
                SELECT {_MESSAGE_COLUMNS}, {select_vec} AS has_vector
                FROM message_history h WHERE {where}
                ORDER BY h.msg_timestamp DESC, h.id DESC
                LIMIT ? OFFSET ?
                ''',
                params + [per_page, offset],
            )
            result['messages'] = [_message_row_to_dict(r, r['has_vector']) for r in cursor.fetchall()]

        return result
    finally:
        conn.close()


def delete_message_history_rows(ids) -> dict:
    """
    Deletes messages together with everything derived from them:
    the vector (message_history_vec), the BM25 keyword entry
    (message_history_fts) and the row itself (message_history).

    Returns {"deleted": <message rows>, "vectors_deleted": <vector rows>}.
    """
    clean = sorted({int(i) for i in ids})
    if not clean:
        return {'deleted': 0, 'vectors_deleted': 0}

    conn = get_db()
    try:
        cursor = conn.cursor()
        vectors_deleted = 0
        if sqlite_vec_available():
            for mid in clean:
                cursor.execute('DELETE FROM message_history_vec WHERE id = ?', (mid,))
                vectors_deleted += cursor.rowcount
        try:
            cursor.executemany('DELETE FROM message_history_fts WHERE rowid = ?', [(mid,) for mid in clean])
        except sqlite3.OperationalError:
            pass  # FTS table missing on very old databases
        cursor.executemany('DELETE FROM message_history WHERE id = ?', [(mid,) for mid in clean])
        deleted = cursor.rowcount  # executemany reports the total across all ids
        conn.commit()
        return {'deleted': deleted, 'vectors_deleted': vectors_deleted}
    finally:
        conn.close()


if __name__ == '__main__':
    init_db()
