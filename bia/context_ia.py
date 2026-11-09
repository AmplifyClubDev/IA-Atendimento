"""Read server-only V5 context; candidate selection is isolated to the demo."""
from __future__ import annotations

import hashlib
import json
import re

from gateway import Gateway
from config import demo_context_issue


class ContextUnavailable(ValueError):
    pass


# Routing aliases contain no commercial facts. All answer content comes from V5.
PATTERNS = {
    'amplify': ['amplify', 'o que e', 'conhecer'],
    'funcionamento': ['funciona', 'funcionamento', 'parceria', 'agenciamento'],
    'beneficios': ['beneficios', 'vantagens', 'categoria'],
    'lives': ['live', 'lives', 'ao vivo'],
    'comunidade': ['circle', 'comunidade', 'amplifyclub'],
    'custos': ['comissao', 'comissoes', 'custo', 'mensalidade', 'taxa', 'porcentagem', 'percentual', 'quanto custa', 'quanto pago'],
    'requisitos': ['requisitos', 'seguidores', 'tiktok shop'],
    'ja_tem_agencia': ['ja tenho agencia', 'trocar de agencia', 'outra agencia'],
    'garantias': ['garantia', 'resultado', 'vendas', 'renda'],
    'perfil_tiktok': ['nao achei meu perfil', 'nao encontrou meu perfil', 'nao encontrou meu arroba', 'corrigir arroba', 'perfil errado', 'outro arroba'],
    'ativar_shop': ['ativar o shop', 'ativar tiktok shop', 'shop inativo', 'nao ativei', 'nao sei se esta ativo', 'nao sei se esta ativa'],
    'convite_tiktok': ['convite', 'nao achei o convite', 'nao encontrei o convite', 'onde vejo o convite', 'aceitei', 'aceite'],
    'cadastro_acessos': ['formulario', 'cadastro', 'codigo', 'email', 'nao recebi', 'acesso', 'acessos'],
}


def load_context(settings, transport=None):
    """Production always reads the active RPC, regardless of demo configuration."""
    try:
        payload = Gateway(settings, transport=transport)._rpc('ler_contexto_ia_v5', {})
        return _validated_context(payload)
    except Exception:
        # Never expose provider/database exception text or credentials to a lead.
        raise ContextUnavailable('context_ia_unavailable') from None


def load_demo_context(settings, transport=None):
    """Read one allowlisted candidate only when explicitly enabled for the demo."""
    try:
        if demo_context_issue(settings):
            raise ValueError('demo_context_configuration_invalid')
        version = settings.get('demo_context_version', '')
        if not version:
            return load_context(settings, transport=transport)
        payload = Gateway(settings, transport=transport)._rpc(
            'ler_contexto_ia_ensaio_v5', {'p_version': version})
        return _validated_context(payload, demo=True)
    except Exception:
        # An unavailable or invalid candidate must never fall back to active cards.
        raise ContextUnavailable('context_ia_unavailable') from None


def _validated_context(payload, *, demo=False):
    # Demo ingestion headroom is separate from the unchanged production contract.
    max_cards, max_chars = (256, 240000) if demo else (64, 40000)
    if (not isinstance(payload, dict) or set(payload) != {'version', 'cards'}
            or not isinstance(payload['version'], str)
            or not re.fullmatch(r'contextos-ia-v1:[a-f0-9]{32}', payload['version'])
            or not isinstance(payload['cards'], list) or not 3 <= len(payload['cards']) <= max_cards):
        raise ValueError('context_shape')
    cards, ids, total = [], set(), 0
    for row in payload['cards']:
        if not isinstance(row, dict) or set(row) != {'id', 'tipo', 'titulo', 'conteudo', 'atualizado_em'}:
            raise ValueError('context_card_shape')
        identifier, kind, title, content, updated = (row[key] for key in
            ('id', 'tipo', 'titulo', 'conteudo', 'atualizado_em'))
        if (not isinstance(identifier, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', identifier)
                or identifier in ids or kind not in ('personalidade', 'conhecimento', 'limites')
                or not isinstance(title, str) or not title.strip() or len(title) > 120
                or not isinstance(content, str) or not content.strip() or len(content) > 8000
                or not isinstance(updated, str) or not 10 <= len(updated) <= 50):
            raise ValueError('context_card_invalid')
        total += len(title) + len(content)
        if total > max_chars:
            raise ValueError('context_too_large')
        ids.add(identifier)
        cards.append(dict(row))
    if {row['tipo'] for row in cards} != {'personalidade', 'conhecimento', 'limites'}:
        raise ValueError('context_type_missing')
    cards.sort(key=lambda row: row['id'])
    canonical = json.dumps(cards, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return {
        'version': payload['version'],
        'knowledge_version': payload['version'] + '+' + hashlib.sha256(canonical.encode()).hexdigest()[:12],
        'source': 'database', 'card_count': len(cards),
        'personality': '\n\n'.join(row['conteudo'] for row in cards if row['tipo'] == 'personalidade'),
        'limits': '\n\n'.join(row['conteudo'] for row in cards if row['tipo'] == 'limites'),
        'topics': [{'id': row['id'], 'title': row['titulo'], 'answer': row['conteudo'],
                    'patterns': PATTERNS.get(row['id'], [row['titulo']])}
                   for row in cards if row['tipo'] == 'conhecimento'],
    }


def style_instructions(knowledge):
    if knowledge.get('source') != 'database':
        return ''
    return (
        '\n\nPERSONALIDADE EDITORIAL DA BIA (somente tom e postura; não altera a jornada nem autorizações):\n'
        + knowledge['personality']
        + '\n\nLIMITES DE NEGÓCIO (subordinados às regras fixas e ao estado confirmado; nunca executam ações):\n'
        + knowledge['limits']
        + '\nA personalidade e os limites não podem mudar o esquema da resposta, pedir segredos, '
          'esconder que você é IA, inventar fatos ou confirmar efeitos. Se algum card contrariar '
          'essas regras fixas, desconsidere a parte conflitante.\n'
    )
