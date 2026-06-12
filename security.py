from flask import jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman

# Initialize Limiter
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    strategy="fixed-window"
)

# Initialize CSRF Protection
csrf = CSRFProtect()

def init_security(app):
    """
    Initializes all security mechanisms (Rate Limiting, CSRF, Secure Headers)
    on the given Flask app.
    """
    # 1. Initialize Rate Limiter
    limiter.init_app(app)

    # 2. Initialize CSRF Protection
    # This will automatically protect all forms of non-GET requests.
    csrf.init_app(app)
    
    # 3. Initialize Secure HTTP Headers via Talisman
    # We use 'unsafe-inline' and 'unsafe-eval' to not break the existing UI/JS logic.
    csp = {
        'default-src': [
            '\'self\'',
            'https://fonts.googleapis.com',
            'https://fonts.gstatic.com'
        ],
        'style-src': [
            '\'self\'',
            '\'unsafe-inline\'',
            'https://fonts.googleapis.com'
        ],
        'script-src': [
            '\'self\'',
            '\'unsafe-inline\'',
            '\'unsafe-eval\''
        ],
        'img-src': [
            '*',
            'data:'
        ],
        'connect-src': [
            '*'
        ]
    }
    
    # Disable force_https to allow local development on HTTP
    Talisman(app, content_security_policy=csp, force_https=False, session_cookie_secure=False)

    # 4. Error Handlers
    @app.errorhandler(429)
    def ratelimit_handler(e):
        if request.path.startswith('/api/'):
            return jsonify(error="ratelimit_exceeded", message=str(e.description)), 429
        if request.path == '/login':
            return render_template('login.html', error=f"Rate limit exceeded: {e.description}"), 429
        return f"Rate limit exceeded: {e.description}", 429

    @app.errorhandler(400)
    def csrf_error(e):
        if 'CSRF' in str(e.description) or 'CSRF' in getattr(e, 'name', ''):
            if request.path.startswith('/api/'):
                return jsonify(error="csrf_error", message=str(e.description)), 400
            return f"CSRF Error: {e.description}", 400
        return f"Bad Request: {e.description}", 400
