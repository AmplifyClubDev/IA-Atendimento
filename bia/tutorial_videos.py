"""User-provided public tutorials. Verified bytes against originals on 2026-11-13.
URLs are internal selectors: transport removes them and sends verified MP4 attachments.
"""
ACCEPT_INVITE_URL = 'https://divlvdmsqbwplervsqwu.supabase.co/storage/v1/object/public/bia-orientacoes/convite.mp4'
ACTIVATE_SHOP_URL = 'https://divlvdmsqbwplervsqwu.supabase.co/storage/v1/object/public/bia-orientacoes/Download.mp4'

def invitation_help(text):
    return text + '\n\nVídeo de como aceitar o convite:\n' + ACCEPT_INVITE_URL

def activation_help(text):
    return text + '\n\nVeja o vídeo de como ativar o TikTok Shop:\n' + ACTIVATE_SHOP_URL

# Exact immutable allowlist: never fetch an arbitrary URL supplied by a lead/model.
ASSETS = {
    ACCEPT_INVITE_URL: {'key': 'accept_invite', 'filename': 'como-aceitar-convite.mp4',
        'size': 865972, 'sha256': '693fbc62ecd6d3018428d0912e953346f3488652d5a3d1cfedde93367ca357b0'},
    ACTIVATE_SHOP_URL: {'key': 'activate_shop', 'filename': 'como-ativar-tiktok-shop.mp4',
        'size': 7294077, 'sha256': '6290dc8d2a2779c157b0b5625f0813553d630059bcf76603da7925eb2f114cea'},
}


def select_attachment(text, buttons):
    """An internal known tutorial URL selects a video; it is never delivered as text."""
    found = [url for url in ASSETS if url in text]
    if not found:
        return None
    if len(found) != 1 or text.count(found[0]) != 1:
        raise ValueError('ambiguous_tutorial')
    url = found[0]
    caption = text.replace('Vídeo de como aceitar o convite:\n' + url, '')
    caption = caption.replace('Veja o vídeo de como ativar o TikTok Shop:\n' + url, '')
    caption = caption.replace(url, '').strip()
    # Native video messages cannot also be interactive-button messages. Keep the
    # same reply choices discoverable as text, understood by the existing router.
    choices = [b.strip() for b in (buttons or [])[:10] if isinstance(b, str) and b.strip()]
    if choices:
        caption += '\n\nResponda: ' + ' / '.join(choices)
    if not caption or len(caption) > 1024:
        raise ValueError('video_caption_invalid')
    return {'url': url, 'caption': caption, **ASSETS[url]}
