import atexit
import logging
import os
import subprocess
import threading

from dotenv import load_dotenv
from flask import Flask

import state
from database import get_ide_config, init_db
from routes import register_routes
from sweeper import sweep

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
            """
            if state.worker_process:
                logging.info("Shutting down Baileys WhatsApp Worker...")
                state.worker_process.terminate()
                state.worker_process.wait()
                
        atexit.register(cleanup_worker)

    sweeper_thread = threading.Thread(target=sweep, daemon=True)
    sweeper_thread.start()
    logging.info("Started Sweeper thread for scheduled tasks.")

# Register all Blueprints
register_routes(app)

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
