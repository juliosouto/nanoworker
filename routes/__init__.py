def register_routes(app):
    from .api_chat import api_chat_bp
    from .api_cron import api_cron_bp
    from .api_files import api_files_bp
    from .api_llm import api_llm_bp
    from .api_memory import api_memory_bp
    from .api_settings import api_settings_bp
    from .api_whatsapp import api_whatsapp_bp
    from .views import views_bp
    from .webhooks import webhooks_bp

    app.register_blueprint(views_bp)
    app.register_blueprint(api_files_bp)
    app.register_blueprint(api_whatsapp_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(api_chat_bp)
    app.register_blueprint(api_settings_bp)
    app.register_blueprint(api_llm_bp)
    app.register_blueprint(api_cron_bp)
    app.register_blueprint(api_memory_bp)
