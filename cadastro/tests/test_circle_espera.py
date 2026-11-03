"""O Circle às vezes leva mais de 9 s para mostrar grupo, tag e espaço novos (30/10, gabiosantana1)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from legado.cadastro_delivery import COMMUNITY, GROUPS, Circle  # noqa: E402

TAGS = {label: 900 + i for i, label in enumerate(GROUPS)}


class SlowCircle(Circle):
    """Membro já existe; grupo, tag e espaço só aparecem depois de `ready_after` leituras de conferência."""

    def __init__(self, ready_after):
        self.ready_after, self.reads, self.writes = ready_after, 0, []

    def _visible(self):
        return self.reads > self.ready_after

    def call(self, path, method="GET", body=None, missing=False):
        if method != "GET":
            self.writes.append((method, path))
            return {}
        if path.startswith("/community_members/search"):
            return {"id": 7, "community_id": COMMUNITY, "email": "a@b.co", "member_tags": []}
        if path == "/community_members/7":
            self.reads += 1
            tags = [{"id": TAGS["Start"]}] if self._visible() else []
            return {"id": 7, "community_id": COMMUNITY, "email": "a@b.co", "member_tags": tags}
        raise AssertionError(path)

    def records(self, path):
        if path == "/access_groups":
            return [{"id": i, "community_id": COMMUNITY, "name": "Creator " + l, "status": "active"} for l, i in GROUPS.items()]
        if path == "/member_tags":
            return [{"id": TAGS[l], "name": "Creator " + l} for l in GROUPS]
        if path.endswith("/access_groups"):
            return [{"id": GROUPS["Start"], "status": "active"}] if self._visible() else []
        if path.startswith("/community_member_spaces"):
            return [{"id": 2794358}] if self._visible() else []
        raise AssertionError(path)


def test_confirmacao_lenta_do_circle_ainda_libera_o_acesso(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    circle = SlowCircle(ready_after=4)  # visível só na 5ª leitura: passava de 9 s
    assert circle.provision(email="a@b.co", name="Teste", tier="Start", before_write=lambda: None) == 7
    assert ("POST", f"/access_groups/{GROUPS['Start']}/community_members") in circle.writes


def test_circle_que_nunca_confirma_vai_para_revisao(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    circle = SlowCircle(ready_after=99)
    try:
        circle.provision(email="a@b.co", name="Teste", tier="Start", before_write=lambda: None)
    except RuntimeError as error:
        assert str(error) == "circle_leitura_ainda_nao_confirmada"
    else:
        raise AssertionError("devia ir para revisão manual")
