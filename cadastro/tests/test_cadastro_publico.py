"""Formulário público -> AmplifyOS-v5, ponta a ponta, só local.

Banco: PostgreSQL 17 descartável com o esquema do V5 + a migration nova.
Ponte TikTok: dublê no formato real, passando pelo mesmo cliente da Bia.
Nenhuma rede externa, credencial ou serviço de produção é usado.
"""
from __future__ import annotations

import json
import uuid
from datetime import date

import psycopg
import pytest

from fakes import READING_BLUR, READING_OK, FakeBridge, FakeEmail, PgGateway, answers, openai_transport, png
from local_pg import ROOT, LocalPostgres

import cadastro_pilot
from agency import AgencyChecker
from entrega import Entrega
from cadastro_server import Deps, create_app
from form import CONSENT_VERSION, VERSION, event_id
from gmv_print import GmvPrintReader, interpret, parse_brl
from store import Store

PUBLIC = "https://amplify-cadastro.up.railway.app"
RELATIONS = {"vinculada.ok": "linked", "bia.lead": "linked", "convite.pendente": "pending",
             "sem.vinculo": None, "outra.pessoa": "linked", "print.borrado": "linked"}


@pytest.fixture(scope="session")
def pg():
    server = LocalPostgres().start(ROOT / "sql" / "001_cadastro_publico_v5.sql")
    yield server
    server.stop()


def query(pg, sql, *args):
    with psycopg.connect(pg.dsn) as conn:
        return conn.execute(sql, args).fetchall()


@pytest.fixture
def env(pg, tmp_path):
    def build(reading=READING_OK, falhas=0, alertas=None, avisos=None):
        email, bridge, gateway = FakeEmail(), FakeBridge(RELATIONS), PgGateway(pg.dsn)
        circle = FakeCircle(falhas)
        deps = Deps(secret="s" * 40, public_url=PUBLIC, store=Store(tmp_path / "estado.sqlite3"), v5=gateway,
                    agency=AgencyChecker("t" * 40, transport=bridge),
                    email=email, gmv_reader=GmvPrintReader("chave-teste", "modelo-teste", transport=openai_transport(reading)),
                    entrega=Entrega(gateway, circle_token="c" * 40, settings=None, enabled=True,
                                    circle_factory=lambda token: circle, send=circle.send,
                                    notify=(lambda job: avisos.append(job) or {"notice_status": "aviso_chatwoot_enviado"}) if avisos is not None else None,
                                    alert=(lambda ev, reason: alertas.append(reason)) if alertas is not None else None))
        deps.circle = circle
        app = cadastro_pilot.create_app(base_app_factory=lambda: create_app(deps),
                                        environ={"CADASTRO_V5_PILOT_ENABLED": "true"})
        return app.test_client(), deps
    return build


API = "/onboarding/api/v2/publico/"


class FakeCircle:
    """Mesma assinatura de legado.cadastro_delivery.Circle.provision e send_welcome."""

    def __init__(self, falhas=0):
        self.provisioned, self.welcomes, self.falhas = [], [], falhas

    def provision(self, *, email, name, tier, before_write, **extra):
        self.provisioned.append((email, tier))
        if len(self.provisioned) <= self.falhas:
            raise RuntimeError("circle_leitura_ainda_nao_confirmada")
        return 123456

    def send(self, settings, job, tier):
        self.welcomes.append((job["email"], tier))
        return "<boas-vindas@amplifyugc.co>"


class Form:
    def __init__(self, client, deps):
        self.client, self.deps, self.token = client, deps, None

    def call(self, path, method="POST", json_body=None, data=None, query=""):
        headers = {"Authorization": "Bearer " + (self.token or ""), "Origin": PUBLIC}
        response = self.client.open(API + path + query, method=method, headers=headers, json=json_body, data=data,
                                    content_type=None if json_body is not None else "image/png")
        return response.status_code, response.get_json(silent=True)

    def start(self):
        status, value = self.call("sessao", json_body={"nonce": str(uuid.uuid4())})
        assert status == 200, value
        assert value["version"] == VERSION and value["revision"] == 0 and not value["submitted"]
        self.token = value["token"]
        return value

    def confirm_email(self, email):
        assert self.call("email/solicitar", json_body={"email": email})[1]["status"] == "enviado"
        code = self.deps.email.last_code(email)
        status, value = self.call("email/confirmar", json_body={"email": email, "code": code})
        assert status == 200 and value["verified"] is True, value

    def put(self, items, step):
        return self.call("respostas", "PUT", {"version": VERSION, "revision": 0, "step": step, "answers": items})

    def complete(self, tiktok, whatsapp, email):
        full = answers(tiktok, whatsapp, email)
        self.start()
        assert self.call("agenciamento", json_body={"tiktok": "@" + tiktok}) == (200, {"status": "aprovada"})
        self.confirm_email(email)
        first = {k: full[k] for k in ("nome", "email", "whatsapp", "tiktok")}
        assert self.put(first, 0)[0] == 200
        status, value = self.call("validacao-inicial", json_body=first)
        if status != 200:
            return status, value
        for field, color in (("foto_perfil", (200, 30, 90)), ("print_gmv", (30, 200, 90))):
            status, receipt = self.call("anexos", data=png(color), query="?campo=" + field)
            assert status == 200, receipt
            full[field] = receipt
        assert self.put(full, 3)[0] == 200
        return self.call("respostas", "POST", {"version": VERSION, "revision": 0, "step": 5, "answers": full,
                                               "consent": {"accepted": True, "version": CONSENT_VERSION}})


def test_vinculado_passa_e_grava_tudo_no_banco_novo(env, pg):
    client, deps = env()
    form = Form(client, deps)
    status, value = form.complete("vinculada.ok", "47999990001", "vinculada@example.com")
    assert status == 200 and value["submitted"] is True and value["outcome"]["status"] == "entrega_em_andamento", value
    (creator,) = query(pg, "select id,nome,email,whatsapp,tiktok,cadastro_situacao,formulario_situacao,cpf,endereco_cidade,"
                           "endereco_estado,cnpj,possui_cnpj,pets,nichos,calcado,meta_renda_mensal,foto_perfil_referencia,"
                           "canal_entrada,gmv_entrada_id,email_confirmado_em is not null from interno.creators where tiktok='vinculada.ok'")
    assert creator[1:7] == ("Teste Local", "vinculada@example.com", "5547999990001", "vinculada.ok", "confirmado",
                            "recebido_formulario_publico")
    assert creator[7:13] == ("52998224725", "Joinville", "Santa Catarina", "11222333000181", True, "Gato")
    assert creator[13] == ["Beleza"] and float(creator[14]) == 37 and float(creator[15]) == 5000
    assert creator[16].startswith("publico/") and creator[17] == "formulario_publico" and creator[19] is True
    agency = query(pg, "select fonte,situacao,tiktok_observado,conta_referencia from interno.agenciamentos where creator_id=%s", creator[0])
    assert agency == [("tiktok_partner_center", "confirmado", "@vinculada.ok", "formulario_publico")]
    gmv = query(pg, "select id,natureza,periodicidade,periodo_inicio,periodo_fim,valor,situacao,fonte,comprovante_referencia "
                    "from interno.gmv where creator_id=%s order by id", creator[0])
    (declared,) = gmv  # o banco aceita uma linha de entrada por natureza
    assert creator[18] is None  # gmv_entrada_id só aponta para GMV verificado
    assert declared[1:5] == ("declarado", "nao_informado", None, None) and declared[6] == "registrado"
    assert float(declared[5]) == 15000.50 and declared[7].startswith("formulario_publico:")
    assert declared[8].startswith("publico/") and "/print_gmv/" in declared[8]
    ((gmv_id, reading),) = query(pg, "select gmv_id,dados from interno.eventos where creator_id=%s and tipo='gmv_atualizado' "
                                     "and instancia='formulario_publico'", creator[0])
    assert gmv_id == declared[0] and reading["origem"] == "leitura_print_gmv" and reading["natureza"] == "declarado"
    assert reading["situacao"] == "lido" and reading["valor"] == "12345.67" and reading["moeda"] == "BRL"
    assert (reading["periodicidade"], reading["periodo_inicio"], reading["periodo_fim"]) == ("janela_28_dias", "2026-10-02", "2026-10-29")
    assert reading["leitor"] == "openai:modelo-teste" and reading["diverge_do_digitado"] is True
    assert not query(pg, "select 1 from interno.gmv where creator_id=%s and natureza='verificado'", creator[0])
    (event,) = query(pg, "select tipo,instancia,atendimento_id,dados from interno.eventos where creator_id=%s "
                         "and tipo='cadastro_confirmado'", creator[0])
    assert event[:3] == ("cadastro_confirmado", "formulario_publico", None)
    assert event[3]["leitura_print"]["situacao"] == "lido" and event[3]["vinculo"]["relation_id"] == "7300000000000000001"
    # Mesmo envio de novo: recibo guardado, nada duplicado.
    again = form.call("respostas", "POST", {"version": VERSION, "revision": 0, "step": 5, "answers": {},
                                            "consent": {"accepted": True, "version": CONSENT_VERSION}})
    assert again[0] == 200 and again[1]["submitted"] is True
    # Acesso no Circle: categoria pelo valor lido do print (12.345,67 → Silver); e-mail de boas-vindas.
    for thread in deps.entrega.threads.values():
        thread.join(timeout=10)
    assert deps.circle.provisioned == [("vinculada@example.com", "Silver")] and deps.circle.welcomes == [("vinculada@example.com", "Silver")]
    assert query(pg, "select circle_situacao,circle_categoria_entrada,acesso_referencia from interno.creators where id=%s",
                 creator[0]) == [("acessos_liberados", "Silver", "circle:123456")]
    assert [r[0] for r in query(pg, "select tipo from interno.eventos where creator_id=%s and instancia='formulario_publico' "
                                     "order by revisao", creator[0])] == ["cadastro_confirmado", "gmv_atualizado", "acesso_solicitado",
                                                                        "acesso_entregue", "email_aceito_provedor"]
    outcome = form.call("contexto", "GET")[1]["outcome"]
    assert outcome["status"] == "acessos_liberados" and outcome["access"]["category"] == "Silver"
    assert query(pg, "select count(*) from interno.eventos where tipo='cadastro_confirmado' and creator_id=%s", creator[0]) == [(1,)]
    assert form.call("contexto", "GET")[1]["submitted"] is True


def test_nao_vinculado_nao_passa_da_primeira_etapa(env, pg):
    client, deps = env()
    form = Form(client, deps)
    form.start()
    status, value = form.call("agenciamento", json_body={"tiktok": "@sem.vinculo"})
    assert status == 409 and "Não encontramos vínculo" in value["erro"]
    # Nem pulando a checagem: as respostas com esse @ são conferidas ao vivo de novo.
    status, value = form.put({"tiktok": "sem.vinculo"}, 0)
    assert status == 409
    assert query(pg, "select count(*) from interno.creators where tiktok='sem.vinculo'") == [(0,)]


def test_convite_pendente_recebe_orientacao_para_aceitar(env):
    client, deps = env()
    form = Form(client, deps)
    form.start()
    status, value = form.call("agenciamento", json_body={"tiktok": "convite.pendente"})
    assert status == 409 and "aceite o convite da Amplify" in value["erro"] and "Parcerias" in value["erro"]


def test_lead_da_bia_cai_na_mesma_ficha(env, pg):
    creator, attendance = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(pg.dsn) as conn:
        conn.execute("select set_config('app.v5_explicit_event','on',false)")
        conn.execute("insert into interno.creators(id,whatsapp,origem_instancia,origem_account_id,origem_contact_id,"
                     "canal_entrada,etapa_atual,situacao_atual) values(%s,'554788880002','bia','1','42','whatsapp','form','em_atendimento')",
                     (creator,))
        conn.execute("insert into interno.atendimentos(id,creator_id,instancia,account_id,contact_id,conversation_id,revisao,"
                     "etapa,situacao,qualificacao,rascunho,marcos,mensagens_recebidas,criado_em,atualizado_em) "
                     "values(%s,%s,'bia','1','42','77',1,'form','aberto','{}','{}','{}',3,now(),now())", (attendance, creator))
    client, deps = env()
    status, value = Form(client, deps).complete("bia.lead", "47988880002", "bialead@example.com")
    assert status == 200 and value["submitted"] is True, value
    # A Bia gravou o WhatsApp SEM o 9º dígito; o formulário recebe COM ele: tem que cair na mesma ficha.
    rows = query(pg, "select id::text,tiktok,cadastro_situacao,canal_entrada from interno.creators where id=%s or tiktok='bia.lead'", creator)
    assert rows == [(creator, "bia.lead", "confirmado", "whatsapp")]
    linked = query(pg, "select atendimento_id::text from interno.eventos where creator_id=%s and tipo='cadastro_confirmado'", creator)
    assert linked == [(attendance,)]
    assert query(pg, "select atendimento_id::text from interno.gmv where creator_id=%s", creator)[0] == (attendance,)
    # O cadastro conclui o atendimento da Bia.
    assert query(pg, "select situacao,motivo_encerramento from interno.atendimentos where id=%s", attendance) == [("encerrado", "cadastro_confirmado")]


def test_mesmo_arroba_com_outro_whatsapp_vai_para_conferencia(env, pg):
    client, deps = env()
    assert Form(client, deps).complete("outra.pessoa", "47977770003", "dona@example.com")[0] == 200
    client, deps = env()
    status, value = Form(client, deps).complete("outra.pessoa", "47966660004", "intrusa@example.com")
    assert status == 409 and "já está ligado a outro WhatsApp" in value["erro"], value
    assert query(pg, "select count(*) from interno.creators where tiktok='outra.pessoa'") == [(1,)]


def test_print_ilegivel_fica_indisponivel_e_nunca_zero(env, pg):
    client, deps = env(READING_BLUR)
    status, value = Form(client, deps).complete("print.borrado", "47955550005", "borrado@example.com")
    assert status == 200, value
    (cid,) = query(pg, "select id from interno.creators where tiktok='print.borrado'")[0]
    gmv = query(pg, "select valor,periodicidade from interno.gmv where creator_id=%s", cid)
    assert gmv == [(gmv[0][0], "nao_informado")] and float(gmv[0][0]) == 15000.50
    ((entry,),) = query(pg, "select dados from interno.eventos where creator_id=%s and tipo='gmv_atualizado'", cid)
    assert entry["situacao"] == "indisponivel" and entry["valor"] is None and entry["diverge_do_digitado"] is None
    assert entry["motivo"] == "gmv_nao_encontrado"


def test_link_da_bia_continua_funcionando(env):
    client, _deps = env()
    response = client.get("/cadastro/ensaio")
    assert response.status_code == 200 and b"amplify-v5-pilot" in response.data
    page = client.get("/cadastro")
    assert page.status_code == 200 and b"const publicMode=location.pathname" in page.data
    assert client.get("/formulario").status_code == 302
    assert client.post("/onboarding/api/v2/respostas").status_code == 410


def test_banco_recusa_prova_pendente_e_contexto_adulterado(pg):
    gateway = PgGateway(pg.dsn)
    form_id = str(uuid.uuid4())
    from form import build_payload
    from datetime import datetime, timezone
    received = datetime.now(timezone.utc)
    full = answers("adulterado", "47944440006", "adulterado@example.com")
    attachments = {f: {"reference": f"publico/{form_id}/{f}/{'a' * 64}.jpg", "source": "upload_validado", "receipt_sha256": "b" * 64}
                   for f in ("foto_perfil", "print_gmv")}
    full.update({f: {"receipt": "x"} for f in attachments})
    payload = build_payload(full, attachments, received)
    at = received.isoformat(timespec="microseconds").replace("+00:00", "Z")
    import hashlib
    context = {"event_id": event_id(form_id), "form_instance_id": form_id, "received_at": at,
               "source": {"kind": "formulario_publico", "reference": "formulario-publico:" + form_id},
               "attachments": attachments,
               "email_confirmation": {"at": at, "source": "email_token_validado", "reference": "t",
                                      "email_sha256": hashlib.sha256(b"adulterado@example.com").hexdigest()},
               "relationship": {"operation": "relationship", "creator": "@adulterado", "observed_at": at, "status": "pending",
                                "confirmed": True, "job_id": "j1", "evidence": {}},
               "gmv_print": {"situacao": "indisponivel", "valor": None, "moeda": None, "periodo_inicio": None,
                             "periodo_fim": None, "leitor": "openai:x", "lido_em": at, "motivo": "leitor_falhou"}}
    def code(ctx):
        try:
            gateway.rpc("registrar_cadastro_publico_v5", {"p_payload": payload, "p_context": ctx})
        except Exception as error:
            return error.code
    assert code(context) == "cadastro_publico_vinculo_obrigatorio"
    linked = {**context, "relationship": {**context["relationship"], "status": "linked", "evidence": {
        "relation_id": "1", "status": "vinculado", "tiktok_status": 1, "source": "partner_relations", "fresh": True, "complete": True}}}
    assert code({**linked, "relationship": {**linked["relationship"], "creator": "@outro"}}) == "cadastro_publico_vinculo_obrigatorio"
    assert code({**linked, "event_id": str(uuid.uuid4())}) == "cadastro_publico_evento_nao_corresponde_ao_formulario"
    assert code({**linked, "gmv_print": {**linked["gmv_print"], "valor": "0"}}) == "cadastro_publico_leitura_print_invalida"
    assert code({**linked, "email_confirmation": {**linked["email_confirmation"], "email_sha256": "0" * 64}}) == "cadastro_publico_email_nao_confirmado"
    assert query(pg, "select count(*) from interno.creators where tiktok='adulterado'") == [(0,)]
    with psycopg.connect(pg.dsn) as conn:  # anon/authenticated não executam as funções novas
        conn.execute("set role anon")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select public.consultar_cadastro_publico_v5('a1','5547999999999','a@b.co')")


@pytest.mark.parametrize("text,expected", [("R$ 12.345,67", "12345.67"), ("R$1,2 mil", "1200.00"), ("12,3K", "12300.00"),
                                           ("R$ 0,00", "0.00"), ("1.234", "1234.00"), ("R$ 2,5 mi", "2500000.00"),
                                           ("1,234.56", None), ("abc", None)])
def test_leitura_de_valor_em_reais(text, expected):
    value = parse_brl(text)
    assert (format(value, "f") if value is not None else None) == expected


def test_interpretacao_do_print_sem_ano_e_sem_periodo():
    today = date(2026, 10, 30)
    reading = {**READING_OK, "inicio_ano": None, "fim_ano": None}
    result = interpret(reading, today)
    assert result["periodo_inicio"] == "2026-10-02" and result["periodo_fim"] == "2026-10-29"
    no_dates = interpret({**READING_OK, "inicio_dia": None, "fim_dia": None}, today)
    assert no_dates["situacao"] == "lido" and no_dates["periodo_inicio"] is None
    assert interpret({**READING_OK, "e_print_tiktok_shop": False}, today)["motivo"] == "imagem_nao_e_print_gmv"
    assert GmvPrintReader("", "").read(b"x")["motivo"] == "leitor_nao_configurado"


@pytest.mark.parametrize("job,lido,esperado", [
    ({"gmv_declarado": 150000}, "600.00", "Start"),        # vale o que o bot leu, não o digitado
    ({"gmv_declarado": 600}, "45000.00", "Gold"),          # print maior que o digitado: vale o print
    ({"gmv_declarado": 120000}, None, "Diamond"),          # print ilegível: vale o digitado
    ({"gmv_declarado": None}, None, "Start"),              # sem nada: Start
    ({"gmv_verificado": 4000, "gmv_declarado": 150000}, "150000.00", "Start"),  # verificado manda
])
def test_categoria_pelo_bot_do_print(job, lido, esperado):
    from entrega import categoria
    assert categoria(job, lido) == esperado


def envelhecer_tentativas(pg, tiktok):
    """Só no banco local: simula que a última tentativa foi há mais de 10 minutos."""
    with psycopg.connect(pg.dsn) as conn:
        conn.execute("alter table interno.eventos disable trigger user")
        conn.execute("update interno.eventos set registrado_em=registrado_em-interval '11 minutes' where tipo='acesso_solicitado' "
                     "and creator_id=(select id from interno.creators where tiktok=%s)", (tiktok,))
        conn.execute("alter table interno.eventos enable trigger user")


def esperar(deps):
    for thread in list(deps.entrega.threads.values()):
        thread.join(timeout=10)


def test_entrega_que_falhou_e_retomada_sozinha(env, pg):
    RELATIONS["retomada.ok"] = "linked"
    avisos = []
    client, deps = env(falhas=1, avisos=avisos)
    status, value = Form(client, deps).complete("retomada.ok", "47933330007", "retomada@example.com")
    assert status == 200, value
    esperar(deps)
    assert deps.circle.welcomes == []  # 1ª tentativa falhou no Circle: nada de boas-vindas
    assert deps.entrega.retomar_pendentes() == [{"status": "entrega_ja_iniciada"}]  # espera 10 min
    envelhecer_tentativas(pg, "retomada.ok")
    resultado = deps.entrega.retomar_pendentes()
    assert resultado[0]["status"] == "acessos_liberados" and resultado[0]["notice_status"] == "aviso_chatwoot_enviado"
    assert deps.circle.welcomes == [("retomada@example.com", "Silver")]
    assert deps.entrega.retomar_pendentes() == []  # concluída: some da lista de pendentes
    tipos = [r[0] for r in query(pg, "select tipo||':'||revisao from interno.eventos e join interno.creators c on c.id=e.creator_id "
                                     "where c.tiktok='retomada.ok' and e.instancia='formulario_publico' order by revisao")]
    assert tipos == ["cadastro_confirmado:0", "gmv_atualizado:1", "acesso_solicitado:2", "acesso_entregue:3",
                     "email_aceito_provedor:4", "email_falha:5", "acesso_solicitado:102"]
    assert query(pg, "select circle_situacao from interno.creators where tiktok='retomada.ok'") == [("acessos_liberados",)]


def test_tres_falhas_param_e_avisam_a_equipe(env, pg):
    RELATIONS["sempre.falha"] = "linked"
    alertas = []
    client, deps = env(falhas=99, alertas=alertas)
    assert Form(client, deps).complete("sempre.falha", "47922220008", "falha@example.com")[0] == 200
    esperar(deps)
    for _ in range(2):
        envelhecer_tentativas(pg, "sempre.falha")
        assert deps.entrega.retomar_pendentes()[0]["status"] == "revisao_manual"
    assert alertas == ["circle_leitura_ainda_nao_confirmada"]  # alerta só na 3ª
    envelhecer_tentativas(pg, "sempre.falha")
    assert deps.entrega.retomar_pendentes() == [{"status": "tentativas_esgotadas"}]
    assert len(deps.circle.provisioned) == 3


def test_aviso_whatsapp_vai_para_a_conversa_do_lead_da_bia(env, pg):
    RELATIONS["bia.aviso"] = "linked"
    creator, attendance = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(pg.dsn) as conn:
        conn.execute("select set_config('app.v5_explicit_event','on',false)")
        conn.execute("insert into interno.creators(id,whatsapp,origem_instancia,origem_account_id,origem_contact_id,"
                     "canal_entrada,etapa_atual,situacao_atual) values(%s,'554777770009','bia','1','43','whatsapp','form','em_atendimento')",
                     (creator,))
        conn.execute("insert into interno.atendimentos(id,creator_id,instancia,account_id,contact_id,conversation_id,revisao,"
                     "etapa,situacao,qualificacao,rascunho,marcos,mensagens_recebidas,criado_em,atualizado_em) "
                     "values(%s,%s,'bia','1','43','88',1,'form','aberto','{}','{}','{}',3,now(),now())", (attendance, creator))
    avisos = []
    client, deps = env(avisos=avisos)
    assert Form(client, deps).complete("bia.aviso", "47977770009", "aviso@example.com")[0] == 200
    esperar(deps)
    assert [a["conversation_id"] for a in avisos] == ["88"]


def test_conversa_da_bia_alimenta_a_ficha(pg):
    creator, attendance = str(uuid.uuid4()), str(uuid.uuid4())
    qual = {"origem_declarada": "anuncio", "tiktok_declarado": "@ficha.teste", "interesse_agenciamento": True,
            "consentimento_convite": True, "verificacoes_tiktok": {
                "precheck": {"status": "eligible", "confirmed": True, "observed_at": "2026-10-30T20:27:45.120708Z"},
                "invite": {"status": "sent", "confirmed": True, "observed_at": "2026-10-30T20:33:39.720037Z",
                           "evidence": {"relation_id": "8687510033319298834"}}}}
    origem = {"at": "2026-10-30T20:27:14Z", "value": "anuncio", "source": "declaracao_pessoa", "reference": "chatwoot:1:999"}
    with psycopg.connect(pg.dsn) as conn:
        conn.execute("select set_config('app.v5_explicit_event','on',false)")
        conn.execute("insert into interno.creators(id,whatsapp,origem_instancia,origem_account_id,origem_contact_id,"
                     "canal_entrada,etapa_atual,situacao_atual) values(%s,'554766660010','bia','1','44','whatsapp','form','em_atendimento')",
                     (creator,))
        conn.execute("insert into interno.atendimentos(id,creator_id,instancia,account_id,contact_id,conversation_id,revisao,"
                     "etapa,situacao,qualificacao,rascunho,marcos,mensagens_recebidas,origem,criado_em,atualizado_em) "
                     "values(%s,%s,'bia','1','44','99',1,'form','aberto',%s,'{}','{}',3,%s,now(),now())",
                     (attendance, creator, json.dumps(qual), json.dumps(origem)))
    row = query(pg, "select tiktok,origem_entrada,origem_fonte,interesse_agenciamento,quer_convite,validacao_situacao,"
                    "validacao_confirmada_em is not null,convite_situacao,convite_enviado_em is not null,convite_referencia,"
                    "pendencia_atual is not null from interno.creators where id=%s", creator)
    assert row == [(None, "anuncio", "declaracao_pessoa", True, True, "elegivel", True, "enviado", True,
                    "8687510033319298834", True)]
    # Vínculo confirmado depois: a ficha passa a "aceito".
    qual["verificacoes_tiktok"]["relationship"] = {"status": "linked", "confirmed": True, "observed_at": "2026-10-30T21:00:00Z"}
    with psycopg.connect(pg.dsn) as conn:
        conn.execute("update interno.atendimentos set qualificacao=%s where id=%s", (json.dumps(qual), attendance))
    assert query(pg, "select convite_situacao, convite_aceito_em is not null from interno.creators where id=%s", creator) == [("aceito", True)]


def test_vigia_avisa_quando_a_ponte_pede_login_e_quando_volta():
    from vigia_ponte import VigiaPonte
    respostas = iter(["ready", "human_login_required", "human_login_required", "human_login_required", "busy", "ready", "ready"])
    alertas = []
    vigia = VigiaPonte("t" * 40, lambda assunto, texto, **visual: alertas.append((assunto, visual.get("botao"))),
                       nome="Pré-validação", painel="https://cadastro/operacao", ler=lambda token: {"status": next(respostas)})
    resultados = [vigia.checar(agora=1000 + 300 * i) for i in range(7)]
    assert resultados == ["ok", "caida", "alertado", "caida", "instavel", "ok", "ok"]
    assert alertas[0][0].startswith("🔴 Ponte do TikTok (Pré-validação) pediu login")
    assert alertas[0][1] == ("Abrir painel de login", "https://cadastro/operacao")
    assert alertas[1][0].startswith("✅ Ponte do TikTok (Pré-validação) de volta") and len(alertas) == 2


def test_circle_nao_manda_o_proprio_convite():
    from entrega import CircleComCache
    enviados = []

    class Sessao:
        def request(self, method, url, json=None, timeout=None):
            enviados.append((method, url, json))
            class R:
                ok, status_code, content = True, 200, b"{}"
                def json(self):
                    return {}
            return R()
    circle = CircleComCache("c" * 32)
    circle.session = Sessao()
    circle.call("/community_members", "POST", {"email": "a@b.co", "name": "A", "skip_invitation": False, "member_tag_ids": [1]})
    circle.call("/access_groups/1/community_members", "POST", {"email": "a@b.co"})
    assert enviados[0][2]["skip_invitation"] is True and "skip_invitation" not in enviados[1][2]


def test_banco_lista_atendimento_travado_ha_mais_de_30_min(pg):
    from fakes import PgGateway
    creator, parado, recente = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(pg.dsn) as conn:
        conn.execute("select set_config('app.v5_explicit_event','on',false)")
        conn.execute("insert into interno.creators(id,whatsapp,tiktok,nome,origem_instancia,origem_account_id,origem_contact_id,"
                     "canal_entrada,etapa_atual,situacao_atual) values(%s,'554766660020','emy.teste','Emy','bia','1','45',"
                     "'whatsapp','blocked','em_atendimento')", (creator,))
        conn.execute("alter table interno.atendimentos disable trigger v5_10_datas")  # simula idade (só no banco local)
        for ident, conversa, idade in ((parado, "56747", "2 hours"), (recente, "56748", "5 minutes")):
            conn.execute("insert into interno.atendimentos(id,creator_id,instancia,account_id,contact_id,conversation_id,revisao,"
                         "etapa,situacao,qualificacao,rascunho,marcos,mensagens_recebidas,origem,criado_em,atualizado_em) "
                         "values(%s,%s,'bia','1','45',%s,1,'blocked','aberto','{}','{}','{}',3,'{}',now()-%s::interval,now()-%s::interval)",
                         (ident, creator, conversa, idade, idade))
        conn.execute("alter table interno.atendimentos enable trigger v5_10_datas")
    lista = PgGateway(pg.dsn).rpc("listar_atendimentos_parados_v5", {"p_minutos": 30})
    assert [(a["conversa"], a["tiktok"], a["nome"]) for a in lista] == [("56747", "emy.teste", "Emy")]


def test_vigia_so_avisa_erro_da_maquina_e_nao_repete_depois_de_reiniciar(tmp_path):
    from vigia_atendimento import VigiaAtendimento

    class ChatwootFalso:
        sem = [{"conversa": 56752, "desde": 1000}]
        def sem_resposta(self, agora): return list(self.sem)
        def link(self, c): return f"https://chat/{c}"

    alertas, arquivo = [], str(tmp_path / "vigia.json")
    bia = iter([(True, ""), (False, "x"), (False, "x"), (True, "")])
    cw = ChatwootFalso()
    vigia = VigiaAtendimento(lambda assunto, texto, **v: alertas.append((assunto, texto, v.get("selo"))), chatwoot=cw,
                             bia=lambda: next(bia), arquivo=arquivo)
    assert vigia.checar(agora=5000) == [("sem_resposta", 1)]
    assert alertas[0][0].startswith("🔴 Erro da Bia") and "https://chat/56752" in alertas[0][1] and alertas[0][2] == "ERRO DA MÁQUINA"
    # o serviço reinicia: o mesmo lead não gera outro e-mail
    vigia = VigiaAtendimento(lambda assunto, texto, **v: alertas.append((assunto, texto, v.get("selo"))), chatwoot=cw,
                             bia=lambda: next(bia), arquivo=arquivo)
    assert vigia.checar(agora=5600) == []
    cw.sem = []                                                # a Bia respondeu
    assert vigia.checar(agora=6200) == ["bia_fora"]            # 2ª leitura ruim da Bia
    assert vigia.checar(agora=6800) == ["bia_voltou"]
    cw.sem = [{"conversa": 56752, "desde": 6900}]              # ficou sem resposta de novo: avisa de novo
    vigia.bia = lambda: (True, "")
    assert vigia.checar(agora=9000) == [("sem_resposta", 1)]


def test_chatwoot_ignora_conversa_com_atendente(monkeypatch):
    import vigia_atendimento as va
    pagina = {"data": {"payload": [
        {"id": 1, "meta": {"assignee": {"name": "Ana"}}, "last_activity_at": 9000,
         "last_non_activity_message": {"message_type": 0, "created_at": 5000}},
        {"id": 2, "meta": {}, "last_activity_at": 9000,
         "last_non_activity_message": {"message_type": 0, "created_at": 5000}}]}}
    monkeypatch.setattr(va, "_get", lambda url, headers=None, timeout=30: pagina if "page=1" in url else {"data": {"payload": []}})
    assert [c["conversa"] for c in va.Chatwoot("https://c", "1", "t").sem_resposta(9000)] == [2]


def test_etiqueta_localiza_conversa_exata_de_acesso_confirmado(pg):
    creator, matched, newer, event = (str(uuid.uuid4()) for _ in range(4))
    with psycopg.connect(pg.dsn) as conn:
        conn.execute("select set_config('app.v5_explicit_event','on',false)")
        conn.execute("insert into interno.creators(id,whatsapp,origem_instancia,origem_account_id,origem_contact_id,"
                     "canal_entrada,etapa_atual,situacao_atual) values(%s,'554766660129',"
                     "'chatwoot-amplify-prod','1','40129','whatsapp','form','em_atendimento')", (creator,))
        for attendance, conversation, offset in ((matched, "40129", 2), (newer, "40130", 1)):
            conn.execute("insert into interno.atendimentos(id,creator_id,instancia,account_id,contact_id,conversation_id,"
                         "revisao,etapa,situacao,qualificacao,rascunho,marcos,mensagens_recebidas,criado_em,atualizado_em) "
                         "values(%s,%s,'chatwoot-amplify-prod','1','40129',%s,1,'form','encerrado','{}','{}','{}',3,"
                         "now()-make_interval(mins=>%s),now()-make_interval(mins=>%s))",
                         (attendance, creator, conversation, offset, offset))
        assert conn.execute("select has_function_privilege('anon',"
                            "'public.destino_etiqueta_acesso_circle_v5(uuid)','EXECUTE'),"
                            "has_function_privilege('authenticated',"
                            "'public.destino_etiqueta_acesso_circle_v5(uuid)','EXECUTE')").fetchone() == (False, False)
        conn.execute("set local role service_role")
        assert conn.execute("select public.destino_etiqueta_acesso_circle_v5(%s::uuid)", (event,)).fetchone() == ({},)
        conn.execute("reset role")
        conn.execute("insert into interno.eventos(creator_id,atendimento_id,tipo,instancia,referencia,"
                     "revisao,ocorrido_em,dados) values(%s,%s,'acesso_entregue','formulario_publico',%s,3,now(),"
                     "'{\"circle_member_id\":123456,\"categoria\":\"Start\"}')", (creator, matched, event))
        conn.execute("set local role service_role")
        assert conn.execute("select public.destino_etiqueta_acesso_circle_v5(%s::uuid)", (event,)).fetchone() == (
            {"conversation_id": "40129", "account_id": "1"},
        )
        conn.rollback()
