from pathlib import Path
import hashlib
PATCHES = [('/app/publico.py', '169780bfad059e0f04eb8672f7a324d74bcd02a83cf2fb9a9283863da0c8a001', '                if img.width * img.height > 20_000_000 or getattr(img, "n_frames", 1) != 1:\n                    raise ValueError()', '                # Bounded JPEG draft downsamples before loading the pixel buffer.\n                source_pixels = img.width * img.height\n                if getattr(img, "n_frames", 1) != 1:\n                    raise ValueError()\n                if source_pixels > 20_000_000:\n                    if (img.format != "JPEG" or source_pixels > 40_000_000\n                            or img.info.get("progressive") or img.info.get("progression")):\n                        raise CadastroError("Esta imagem tem resolução muito alta. Envie uma cópia menor ou uma captura de tela legível, em JPG, PNG ou WebP de até 5 MB. JPG comum aceita até 40 megapixels; PNG, WebP e JPG progressivo, até 20 megapixels.")\n                    scale = 2400 / max(img.width, img.height)\n                    img.draft("RGB", (max(1, int(img.width * scale)), max(1, int(img.height * scale))))\n                    if img.width * img.height > 20_000_000:\n                        raise CadastroError("Não foi possível reduzir esta imagem com segurança. Envie uma cópia com resolução menor ou uma captura de tela legível de até 5 MB.")'), ('/app/store.py', '8bd745bc2c7a2c3b3d9ec0fb9c220d815820e231a8f55064eb919baf5789a618', "            attempts = row['otp_attempts'] if row['otp_email_hash'] == email_hash else 0", '            # Cada nova geração tem tentativas próprias; limites de envio preservados.\n            attempts = 0')]

def apply(root=None):
    pending=[]
    for destination, expected, old, new in PATCHES:
        path=Path(destination) if root is None else Path(root)/destination.removeprefix('/app/')
        source=path.read_text(encoding='utf-8')
        if new in source:
            continue
        if hashlib.sha256(source.encode()).hexdigest()!=expected or source.count(old)!=1:
            raise RuntimeError('cadastro-image-otp-v1: source version mismatch; no patch written')
        updated=source.replace(old,new,1)
        compile(updated,str(path),'exec')
        pending.append((path,updated))
    for path,updated in pending:
        temp=path.with_suffix('.image-otp-v1.tmp')
        temp.write_text(updated,encoding='utf-8')
        temp.replace(path)
    print('cadastro-image-otp-v1: validated and applied')
if __name__=='__main__': apply()
