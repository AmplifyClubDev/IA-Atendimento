"""User-provided public tutorials. Verified bytes against originals on 2026-11-13.
Links only: delivery uses the existing audited text transport, not a media receipt.
"""
ACCEPT_INVITE_URL = 'https://divlvdmsqbwplervsqwu.supabase.co/storage/v1/object/public/bia-orientacoes/convite.mp4'
ACTIVATE_SHOP_URL = 'https://divlvdmsqbwplervsqwu.supabase.co/storage/v1/object/public/bia-orientacoes/Download.mp4'

def invitation_help(text):
    return text + '\n\nVídeo de como aceitar o convite:\n' + ACCEPT_INVITE_URL

def activation_help(text):
    return text + '\n\nVeja o vídeo de como ativar o TikTok Shop:\n' + ACTIVATE_SHOP_URL
