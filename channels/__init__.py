"""
Channel adapter registry.
Each channel adapter registers itself here. The app routes inbound messages
from external platforms through the appropriate adapter.
"""

# Registry of active channel adapters keyed by channel type name.
_adapters = {}


def register_channel(name, adapter):
    """Register a channel adapter by name."""
    _adapters[name] = adapter


def get_channel(name):
    """Get a registered channel adapter by name, or None."""
    return _adapters.get(name)


def get_all_channels():
    """Return all registered channel adapters as a dict."""
    return dict(_adapters)
