"""Real token counting for context-budget accounting.

Replaces the legacy "1 token ~= 4 chars" heuristic with BPE counting via
``tiktoken`` (``cl100k_base``), which tracks real model tokenizers far more
closely than the character estimate — especially for code, JSON tool schemas
and non-ASCII text. When tiktoken is unavailable or the counter is pinned to
``heuristic``, the legacy math is preserved exactly.

Mode resolution (agent.lc.settings.token_counter_mode) is accepted as a
parameter so hot loops (pruning, slicing) resolve it once per operation
instead of hitting app_config per message.
"""
import logging

from agent.lc import settings

logger = logging.getLogger(__name__)

# Legacy constant kept for reference and the heuristic fallback.
CHARS_PER_TOKEN = 4

_ENCODING_NAME = "cl100k_base"
_ENCODINGS = {}
_ENCODING_FAILED = False


def _encoding():
    """Loads (and caches) the tiktoken encoding, or None on failure."""
    global _ENCODING_FAILED
    if _ENCODING_NAME in _ENCODINGS:
        return _ENCODINGS[_ENCODING_NAME]
    if _ENCODING_FAILED:
        return None
    try:
        import tiktoken
        enc = tiktoken.get_encoding(_ENCODING_NAME)
    except Exception as exc:
        _ENCODING_FAILED = True
        logger.warning("tiktoken unavailable (%s); falling back to heuristic token counting", exc)
        return None
    _ENCODINGS[_ENCODING_NAME] = enc
    return enc


def heuristic_count(text) -> int:
    """Legacy estimate: 1 token ~= 4 chars (never returns less than 1)."""
    if not text:
        return 0
    return max(1, len(str(text)) // CHARS_PER_TOKEN)


def count_tokens(text, mode=None) -> int:
    """Token count for a string.

    Args:
        text: Any value; stringified when not a str. None/empty -> 0.
        mode: 'tiktoken', 'heuristic' or None to resolve from settings.

    Returns:
        Number of tokens (int).
    """
    if text is None or text == "":
        return 0
    if mode is None:
        mode = settings.token_counter_mode()
    if mode != "heuristic":
        enc = _encoding()
        if enc is not None:
            try:
                # disallowed_special=() so literal strings like "text" in
                # prompts never raise an encoding error.
                return len(enc.encode(str(text), disallowed_special=()))
            except Exception as exc:
                logger.debug("tiktoken encode failed (%s); using heuristic", exc)
    return heuristic_count(text)


def truncate_tail(text, token_budget, mode=None):
    """Keeps only the tail of `text` within `token_budget` tokens.

    Mirrors the legacy behavior of keeping the LAST slice of the message
    (the most recent content), but the budget is now measured in real
    tokens instead of chars when mode is 'tiktoken'.

    heuristic mode reproduces the old ``text[-budget * 4:]`` slice exactly.
    """
    if not text or not token_budget or token_budget <= 0:
        return text
    text = str(text)
    if mode is None:
        mode = settings.token_counter_mode()
    if mode == "heuristic":
        max_chars = token_budget * CHARS_PER_TOKEN
        return text[-max_chars:] if len(text) > max_chars else text

    enc = _encoding()
    if enc is None:
        max_chars = token_budget * CHARS_PER_TOKEN
        return text[-max_chars:] if len(text) > max_chars else text
    try:
        tokens = enc.encode(text, disallowed_special=())
    except Exception as exc:
        logger.debug("tiktoken encode failed (%s); using heuristic tail", exc)
        max_chars = token_budget * CHARS_PER_TOKEN
        return text[-max_chars:] if len(text) > max_chars else text
    if len(tokens) <= token_budget:
        return text
    return enc.decode(tokens[-token_budget:])
