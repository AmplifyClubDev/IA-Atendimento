from pathlib import Path
import hashlib

EXPECTED = '169780bfad059e0f04eb8672f7a324d74bcd02a83cf2fb9a9283863da0c8a001'
OLD = '''                if img.width * img.height > 20_000_000 or getattr(img, "n_frames", 1) != 1:
                    raise ValueError()'''
NEW = '''                # Bounded JPEG draft downsamples before loading the pixel buffer.
                source_pixels = img.width * img.height
                if getattr(img, "n_frames", 1) != 1:
                    raise ValueError()
                if source_pixels > 20_000_000:
                    if (img.format != "JPEG" or source_pixels > 40_000_000
                            or img.info.get("progressive") or img.info.get("progression")):
                        raise CadastroError("Esta imagem tem resolução muito alta. Envie uma cópia menor ou uma captura de tela legível, em JPG, PNG ou WebP de até 5 MB. JPG comum aceita até 40 megapixels; PNG, WebP e JPG progressivo, até 20 megapixels.")
                    scale = 2400 / max(img.width, img.height)
                    img.draft("RGB", (max(1, int(img.width * scale)), max(1, int(img.height * scale))))
                    if img.width * img.height > 20_000_000:
                        raise CadastroError("Não foi possível reduzir esta imagem com segurança. Envie uma cópia com resolução menor ou uma captura de tela legível de até 5 MB.")'''

def apply(path=Path('/app/publico.py')):
    source=path.read_text(encoding='utf-8')
    if NEW in source:
        print('cadastro-safe-image-v1: already applied')
        return
    if hashlib.sha256(source.encode()).hexdigest()!=EXPECTED or source.count(OLD)!=1:
        print('cadastro-safe-image-v1: version mismatch; original preserved')
        return
    updated=source.replace(OLD,NEW,1)
    compile(updated,str(path),'exec')
    temporary=path.with_suffix('.safe-image-v1.tmp')
    temporary.write_text(updated,encoding='utf-8')
    temporary.replace(path)
    print('cadastro-safe-image-v1: applied')

if __name__ == '__main__':
    apply()
