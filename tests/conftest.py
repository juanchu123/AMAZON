"""Para todos los tests: nunca se manda un correo real ni se dejan .eml en salidas/."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


@pytest.fixture(autouse=True)
def sin_correo_real(tmp_path, monkeypatch):
    for v in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(config, "CORREOS_PENDIENTES", tmp_path / "correos")
