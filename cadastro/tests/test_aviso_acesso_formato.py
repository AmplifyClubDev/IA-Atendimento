"""Auditoria 21/11/2026: aviso de acesso liberado no formato do WhatsApp."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from legado.cadastro_delivery import ACCESS_RELEASED_NOTICE, first_name  # noqa: E402


def test_primeiro_nome_sem_caixa_alta():
    assert first_name("GABRIELA HELENA DA SILVA ALVES") == "Gabriela"
    assert first_name("  ana ") == "Ana"
    assert first_name("") == "tudo bem"


def test_aviso_em_paragrafos_curtos_com_negrito():
    texto = ACCESS_RELEASED_NOTICE.format(name=first_name("JOAO SILVA"), email="joao@exemplo.com")
    assert texto.startswith("Oi, Joao! 🎉\n\n*Seu acesso à Amplify foi liberado* 💙\n\n")
    assert "\njoao@exemplo.com\n\n" in texto
    assert texto.count("\n\n") == 4
    assert "JOAO" not in texto
