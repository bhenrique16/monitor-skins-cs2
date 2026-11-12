"""Configuração por variáveis de ambiente, com leitura opcional de um arquivo .env."""
from __future__ import annotations

import os

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def load_env(path: str = ".env", environ=None) -> None:
    """Lê linhas CHAVE=valor. Variáveis já definidas no ambiente têm prioridade."""
    environ = os.environ if environ is None else environ
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in environ:
            environ[key] = value


def data_dir(environ=None) -> str:
    environ = os.environ if environ is None else environ
    return environ.get("SKINMON_DATA") or "data"


def int_setting(environ, key: str, default: int) -> int:
    try:
        return int(environ.get(key, default))
    except (TypeError, ValueError):
        return default
