"""
anotador.py — Convierte (crop imagen + descripción en texto) → JSON de UNA pieza.

Flujo:
  1. Usuario dibuja rectángulo sobre la nota manuscrita
  2. Usuario escribe descripción libre: "Encimera 3000×620, frente pulido,
     cabezas ingletadas 45.5°, hueco fregadero 490×400 a 150mm del frente"
  3. Este módulo recibe el crop + el texto y devuelve el dict estructurado
     de la pieza, listo para añadir a datos.piezas[]
"""

import os
import io
import json
import base64
import re
from pathlib import Path
from typing import Optional

import anthropic
from PIL import Image


MODEL = "claude-opus-4-7"
MAX_CROP_SIDE = 1600


SYSTEM_PROMPT = """Eres un asistente experto en convertir descripciones en lenguaje natural
de piezas de encimera de cocina en el JSON estructurado que usa el sistema de producción.

El usuario te envía:
  (a) Un RECORTE de una nota manuscrita sobre papel cuadriculado que muestra UNA pieza
  (b) Una DESCRIPCIÓN en texto libre con las medidas, acabados y detalles que él ve

Tu tarea: devolver el JSON de esa UNA pieza. El usuario ha leído la nota él mismo,
tu trabajo es traducir su descripción a los campos correctos — no dudes de sus números.

## Tipos de pieza (elige el más apropiado)
- encimera, chapeado, copete, rodapie, isla, costado, pilastra, paso, tabica, zocalo, otro

## Campos de una pieza
{
  "tipo": "...",
  "forma": "rectangular" | "L" | "U" | "irregular",
  "largo_mm": <número>,
  "ancho_mm": <número>,           // para encimera = fondo (profundidad)
  "alto_mm": null,                 // normalmente null salvo chapeados verticales
  "descuadro_izq_mm": null,
  "descuadro_der_mm": null,
  "descuadro_sup_mm": null,
  "descuadro_inf_mm": null,
  "tiene_guion": false,            // si el usuario dice "568-" mencionando descuento del grosor
  "zona": null,                    // pared norte, isla, etc si el usuario lo indica
  "pulido_vuelo_mm": null,
  "acabados_aristas": {
    "frente":     {"tipo": null, "angulo": null, "profundidad_mm": null},
    "fondo":      {"tipo": null, "angulo": null, "profundidad_mm": null},
    "cabeza_izq": {"tipo": null, "angulo": null, "profundidad_mm": null},
    "cabeza_der": {"tipo": null, "angulo": null, "profundidad_mm": null}
  },
  "notas": "...",
  "huecos": [ { "tipo": "placa|fregadero|grifo|enchufe",
                 "largo_mm": ..., "ancho_mm": ...,
                 "subtipo": "sobre_encimera" | "bajo_encimera" | null,
                 "posicion": "centro|izquierda|derecha" | null,
                 "distancia_frente_mm": ..., "distancia_lado_mm": null,
                 "notas": "..." } ]
}

## Convenciones a aplicar

⚠️ REGLA CRÍTICA: Esto es **producción**, no presupuesto. NO inventes medidas, NO
uses defaults, NO completes valores típicos. Si el usuario no dice una medida,
deja el campo en **null** y añade en el campo `notas` una línea como
"FALTA CONFIRMAR: {qué falta}". El operador lo verá en la UI y lo rellenará.

1. **Inglete**: si el usuario dice "inglete/ingletes" sin ángulo, usa 45.5°
   (convención fija del negocio, no un default presupuestario). Si dice otro
   ángulo, úsalo literalmente.
2. **Bisel**: solo si lo menciona explícitamente. Rellena angulo y profundidad_mm
   sólo con lo que él diga; si falta alguno, null.
3. **Pulido**: tipo="pulido" en la arista que indique; angulo y profundidad_mm null.
4. **Arista "frente"** = lado inferior visible de la cocina. **"fondo"** = pegado
   a pared. **"cabeza_izq/der"** = laterales.
5. **Huecos**: todo campo (largo_mm, ancho_mm, posicion, distancia_frente_mm,
   distancia_lado_mm) debe salir del texto del usuario. Si falta, null + nota
   "FALTA: hueco placa ancho_mm" o similar. **No** rellenes 560×490 ni 490×400
   ni 70mm de frente por defecto.
6. **"bajoencimera" o "B/E"** → subtipo="bajo_encimera". **"SE" o "sobre encimera"**
   → subtipo="sobre_encimera".
7. **Guion final** (ej "568-"): marca tiene_guion=true sólo si el usuario lo menciona.
8. **Enchufe / grifo**: son círculos con diámetro fijo por herramienta (no hace falta
   dimensión); pero sí necesitan posición (distancia_frente_mm + distancia_lado_mm o
   posicion="centro"). Si la posición no está clara → null + notas.

## Formato de respuesta

- Si la descripción se refiere a UNA sola pieza → devuelve un **objeto JSON** con los
  campos de esa pieza.
- Si la descripción se refiere a VARIAS piezas (ej. "rodapié dividido en dos tramos
  de 1263mm cada uno", "cuatro rodapiés: 330, 910, 865, 905") → devuelve un **array
  JSON** con un objeto pieza por cada una. Cada una con sus propias dimensiones,
  acabados y huecos según la descripción.

SOLO JSON (objeto o array), sin prosa, sin bloques ``` ```. Si algún campo no puede
deducirse, déjalo null. NO inventes números. Si el usuario omite el ancho y solo da
el largo, deja ancho_mm=null (el editor lo rellenará luego).
"""


def _encode_crop_from_bbox(image_path: Path, bbox_norm: tuple[float, float, float, float]) -> tuple[str, str, tuple[int, int]]:
    """
    Abre la imagen original, recorta con bbox normalizado [x1,y1,x2,y2] en [0,1]
    (origen arriba-izquierda), redimensiona si hace falta y devuelve base64 + mime.
    """
    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    x1 = max(0, int(bbox_norm[0] * W))
    y1 = max(0, int(bbox_norm[1] * H))
    x2 = min(W, int(bbox_norm[2] * W))
    y2 = min(H, int(bbox_norm[3] * H))
    if x2 <= x1 + 5 or y2 <= y1 + 5:
        raise ValueError("Bounding box demasiado pequeño")
    crop = img.crop((x1, y1, x2, y2))

    cw, ch = crop.size
    if max(cw, ch) > MAX_CROP_SIDE:
        if cw >= ch:
            nw, nh = MAX_CROP_SIDE, int(ch * MAX_CROP_SIDE / cw)
        else:
            nw, nh = int(cw * MAX_CROP_SIDE / ch), MAX_CROP_SIDE
        crop = crop.resize((nw, nh), Image.LANCZOS)

    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=92)
    data = buf.getvalue()
    return (base64.standard_b64encode(data).decode("ascii"),
            "image/jpeg",
            crop.size)


def _extract_json(text: str):
    """
    Parsea la respuesta de Claude. Puede devolver un dict (una pieza)
    o una lista de dicts (varias piezas).
    """
    text = text.strip()
    stripped = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # Intento 2: encontrar el primer carácter de apertura válido ([ o {)
    start_brace  = stripped.find("{")
    start_bracket = stripped.find("[")
    if start_brace < 0 and start_bracket < 0:
        raise ValueError(f"No se encontró JSON en la respuesta: {text[:300]}")
    if start_bracket >= 0 and (start_brace < 0 or start_bracket < start_brace):
        start, open_c, close_c = start_bracket, "[", "]"
    else:
        start, open_c, close_c = start_brace, "{", "}"
    depth = 0
    for i in range(start, len(stripped)):
        if stripped[i] == open_c:  depth += 1
        elif stripped[i] == close_c:
            depth -= 1
            if depth == 0:
                return json.loads(stripped[start:i+1])
    raise ValueError("JSON no balanceado")


def anotar_pieza(image_path: Path, bbox_norm: tuple, descripcion: str,
                 api_key: Optional[str] = None) -> dict:
    """
    Llama a Claude con el crop + descripción y devuelve un dict con la pieza
    y metadatos de uso (tokens, modelo).

    Retorno: {"pieza": {...}, "_meta": {"input_tokens": ..., "output_tokens": ...}}
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY")
    if not descripcion or not descripcion.strip():
        raise ValueError("Descripción vacía")

    b64, mime, (w, h) = _encode_crop_from_bbox(image_path, bbox_norm)
    client = anthropic.Anthropic(api_key=api_key)

    msg = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text",
                 "text": f"Descripción del usuario:\n\"\"\"\n{descripcion.strip()}\n\"\"\"\n\n"
                         "Devuelve SOLO el JSON de esta pieza."},
            ],
        }],
    )

    raw = "".join(b.text for b in msg.content if b.type == "text")
    pieza = _extract_json(raw)

    return {
        "pieza": pieza,
        "_meta": {
            "model": MODEL,
            "crop_size": [w, h],
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
            "cache_read_input_tokens": getattr(msg.usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens": getattr(msg.usage, "cache_creation_input_tokens", 0),
        },
    }
