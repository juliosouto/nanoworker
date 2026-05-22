import functools
from database import get_config

def require_permission(permission_key: str):
    """
    Decorator to check if a specific permission is enabled in the database
    before executing the wrapped function.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            is_enabled = get_config(permission_key, 'false').lower() == 'true'
            if not is_enabled:
                return f"Error: Access denied. The user has disabled the '{permission_key}' permission in the settings."
            return func(*args, **kwargs)
        return wrapper
    return decorator
