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
    import shutil
    _original_popen_init = subprocess.Popen.__init__
    def _patched_popen_init(self, args, **kwargs):
        if 'close_fds' not in kwargs:
            kwargs['close_fds'] = False
            
        executable = kwargs.get('executable')
        if executable is None:
            if isinstance(args, (str, bytes, os.PathLike)):
                cmd = args
            else:
                cmd = args[0] if args else None
                
            if cmd and isinstance(cmd, str) and not os.path.dirname(cmd):
                resolved = shutil.which(cmd)
                if resolved:
                    if isinstance(args, list):
                        args = list(args)
                        args[0] = resolved
                    elif isinstance(args, tuple):
                        args = list(args)
                        args[0] = resolved
                        args = tuple(args)
                    else:
                        kwargs['executable'] = resolved

        dups_to_close = []
        for key, default_fd in [('stdin', 0), ('stdout', 1), ('stderr', 2)]:
            val = kwargs.get(key)
            if val == default_fd:
                new_fd = os.dup(val)
                kwargs[key] = new_fd
                dups_to_close.append(new_fd)

        try:
            return _original_popen_init(self, args, **kwargs)
        finally:
            for fd in dups_to_close:
                try:
                    os.close(fd)
                except OSError:
                    pass
    subprocess.Popen.__init__ = _patched_popen_init

import threading
from dotenv import load_dotenv
from flask import Flask, request, redirect, session
from werkzeug.middleware.proxy_fix import ProxyFix

import state
from database import get_ide_config, init_db, get_config, set_config
from routes import register_routes
from routes.webhooks import webhooks_bp
from sweeper import sweep
from security import init_security, csrf

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
# Tell Flask it is behind a proxy (Caddy) so that request.remote_addr is the real client IP.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Initialize Proxy Manager Global Monkey-Patch
from utils.proxy_manager import setup_global_proxy
setup_global_proxy()

# Initialize database and apply migrations on startup
init_db()

# Initialize Security Mechanisms (Rate Limiting, CSRF, Talisman)
init_security(app)

# Ensure secret key is set
secret = get_config('FLASK_SECRET_KEY')
if not secret:
    import secrets
    secret = secrets.token_hex(32)
    set_config('FLASK_SECRET_KEY', secret)
app.secret_key = secret

webhook_secret = get_config('WEBHOOK_SECRET')
if not webhook_secret:
    import secrets
    webhook_secret = secrets.token_hex(32)
    set_config('WEBHOOK_SECRET', webhook_secret)

@app.before_request
def check_login():
    if request.path.startswith('/static') or request.path in ['/login', '/api/login/toggle']:
        return

    # Trusted internal services
    secret = request.headers.get('X-Webhook-Secret')
    expected_secret = get_config('WEBHOOK_SECRET')
    if secret and expected_secret and secret == expected_secret:
        return

    login_enabled = get_config('LOGIN_ENABLED', 'false') == 'true'
    if login_enabled:
        if not session.get('logged_in'):
            return redirect('/login')

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
        
        env = os.environ.copy()
        env['WEBHOOK_SECRET'] = get_config('WEBHOOK_SECRET')
        state.worker_process = subprocess.Popen(['node', worker_script], env=env)
        
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

# Exempt webhooks from CSRF protection as they are called by external services
csrf.exempt(webhooks_bp)

if __name__ == '__main__':
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_PORT', 5000))
    
    print("\n" + "═"*60)
    print("\033[1;36m" + " 🤖 NanoWorker Agent Initialized!" + "\033[0m")
    print("═"*60)
    display_host = "localhost" if host == "0.0.0.0" else host
    print("\033[1;32m" + f" 🚀 Access your panel at: http://{display_host}:{port}" + "\033[0m")
    print("═"*60 + "\n")
    
    app.run(debug=True, host=host, port=port)
