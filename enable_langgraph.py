"""Habilita o fluxo de agentes LangGraph no nanoworker.db.

Rode na raiz do projeto (onde fica o nanoworker.db; no Docker, /app):
    python enable_langgraph.py            # habilita
    python enable_langgraph.py --rollback # volta ao fluxo antigo

Não precisa reiniciar o app: get_config lê o banco a cada chamada. Variáveis
de ambiente (LLM_STACK, AGENT_FLOW) têm prioridade sobre o banco.
"""
import shutil
import sqlite3
import sys
from datetime import datetime

DB_PATH = "nanoworker.db"

ENABLE = {
    "LLM_STACK": "langchain",       # o fluxo em grafo exige o stack LangChain
    "AGENT_FLOW": "graph",          # planner + executor + avaliador
    "AGENT_PLANNER": "auto",        # off | auto | always ("" segue PLAN_BEFORE_EXECUTION)
    "AGENT_EVALUATOR_MODEL": "",    # "" = usa os modelos do próprio worker
    "AGENT_PLANNER_MODEL": "",      # "" = usa os modelos do próprio worker
}
ROLLBACK = {
    "LLM_STACK": "legacy",
    "AGENT_FLOW": "legacy",
}


def main():
    values = ROLLBACK if "--rollback" in sys.argv else ENABLE

    backup = f"{DB_PATH}.bak-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(DB_PATH, backup)
    print(f"Backup: {backup}")

    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    try:
        keys = list(values)
        marks = ",".join("?" * len(keys))
        before = dict(conn.execute(
            f"SELECT key, value FROM app_config WHERE key IN ({marks})", keys
        ).fetchall())

        with conn:  # uma transação: grava tudo ou nada
            conn.executemany(
                "INSERT INTO app_config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                values.items(),
            )

        for key, value in values.items():
            print(f"{key}: {before.get(key, '(não existia)')!r} -> {value!r}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
