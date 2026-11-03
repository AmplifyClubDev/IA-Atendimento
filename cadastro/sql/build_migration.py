"""Monta 001_cadastro_publico_v5.sql a partir do template e da função já aplicada.

A validação dos 63 campos e o upsert da ficha são copiados literalmente de
public.registrar_cadastro_ensaio_v5 (aplicar-integracao-real-v2.sql), para que o
formulário público e o da Bia validem e gravem exatamente igual.
Só os códigos de erro trocam o prefixo `ensaio_` por `cadastro_publico_`.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "v5-integracao-real-20261028" / "sql" / "aplicar-integracao-real-v2.sql"
SOURCE_SHA256 = "c394be8cb46ce88b2dc67f07c051c640fff8e57f47bb62b38e308be519e190fd"
TEMPLATE = HERE / "template_cadastro_publico_v5.sql"
OUTPUT = HERE / "001_cadastro_publico_v5.sql"


def between(lines, start_marker, end_marker, *, include_end=False):
    start = next(i for i, line in enumerate(lines) if start_marker in line)
    end = next(i for i in range(start + 1, len(lines)) if end_marker in lines[i])
    return lines[start:end + (1 if include_end else 0)]


def build():
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise SystemExit("fonte da função aplicada mudou; revise antes de gerar")
    lines = raw.decode("utf-8").splitlines()
    function = between(lines, "FUNCTION public.registrar_cadastro_ensaio_v5", "$function$;", include_end=True)
    map_decl = [line for line in function if line.lstrip().startswith("v_map jsonb := $mapping$")]
    assert len(map_decl) == 1
    validation = between(function, "-- Cada chave de destino", "foreach v_observation in array")
    upsert = between(function, "v_flat:=p_payload->'identity';", "v_ref:=(case when v_execution_mode")
    for block in (validation, upsert):
        assert not any("v_execution_mode" in line for line in block)
    validation_text = "\n".join(validation).replace("message='ensaio_", "message='cadastro_publico_")
    assert "ensaio_" not in validation_text
    text = TEMPLATE.read_text(encoding="utf-8")
    for key, value in (("{{MAP_DECL}}", map_decl[0]), ("{{VALIDATION}}", validation_text),
                       ("{{CREATORS_UPSERT}}", "\n".join(upsert))):
        assert text.count(key) == 1
        text = text.replace(key, value)
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    return hashlib.sha256(OUTPUT.read_bytes()).hexdigest()


if __name__ == "__main__":
    print(OUTPUT.name, build())
