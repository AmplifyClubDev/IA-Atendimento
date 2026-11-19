"""Metadata-only Chatwoot projection on a verified Circle access."""
from unittest.mock import patch

from chatwoot_access_label import AccessLabel
from entrega import Entrega


ENV = {
    "CADASTRO_CHATWOOT_ETIQUETA_ACESSO": "acesso-liberado",
    "CHATWOOT_BASE_URL": "https://chatwoot.example",
    "CHATWOOT_ACCOUNT_ID": "1",
    "CHATWOOT_API_TOKEN": "test-only",
}
JOB = {"conversation_id": "4321", "account_id": "1"}
CONVERSATION = {"id": 4321, "account_id": 1, "inbox_id": 3}


class Response:
    def __init__(self, body, status=200):
        self.body = body
        self.status_code = status

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, labels, *, detail=CONVERSATION, lost_ack=False, pending=False):
        self.labels = list(labels)
        self.detail = detail
        self.lost_ack = lost_ack
        self.pending = pending
        self.calls = []

    def request(self, method, url, **kwargs):
        assert kwargs["allow_redirects"] is False
        self.calls.append((method, url, kwargs.get("json")))
        if method == "POST":
            if not self.pending:
                self.labels += [item for item in kwargs["json"]["labels"]["add"] if item not in self.labels]
            if self.lost_ack:
                raise TimeoutError
            return Response({}, status=202)
        if url.endswith("/labels"):
            return Response({"payload": self.labels.copy()})
        return Response(self.detail)


def projection(session, env=ENV):
    return AccessLabel(env, session=session, sleep=lambda _: None)


def test_additive_metadata_only_and_already_present():
    session = FakeSession(["cadastro", "prioridade"])
    adapter = projection(session)
    assert adapter.apply(JOB) == "applied"
    assert adapter.apply(JOB) == "already_present"
    assert session.labels == ["cadastro", "prioridade", "acesso-liberado"]
    assert [c for c in session.calls if c[0] == "POST"] == [
        ("POST", "https://chatwoot.example/api/v1/accounts/1/bulk_actions",
         {"type": "Conversation", "ids": [4321], "labels": {"add": ["acesso-liberado"]}}),
    ]
    assert all("/messages" not in call[1] for call in session.calls)


def test_lost_ack_checks_readback_without_second_write():
    session = FakeSession(["cadastro"], lost_ack=True)
    assert projection(session).apply(JOB) == "applied"
    assert sum(c[0] == "POST" for c in session.calls) == 1


def test_enqueue_without_readback_not_success():
    session = FakeSession(["cadastro"], pending=True)
    assert projection(session).apply(JOB) == "pending"
    assert sum(c[0] == "POST" for c in session.calls) == 1


def test_wrong_inbox_and_missing_account_never_write():
    session = FakeSession(["cadastro"], detail={**CONVERSATION, "inbox_id": 4})
    assert projection(session).apply(JOB) == "unverified_conversation"
    assert projection(session).apply({"conversation_id": "4321"}) == "unverified_conversation"
    assert not any(call[0] == "POST" for call in session.calls)


def test_no_label_config_is_kill_switch():
    session = FakeSession([])
    assert projection(session, {}).apply(JOB) == "disabled"
    assert session.calls == []


class Gateway:
    def __init__(self, timeline, circle_done=False):
        self.timeline = timeline
        self.circle_done = circle_done

    def rpc(self, name, params):
        if name == "destino_etiqueta_acesso_circle_v5":
            self.timeline.append("lookup")
            return JOB.copy()
        if "preparar" in name:
            return {**JOB, "ready": True, "name": "Synthetic", "email": "test@example.invalid",
                    "onboarding_id": "synthetic", "attempt": 1, "gmv": 0,
                    "gmv_verificado": 0, "circle_feito": self.circle_done, "categoria_entregue": "Start"}
        self.timeline.append(params["p_etapa"])
        return {}


class Circle:
    def __init__(self, timeline):
        self.timeline = timeline

    def provision(self, **kwargs):
        self.timeline.append("circle")
        return 100


def test_v5_metadata_failure_does_not_replay_or_block_notice():
    timeline = []
    adapter = Entrega(Gateway(timeline), circle_token="test", settings={}, enabled=True,
                      circle_factory=lambda _: Circle(timeline),
                      send=lambda *args: timeline.append("email") or "receipt",
                      notify=lambda job: timeline.append("notice") or {})
    with patch.dict("os.environ", ENV), patch("chatwoot_access_label.AccessLabel.apply", side_effect=OSError):
        result = adapter.executar("synthetic")
    assert result["status"] == "acessos_liberados"
    assert result["access_label_status"] == "pending"
    assert timeline == ["circle", "circle_confirmado", "lookup", "email", "email_confirmado", "notice"]


def test_v5_labels_only_after_circle_and_in_both_paths():
    for circle_done in (False, True):
        timeline = []
        adapter = Entrega(Gateway(timeline, circle_done=circle_done), circle_token="test", settings={}, enabled=True,
                          circle_factory=lambda _: Circle(timeline),
                          send=lambda *args: "receipt",
                          notify=lambda job: timeline.append("notice") or {})
        with patch("entrega.project_access_label", side_effect=lambda _, event_id: timeline.append("label") or "applied"):
            result = adapter.executar("synthetic")
        assert result["access_label_status"] == "applied"
        assert timeline == (["label", "email_confirmado", "notice"] if circle_done else
                            ["circle", "circle_confirmado", "label", "email_confirmado", "notice"])

