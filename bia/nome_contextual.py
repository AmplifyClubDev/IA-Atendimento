"""Pure extraction of a declared name or preferred form of address.

The caller owns the conversation fence: requested=True is valid only after an
accepted name question in the same cycle. This module never reads a display
name, changes a record, confirms identity or decides whether a change is allowed.
"""
from __future__ import annotations

import re
import unicodedata


def _normal(value):
    decomposed = unicodedata.normalize('NFKD', value.casefold())
    return ' '.join(''.join(c for c in decomposed if not unicodedata.combining(c)).split())


_DECLARATION = re.compile(
    r"(?:meu nome (?:é|e)|(?:eu )?me chamo|(?:eu )?sou(?: [oa])?|"
    r"pode me chamar(?: só)? de|me cham[ae] de|prefiro que me chame de|"
    r"prefiro ser chamad[oa] de)\s+(.+)", re.IGNORECASE)

# These are speech acts and journey answers, not evidence of a person's name.
_NON_NAMES = frozenset((
    'oi', 'ola', 'opa', 'hello', 'bom dia', 'boa tarde', 'boa noite', 'tudo bem',
    'sim', 'nao', 'ok', 'okay', 'claro', 'entendi', 'concordo', 'obrigado', 'obrigada',
    'resetar', 'reset', 'reiniciar', 'reiniciar atendimento', 'reiniciar chat',
    'recomecar', 'menu', 'voltar', 'pular', 'continuar', 'pode continuar',
    'quero me agenciar', 'conhecer a amplify', 'conhecer amplify', 'ja falei',
    'nao sei', 'prefiro nao informar', 'nao quero informar', 'mais tarde',
    'agora nao', 'sem nome', 'ninguem', 'nao informado',
))
_SPEECH_WORDS = frozenset((
    'eu', 'sou', 'estou', 'meu', 'minha', 'nome', 'me', 'chamo', 'chama',
    'quero', 'preciso', 'tenho', 'gostaria', 'voce', 'pode', 'prefiro',
    'nao', 'sim', 'oi', 'ola', 'resetar', 'reset', 'reiniciar', 'menu',
    'continuar', 'agora', 'amanha', 'ontem', 'hoje', 'antes', 'depois',
    'tiktok', 'instagram', 'facebook', 'whatsapp', 'agencia', 'agenciar',
    'agenciado', 'agenciada', 'amplify', 'parceria', 'agenciamento', 'beneficios',
    'comissao', 'convite', 'cadastro', 'acesso', 'creator', 'criador', 'criadora',
    'seguidor', 'seguidores', 'video', 'vi', 'anuncio', 'indicacao', 'amigo',
    'amiga', 'duvida', 'entendi', 'concordo', 'obrigado', 'obrigada', 'claro',
    'ja', 'falei', 'exemplo', 'talvez', 'se', 'caso', 'ele', 'ela',
))
_PARTICLES = frozenset(('da', 'de', 'do', 'das', 'dos', 'e'))


def _valid_name(value):
    if not 2 <= len(value) <= 80 or _normal(value) in _NON_NAMES:
        return False
    # Letters, spaces, and apostrophes/hyphens between letters only. Digits,
    # emails, handles, URLs, emoji, punctuation and quoted examples are refused.
    letter_count = 0
    for index, character in enumerate(value):
        if unicodedata.category(character).startswith('L'):
            letter_count += 1
        elif character == ' ':
            continue
        elif character in "-'":
            if (index == 0 or index == len(value) - 1
                    or not unicodedata.category(value[index - 1]).startswith('L')
                    or not unicodedata.category(value[index + 1]).startswith('L')):
                return False
        else:
            return False
    tokens = re.split(r"[ '\-]+", _normal(value))
    # Preserve existing multiword name fixtures/preferences such as "Nome Novo"
    # without accepting a bare field label or phrases like "meu nome".
    placeholder_name = (len(value.split()) >= 2
                        and any(token not in _SPEECH_WORDS and token not in _PARTICLES for token in tokens))
    blocked = _SPEECH_WORDS - {'nome'} if placeholder_name else _SPEECH_WORDS
    return (letter_count >= 2 and not any(token in blocked for token in tokens)
            and any(token not in _PARTICLES for token in tokens))


def extract_name(text, requested=False):
    """Return the full declared name, or None when it is not unambiguous.

An explicit self-introduction/preference works before agency interest. A bare
name requires requested is True; the caller must bind that permission to the
same cycle and accepted name question. Existing-record confirmation is separate.
"""
    if not isinstance(text, str) or type(requested) is not bool or not 0 < len(text) <= 200:
        return None
    text = unicodedata.normalize('NFC', text).replace('’', "'").strip()
    if '?' in text or any(c in text for c in ('@', '/', '\\', '\n', '\r', '"', '“', '”', '‘')):
        return None
    text = text.rstrip('.!').strip()
    declaration = _DECLARATION.fullmatch(text)
    if declaration:
        value = declaration[1]
    elif requested is True:
        value = text
    else:
        return None
    value = ' '.join(value.split())
    return value if _valid_name(value) else None


def first_name(value):
    """Return a safe first name from a value already accepted by extract_name."""
    name = extract_name(value, requested=True)
    first = name.split(' ', 1)[0] if name else None
    # Quem escreve tudo minúsculo ou tudo maiúsculo é chamado com a inicial maiúscula.
    return first.capitalize() if first and (first.islower() or first.isupper()) else first


def name_question(text):
    """Recognize one direct name request; this does not prove it was delivered."""
    if not isinstance(text, str) or not 0 < len(text) <= 1500 or text.count('?') > 1:
        return False
    value = _normal(re.sub(r'[*_~`]', '', text))
    if (re.search(r'@|\b(?:email|e-mail|telefone|whatsapp|cpf|documento|endereco|origem|'
                  r'tiktok|instagram|shop)\b', value)
            or re.search(r'\b(?:nao|nunca|jamais)\b[^.!?]{0,60}'
                         r'(?:\b(?:seu|teu) nome\b|\bte chamar\b)', value)
            or any(mark in value for mark in ('"', '“', '”'))):
        return False
    return bool(re.search(
        r'\b(?:como (?:posso|podemos) (?:te chamar|chamar voce)|'
        r'por qual nome (?:posso|podemos) te chamar|'
        r'qual (?:e )?(?:o )?(?:seu|teu) nome|'
        r'(?:pode |poderia )?me (?:dizer|informar|contar) (?:o )?(?:seu|teu) nome|'
        r'me (?:diga|informe|conte) (?:o )?(?:seu|teu) nome)\s*[?.!]?(?:\s|$)', value))
