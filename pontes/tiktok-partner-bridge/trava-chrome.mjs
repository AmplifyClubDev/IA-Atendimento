// Trava do Chrome deixada por um container antigo (SingletonLock -> "<host>-<pid>"), 23/11/2026.
// Num container novo, o volume /data só está aqui, então trava de outro host é órfã: o Chrome se recusa a abrir
// o perfil até ela sair. Só remove os 3 arquivos Singleton*; o perfil (cookies, login) não é tocado.
import fs from 'node:fs';
import path from 'node:path';

export function limparTravaOrfa(profileDir, hostAtual) {
  const trava = path.join(profileDir, 'SingletonLock');
  let alvo;
  try { alvo = fs.readlinkSync(trava); } catch { return false; }
  const host = String(alvo).replace(/-\d+$/, '');
  if (!host || host === hostAtual) return false;
  for (const nome of ['SingletonLock', 'SingletonCookie', 'SingletonSocket']) {
    try { fs.unlinkSync(path.join(profileDir, nome)); } catch { /* já não existe */ }
  }
  return true;
}
