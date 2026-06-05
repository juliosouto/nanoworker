import atexit
import logging
import os
import platform
import signal

os.environ['OBJC_DISABLE_INITIALIZE_FORK_SAFETY'] = 'YES'

import subprocess

# On macOS, fork() crashes when Network.framework has been initialized (by any
# socket/SSL import — Flask loads these at import time). Python's subprocess
# defaults to close_fds=True, which forces fork()+exec instead of posix_spawn.
# By defaulting close_fds=False on macOS, subprocess will use posix_spawn which
# does not trigger Network.framework's atfork crash handler.
if platform.system() == 'Darwin' and getattr(subprocess, '_USE_POSIX_SPAWN', False):
    _original_popen_init = subprocess.Popen.__init__
    def _patched_popen_init(self, args, **kwargs):
        if 'close_fds' not in kwargs:
            kwargs['close_fds'] = False
        return _original_popen_init(self, args, **kwargs)
    subprocess.Popen.__init__ = _patched_popen_init

import threading
from dotenv import load_dotenv
from flask import Flask

import state
from database import get_ide_config, init_db
from routes import register_routes
from sweeper import sweep

import socket

def find_free_port(start_port=5000, end_port=5100):
    for port in range(start_port, end_port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                pass
    return start_port

if 'FLASK_PORT' not in os.environ:
    os.environ['FLASK_PORT'] = str(find_free_port(5000))

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Initialize database and apply migrations on startup
init_db()

# Ensure static directory exists
if not os.path.exists('static'):
    os.makedirs('static')

# Initialize global state variables
state.CURRENT_PROJECT_PATH = get_ide_config('CURRENT_PROJECT_PATH')

# Start the Baileys background worker
run_workers = False
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    run_workers = True
elif __name__ != '__main__':
    run_workers = True

if run_workers:
    worker_script = os.path.join(os.path.dirname(__file__), 'node_scripts', 'wa_worker.js')
    if os.path.exists(worker_script):
        logging.info("Starting Baileys WhatsApp Worker (wa_worker.js) in the background...")
        state.worker_process = subprocess.Popen(['node', worker_script])
        
        def cleanup_worker():
            """
            Função registrada via atexit para garantir o encerramento limpo do 
            processo em segundo plano do Baileys (wa_worker.js) quando o servidor parar.
            Usa os.kill() direto em vez de subprocess para evitar fork() durante
            o shutdown do Python, que causa crash no macOS com Network.framework.
            """
            if state.worker_process and state.worker_process.poll() is None:
                logging.info("Shutting down Baileys WhatsApp Worker...")
                try:
                    os.kill(state.worker_process.pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
                
        atexit.register(cleanup_worker)

    sweeper_thread = threading.Thread(target=sweep, daemon=True)
    sweeper_thread.start()
    logging.info("Started Sweeper thread for scheduled tasks.")

# Register all Blueprints
register_routes(app)

if __name__ == '__main__':
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_PORT', 5000))
    app.run(debug=True, host=host, port=port)
