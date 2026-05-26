import contextvars

# Context variable to hold the current session ID
current_session_id = contextvars.ContextVar("current_session_id", default=None)
