"""Bounded, deterministic demo retrieval. Never trims cards or changes a version.

Retrieval is not semantic validation. Safety depends on complete source cards,
mandatory global rules, conservative topic bundles and the answer verifier.
New independently stored exceptions should reference the affected card ID or
use its ID as a prefix; visibly labelled exceptions are always retained.
"""
from copy import deepcopy
import json
import re
import unicodedata
from demo_flow import safe_context_text

MAX_CATALOG_CARDS = 256
MAX_CATALOG_CHARS = 240000
MAX_CONTEXT_CHARS = 48000  # Serialized selected context, including editorial rules.
MAX_SOURCE_CHARS = 40128  # Full evidence quotes, compatible with the evidence catalog.
MAX_SELECTED_TOPICS = 62


def _plain(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                   if not unicodedata.combining(c))


STOP = set('a as o os e ou de da do das dos em na no nas nos um uma uns umas '
           'para por com sem que qual quais como quando onde quanto quantos quais '
           'eu me meu minha meus minhas voce voces ele ela isso isto esse essa '
           'esses essas aquele aquela sim nao se ja ser sou sao e esta estar '
           'tem tenho ter posso pode podem preciso quero saber sobre mais muito '
           'tambem agora antes depois pelo pela ao aos pra pro porque algo coisa '
           'amplify tiktok shop creator creators'.split())

# Routing vocabulary only: no commercial claims. Multiple matches are unioned.
BUNDLES = (
    (('beneficio', 'vantagem', 'ganho', 'oferece', 'oferecem', 'agencia', 'agenciamento', 'conhecer'),
     ('amplify', 'beneficios', 'amplify_doc_offer', 'amplify_doc_club_spaces',
      'amplify_doc_categories', 'amplify_doc_monthly_journey', 'amplify_doc_programs', 'garantias')),
    (('categoria', 'faixa', 'nivel', 'start', 'silver', 'gold', 'diamond', 'safira', 'royal',
      'gmv', 'blue carpet', 'subir', 'rebaixamento', 'protecao', 'quinzenal', 'semanal',
      'individual', 'account manager'),
     ('amplify_doc_categories', 'amplify_doc_monthly_journey', 'amplify_doc_programs',
      'comunidade', 'garantias')),
    (('amostra', 'reembolso', 'reembolsavel', 'receber produto', 'recebo produto', 'marca',
      'vitrine', 'caixa', 'brinde'),
     ('amplify_doc_sample_types', 'amplify_doc_sample_approval', 'amplify_doc_sample_process', 'garantias')),
    (('sair', 'saida', 'deixar', 'cancelar', 'cancelamento', 'desligar', 'desvincular',
      'permanencia', 'burocracia', 'multa', 'encerrar', 'rescisao', 'parceria', 'vinculo'),
     ('funcionamento', 'custos', 'ja_tem_agencia')),
    (('custo', 'taxa', 'mensalidade', 'comissao', 'comissoes', 'porcentagem', 'percentual',
      'pago', 'pagar', 'custa', 'cobram', 'cobranca', 'super afiliado', 'indicacao', 'remuneracao',
      'mentoria', 'squad elite'),
     ('custos', 'funcionamento', 'amplify_doc_programs', 'amplify_doc_categories',
      'amplify_doc_monthly_journey', 'garantias')),
    (('live', 'lives', 'ao vivo', 'obrigatorio', 'obrigada', 'obrigado'),
     ('lives', 'funcionamento', 'garantias')),
    (('club', 'circle', 'comunidade', 'treinamento', 'curso', 'aula', 'espaco', 'acesso'),
     ('comunidade', 'cadastro_acessos', 'amplify_doc_club_spaces', 'amplify_doc_categories',
      'amplify_doc_monthly_journey', 'amplify_doc_programs', 'garantias')),
    (('violacao', 'violacoes', 'punicao', 'punicoes', 'saude da conta', 'recurso', 'recorrer',
      'penalidade', 'apagar video', 'pre verificacao'),
     ('amplify_doc_account_health', 'garantias')),
    (('convite', 'aceite', 'aceitei', 'aceitar'), ('convite_tiktok', 'funcionamento', 'custos')),
    (('cadastro', 'formulario', 'email', 'codigo', 'senha', 'entrar'),
     ('cadastro_acessos', 'funcionamento', 'comunidade')),
    (('requisito', 'seguidor', 'seguidores', 'perfil', 'arroba', 'ativar', 'ativo'),
     ('requisitos', 'perfil_tiktok', 'ativar_shop', 'ja_tem_agencia')),
    (('garantia', 'resultado', 'renda', 'venda', 'vendas', 'lucro', 'crescimento'),
     ('garantias', 'amplify_doc_offer', 'custos', 'amplify_doc_monthly_journey')),
)


def _contains(text, phrase):
    # Permit common Portuguese plurals, never substring matches inside words.
    return bool(re.search(r'(?<!\w)' + re.escape(phrase) + r'(?:s|es)?(?!\w)', text))


def _tokens(text):
    return {token for token in re.findall(r'[a-z0-9]+', _plain(text))
            if len(token) >= 3 and token not in STOP}


def _validate(knowledge):
    if not isinstance(knowledge, dict) or knowledge.get('source') != 'database':
        raise ValueError('demo_selection_invalid')
    topics = knowledge.get('topics')
    if (not isinstance(topics, list) or not 1 <= len(topics) <= MAX_CATALOG_CARDS - 2
            or not isinstance(knowledge.get('knowledge_version'), str)
            or not 1 <= len(knowledge['knowledge_version']) <= 100):
        raise ValueError('demo_selection_invalid')
    total, ids = 0, set()
    for key in ('personality', 'limits'):
        value = knowledge.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError('demo_selection_invalid')
        total += len(value)
    for topic in topics:
        if not isinstance(topic, dict):
            raise ValueError('demo_selection_invalid')
        identifier, title, answer = topic.get('id'), topic.get('title', topic.get('id')), topic.get('answer')
        patterns = topic.get('patterns', [])
        if (not isinstance(identifier, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', identifier)
                or identifier == 'limits' or identifier in ids
                or not isinstance(title, str) or not 1 <= len(title) <= 120
                or not isinstance(answer, str) or not 1 <= len(answer) <= 8000
                or not isinstance(patterns, list) or len(patterns) > 32
                or any(not isinstance(p, str) or len(p) > 120 for p in patterns)):
            raise ValueError('demo_selection_invalid')
        total += len(title) + len(answer)
        ids.add(identifier)
    # Joined editorial cards introduce at most 508 separator characters.
    if total > MAX_CATALOG_CHARS + 508:
        raise ValueError('demo_selection_catalog_too_large')
    return {topic['id']: topic for topic in topics}


def _matches(text, topics):
    text = _plain(text)
    selected = set()
    for aliases, identifiers in BUNDLES:
        if any(_contains(text, alias) for alias in aliases):
            selected.update(set(identifiers) & topics.keys())
    words = _tokens(text)
    for identifier, topic in topics.items():
        metadata = topic.get('title', identifier) + ' ' + identifier.replace('_', ' ')
        if (words & _tokens(metadata)
                or any(_contains(text, _plain(p)) for p in topic.get('patterns', []) if p.strip())):
            selected.add(identifier)
    # Content search covers unfamiliar terminology without letting generic words
    # pull every card. Every matching card is kept, never a top-k partial bundle.
    if words:
        content_words = {key: _tokens(topic['answer']) for key, topic in topics.items()}
        rare = {word for word in words if sum(word in v for v in content_words.values()) <= 4}
        selected.update(key for key, tokens in content_words.items() if rare & tokens)
    return selected


QUALIFIERS = re.compile(r'\b(?:condicoes|condicao|ressalvas?|excecoes|excecao|restricoes|restricao|limites?|elegibilidade)\b')
REFERENCE = re.compile(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b')


def select_demo_knowledge(knowledge, question, dialogue=None):
    """Return an isolated whole-source snapshot or raise ValueError, never truncate.

    The original catalog hash remains the turn identity. A selection describes a
    view of that catalog, not a newly approved knowledge version. Only explicit
    short follow-up references and answers to an explicit pending clarification use
    bounded prior questions, not prior answers (which can contain errors). No external IO or model calls.
    """
    topics = _validate(knowledge)
    if not isinstance(question, str) or not 1 <= len(question) <= 500:
        raise ValueError('demo_selection_question_invalid')
    # Tiny catalogs need no retrieval: retaining all sources is safest and keeps
    # the established injected-loader contract. Still enforce every prompt cap.
    if len(topics) <= 8:
        result = deepcopy(knowledge)
        if (len(result['limits']) + sum(len(t['answer']) for t in topics.values()) > MAX_SOURCE_CHARS
                or len(json.dumps(result, ensure_ascii=False, sort_keys=True)) > MAX_CONTEXT_CHARS):
            raise ValueError('demo_selection_budget_exceeded')
        return result
    selected = _matches(question, topics)
    # History cannot override a complete new question. Only referential, short
    # questions can carry forward the previous question's topics.
    plain = _plain(question)
    referential = bool(re.search(r'\b(?:isso|isto|nesse caso|neste caso|essa|esse|esses|essas|eles|elas|disso|deles|delas|e quanto|e se)\b', plain))
    used_history = False
    if isinstance(dialogue, dict):
        # The answerer passes redacted fields, but enforce the same boundary for
        # direct callers too. A short yes/no is meaningful only with an explicit
        # question awaiting clarification, never with an arbitrary prior answer.
        raw_pending = dialogue.get('pending_clarification')
        pending = (safe_context_text(raw_pending, 240).strip()
                   if isinstance(raw_pending, str) and len(raw_pending) <= 240 else '')
        pending_valid = bool(pending and pending.endswith('?'))
        short_reply = bool(re.fullmatch(
            r'(?:sim|ok|okay|entendi|nao|s|n|isso|isso mesmo|certo|claro|pode ser|nao obrigado|nao obrigada)[.!?\s]*',
            plain.strip()))
        clarification_reply = pending_valid and short_reply
        if (referential and len(question) <= 180) or clarification_reply:
            previous = dialogue.get('last_question')
            if isinstance(previous, str) and 1 <= len(previous) <= 500:
                previous = safe_context_text(previous, 500)
                selected.update(_matches(previous, topics))
                used_history = True
            if clarification_reply:
                selected.update(_matches(pending, topics))
                used_history = True
    # Explicitly labelled guards remain global even if their vocabulary differs
    # from the question. A new standalone condition cannot be ranked out.
    selected.update(key for key, topic in topics.items()
                    if QUALIFIERS.search(_plain(topic.get('title', key) + ' ' + key.replace('_', ' '))))
    # Known bundles are indivisible once any member is chosen. Dependency bundles
    # differ from routing bundles to avoid transitive expansion via generic cards.
    dependencies = (
        ('amplify_doc_categories', 'amplify_doc_monthly_journey', 'amplify_doc_programs', 'garantias'),
        ('amplify_doc_sample_types', 'amplify_doc_sample_approval', 'amplify_doc_sample_process', 'garantias'),
        ('funcionamento', 'custos', 'ja_tem_agencia'),
    )
    references = {key: set(REFERENCE.findall(topic['answer'])) & topics.keys()
                  for key, topic in topics.items()}
    changed = True
    while changed:
        before = set(selected)
        for group in dependencies:
            # Generic guarantees cannot activate every otherwise unrelated group.
            if selected.intersection(set(group) - {'garantias'}):
                selected.update(set(group) & topics.keys())
        for key in list(selected):
            selected.update(references[key])
            # A supplemental rule may point back at its offer rather than the
            # offer knowing about newer rules. Keep both ends of the link.
            selected.update(other for other, links in references.items() if key in links)
            selected.update(other for other in topics
                            if other.startswith(key + '_') or key.startswith(other + '_'))
        changed = before != selected
    result = {key: deepcopy(value) for key, value in knowledge.items() if key != 'topics'}
    result['topics'] = [deepcopy(topics[key]) for key in sorted(selected)]
    source_chars = len(result['limits']) + sum(len(t['answer']) for t in result['topics'])
    result['selection'] = {'catalog_topic_count': len(topics), 'selected_topic_count': len(selected),
                           'history_used': used_history, 'source_chars': source_chars}
    if (len(selected) > MAX_SELECTED_TOPICS or source_chars > MAX_SOURCE_CHARS
            or len(json.dumps(result, ensure_ascii=False, sort_keys=True)) > MAX_CONTEXT_CHARS):
        raise ValueError('demo_selection_budget_exceeded')
    return result
