"""Traz telefones por @ do TikTok de uma fonte externa para interno.telefones_creators (fase A da renovação).

Fonte "base_amplify": o outro Supabase ("Base de dados - Amplify"), tabela criadores (tiktok_handle, telefone).
Só LÊ a fonte. Grava no nosso banco pela função public.importar_telefones_v5 (repetir não duplica).

Uso:
    BASE_AMPLIFY_URL=https://<ref>.supabase.co BASE_AMPLIFY_KEY=<chave de leitura> \
    SUPABASE_URL=https://divlvdmsqbwplervsqwu.supabase.co SUPABASE_SERVICE_ROLE_KEY=<chave> \
    python -I importar_telefones.py [--gravar]

Sem --gravar só conta (simulação). Mostra só números, nunca telefones.
"""
import json
import os
import sys
from urllib.request import ProxyHandler, Request, build_opener

PAGINA = 1000
_http = build_opener(ProxyHandler({}))


def _pedir(url, chave, corpo=None):
    cab = {'apikey': chave, 'Authorization': 'Bearer ' + chave, 'Content-Type': 'application/json'}
    dados = json.dumps(corpo).encode() if corpo is not None else None
    with _http.open(Request(url, data=dados, headers=cab, method='POST' if dados else 'GET'), timeout=60) as r:
        return json.loads(r.read() or b'null')


def ler_base_amplify(url, chave):
    itens, inicio = [], 0
    while True:
        pagina = _pedir(f'{url}/rest/v1/criadores?select=id,tiktok_handle,telefone,atualizado_em'
                        f'&order=id.asc&limit={PAGINA}&offset={inicio}', chave)
        for linha in pagina:
            if linha.get('tiktok_handle') and linha.get('telefone'):
                itens.append({'arroba': linha['tiktok_handle'], 'telefone': str(linha['telefone']),
                              'ref': str(linha.get('id') or ''), 'visto_em': linha.get('atualizado_em')})
        if len(pagina) < PAGINA:
            return itens
        inicio += PAGINA


def main(argv):
    gravar = '--gravar' in argv
    itens = ler_base_amplify(os.environ['BASE_AMPLIFY_URL'].rstrip('/'), os.environ['BASE_AMPLIFY_KEY'])
    print('base_amplify: linhas com @ e telefone =', len(itens))
    if not gravar:
        print('simulação: nada gravado (use --gravar)')
        return 0
    destino, chave = os.environ['SUPABASE_URL'].rstrip('/'), os.environ['SUPABASE_SERVICE_ROLE_KEY']
    total = {'recebidos': 0, 'validos': 0, 'gravados': 0}
    for i in range(0, len(itens), 2000):
        r = _pedir(f'{destino}/rest/v1/rpc/importar_telefones_v5', chave,
                   {'p': {'fonte': 'base_amplify', 'itens': itens[i:i + 2000]}})
        for k in total:
            total[k] += int(r.get(k) or 0)
    print('gravado:', total)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
