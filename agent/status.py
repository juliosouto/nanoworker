"""Live status of the agent's work, shown to the user while it runs.

The WhatsApp channel shows these as one reply to the user's message that is
edited at each step ("Buscando na web...", "Revisando a resposta...") and is
finally replaced by the answer. ``process_message`` installs the channel's
reporter for the turn; everywhere else just calls :func:`report_status`,
which does nothing when no reporter is installed (IDE, cron, tests).
"""

import logging
from contextvars import ContextVar

logger = logging.getLogger(__name__)

_reporter: ContextVar = ContextVar("agent_status_reporter", default=None)

THINKING = "🤔 Pensando..."
PLANNING = "🧭 Planejando os passos..."
ANALYZING = "📦 Analisando os resultados..."
REVIEWING = "🔎 Revisando a resposta..."
REFINING = "🔄 Refinando a resposta..."

# (substring of the tool name, status). First match wins.
_TOOL_STATUSES = [
    ("search_web", "🌐 Buscando na web..."),
    ("web_search", "🌐 Buscando na web..."),
    ("news", "📰 Buscando notícias..."),
    ("weather", "🌤️ Consultando o clima..."),
    ("http_request", "🔌 Chamando uma API..."),
    ("browser", "🧭 Navegando em um site..."),
    ("scrap", "📄 Lendo uma página..."),
    ("webpage", "📄 Lendo uma página..."),
    ("download", "⬇️ Baixando um arquivo..."),
    ("image", "🖼️ Trabalhando com uma imagem..."),
    ("pdf", "📄 Lendo um PDF..."),
    ("audio", "🎧 Trabalhando com áudio..."),
    ("whatsapp", "💬 Preparando uma mensagem..."),
    ("memory", "🧠 Consultando a memória..."),
    ("calendar", "📅 Mexendo na agenda..."),
    ("schedul", "⏰ Agendando uma tarefa..."),
    ("reminder", "⏰ Mexendo nos lembretes..."),
    ("mail", "✉️ Mexendo nos e-mails..."),
    ("price", "💹 Consultando cotações..."),
    ("crypto", "💹 Consultando cotações..."),
    ("stock", "💹 Consultando o mercado..."),
    ("command", "💻 Executando um comando..."),
    ("bash", "💻 Executando um comando..."),
    ("file", "📁 Trabalhando com arquivos..."),
    ("document", "📁 Trabalhando com documentos..."),
    ("map", "🗺️ Consultando mapas..."),
]


def tool_status(tool_name: str) -> str:
    """Friendly status for a tool call, e.g. 'search_web' → 'Buscando na web...'."""
    name = (tool_name or "").lower()
    for key, status in _TOOL_STATUSES:
        if key in name:
            return status
    return f"🔧 Usando a ferramenta {tool_name}..."


def set_status_reporter(reporter):
    """Install ``reporter(text)`` for the current turn; returns a reset token."""
    return _reporter.set(reporter)


def reset_status_reporter(token) -> None:
    _reporter.reset(token)


def report_status(text: str) -> None:
    """Show ``text`` as the current status. Never raises."""
    reporter = _reporter.get()
    if reporter is None or not text:
        return
    try:
        reporter(text)
    except Exception as e:
        logger.warning("Status update failed: %s", e)
