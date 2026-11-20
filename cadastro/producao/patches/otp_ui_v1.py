from pathlib import Path
import hashlib
BASE='cd06d4f31832bc3257f6f30f6560594a050036c5a0abfcf908973e4cf2a9cc4f'
CHANGES=[["let emailRequired=false,emailVerifiedFor='',emailWaitUntil=0,emailTimer=null,emailAction=false,emailCodeRequestedFor='';", "let emailRequired=false,emailVerifiedFor='',emailWaitUntil=0,emailTimer=null,emailAction=false,emailCodeRequestedFor='';\nlet emailConfirmationError='',emailRequestKey='';"], [' emailRequired=state.required??emailRequired;', " const nextRequestKey=String(state.requested_at||state.request_reference||'');\n if(state.verified||(nextRequestKey&&nextRequestKey!==emailRequestKey)||['expirado','tentativas_esgotadas','devolvido'].includes(state.status))emailConfirmationError='';\n if(nextRequestKey)emailRequestKey=nextRequestKey;\n emailRequired=state.required??emailRequired;"], [" updateEmailButtons();\n if(['pendente','enviando','enviado'].includes(state.status)", " if(emailConfirmationError&&['pendente','enviando','enviado','incerto'].includes(state.status))emailNotice(emailConfirmationError,true);\n updateEmailButtons();\n if(['pendente','enviando','enviado'].includes(state.status)"], [" emailCodeRequestedFor=email;el('email-code-entry').hidden=false;", " emailConfirmationError='';emailCodeRequestedFor=email;el('email-code-entry').hidden=false;"], ["else emailNotice(state.status==='codigo_incorreto'?'Código incorreto. Confira o e-mail e tente novamente.':'Este código expirou ou atingiu o limite de tentativas. Solicite outro.',true);", "else{emailConfirmationError=state.status==='codigo_incorreto'?'Código incorreto. Confira o e-mail e tente novamente.':'Este código expirou ou atingiu o limite de tentativas. Solicite outro.';emailNotice(emailConfirmationError,true);}"], ["el('email-code').addEventListener('keydown'", "el('email-code').addEventListener('input',()=>{if(emailConfirmationError){emailConfirmationError='';emailNotice('');}});\nel('email-code').addEventListener('keydown'"], [" emailCodeRequestedFor='';emailWaitUntil=0;", " emailConfirmationError='';emailRequestKey='';emailCodeRequestedFor='';emailWaitUntil=0;"]]

def apply(path):
    path=Path(path)
    source=path.read_text(encoding='utf-8')
    if all(new in source for old,new in CHANGES):
        print('cadastro-otp-ui-v1: already applied')
        return
    if hashlib.sha256(source.encode()).hexdigest()!=BASE:
        raise RuntimeError('cadastro-otp-ui-v1: source mismatch; preserved')
    for old,new in CHANGES:
        if source.count(old)!=1:raise RuntimeError('cadastro-otp-ui-v1: replacement mismatch; preserved')
        source=source.replace(old,new,1)
    tmp=path.with_suffix('.otp-ui.tmp')
    tmp.write_text(source,encoding='utf-8');tmp.replace(path)
    print('cadastro-otp-ui-v1: applied')
if __name__=='__main__':
    import sys
    apply(sys.argv[1])
