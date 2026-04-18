"""
sintetizador.py — Fase 2 del flujo de anotación.

Toma todas las ANOTACIONES (contexto que el usuario ha ido marcando sobre la nota
manuscrita — medidas, símbolos, aclaraciones, piezas completas, correcciones) y las
IMÁGENES completas de la tarjeta, y devuelve una lista coherente de piezas finales
con razonamiento por cada una.

Diferencia clave respecto a anotador.py:
  - Las anotaciones son EVIDENCIA, no son "una pieza cada una"
  - El modelo analiza todo en conjunto y deduce las piezas reales
  - Cada pieza lleva razonamiento + IDs de anotaciones que la sustentan
  - Si una medida no aparece en ninguna anotación, deja null y lo explica
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
MAX_IMG_SIDE  = 1600
MAX_CROP_SIDE = 1200
MAX_IMAGENES_COMPLETAS = 3   # como mucho 3 imágenes completas (las más pesadas)


SYSTEM_PROMPT = """Eres un experto en fabricación de encimeras de cocina de piedra natural y porcelánico.

El dueño del taller ha revisado una nota manuscrita de medidas y te ha enviado:

1. **Anotaciones de contexto**: múltiples recortes de la(s) foto(s) con descripciones
   en texto libre. Algunas anotaciones son piezas completas ("Encimera 3000×620, frente
   pulido"), pero OTRAS son solo medidas específicas ("Este 568- significa que al chapeado
   hay que restarle 22mm del grosor"), símbolos ("Las X marcan zonas pulidas"), correcciones
   ("Aquí me equivoqué antes, el largo es 2450 no 2540") o aclaraciones generales
   ("Esta L de rodapiés significa que van ingletadas entre sí").

2. **Imágenes completas** de la nota para que veas el plano general.

## Tu tarea

Sintetizar toda la evidencia y devolver la lista COHERENTE de piezas finales a fabricar.

### Reglas estrictas (producción, no presupuesto)

- **NO inventes medidas**. Si una dimensión no aparece explícita en ninguna anotación
  ni es legible en la imagen con certeza, ponla en `null` y añade en el razonamiento
  "FALTA: {qué} — no aparece en ninguna anotación".
- **Agrupa anotaciones relacionadas**: si varias anotaciones aclaran la misma pieza
  (una dice el largo, otra el pulido, otra el hueco), fusiona la info en una sola
  pieza con razonamiento que cite todas esas anotaciones.
- **Descarta ruido**: anotaciones que solo explican símbolos globales ("las X son
  pulido") NO son piezas — úsalas como contexto para interpretar otras anotaciones.
- **Correcciones tienen prioridad**: si el usuario escribió "corrijo la anterior: el
  largo real es 2450", usa 2450 y menciona la corrección en el razonamiento.

### Convenciones del negocio
- Inglete por defecto 45.5° (holgura de montaje). Si no se dice ángulo pero hay
  inglete, usa 45.5.
- Bisel: ángulo y profundidad variables, siempre que el usuario lo especifique.
- Pulido: post-proceso manual, sin ángulo.
- Aristas de una pieza: frente (lado visible inferior), fondo (pegado a pared),
  cabeza_izq, cabeza_der.
- Encimera: ancho_mm = fondo (profundidad). Chapeado: alto_mm = altura vertical.
- "B/E" o "bajoencimera" → subtipo="bajo_encimera"; "SE" o "sobre" → "sobre_encimera".
- "568-" (guión al final) → tiene_guion=true, se resta grosor+2mm del material.

### Formato de respuesta

SOLO JSON válido, sin prosa alrededor, sin bloques ```:

{
  "piezas": [
    {
      "tipo": "encimera|chapeado|copete|rodapie|isla|costado|pilastra|paso|tabica|zocalo|otro",
      "forma": "rectangular|L|U|irregular",
      "largo_mm": ...,
      "ancho_mm": ...,
      "alto_mm": ...,
      "descuadro_izq_mm": ..., "descuadro_der_mm": ...,
      "descuadro_sup_mm": null, "descuadro_inf_mm": null,
      "tiene_guion": false,
      "zona": null,
      "pulido_vuelo_mm": null,
      "acabados_aristas": {
        "frente":     {"tipo": ..., "angulo": ..., "profundidad_mm": ...},
        "fondo":      {"tipo": ..., "angulo": ..., "profundidad_mm": ...},
        "cabeza_izq": {"tipo": ..., "angulo": ..., "profundidad_mm": ...},
        "cabeza_der": {"tipo": ..., "angulo": ..., "profundidad_mm": ...}
      },
      "notas": "...",
      "huecos": [...],
      "razonamiento": "Pieza deducida de anotaciones #3 (medida total) + #7 (pulido frente) + #12 (hueco fregadero). FALTA: ancho encimera — no aparece en ninguna anotación.",
      "anotaciones_ids": [3, 7, 12]
    }
  ],
  "razonamiento_global": "Análisis general de 2-3 frases: cuántas piezas totales, dudas, anotaciones ignoradas (y por qué), piezas con información incompleta que requieren más anotaciones del usuario.",
  "anotaciones_contextuales_ids": [1, 5, 8]
}

### anotaciones_contextuales_ids

Lista las IDs de anotaciones que SON contexto global (símbolos, convenciones,
correcciones generales) y que por tanto NO corresponden a ninguna pieza concreta.
Sirve al usuario para saber que las viste y te fueron útiles.
"""


# ── Utilidades ────────────────────────────────────────────────────────────────

def _resize_img(img: Image.Image, max_side: int) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    if w >= h:
        return img.resize((max_side, int(h * max_side / w)), Image.LANCZOS)
    return img.resize((int(w * max_side / h), max_side), Image.LANCZOS)


def _encode_image(img: Image.Image) -> tuple[str, str]:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


def _crop_from_bbox(img_path: Path, bbox_norm: tuple[float, float, float, float]) -> Image.Image:
    img = Image.open(img_path).convert("RGB")
    W, H = img.size
    x1 = max(0, int(bbox_norm[0] * W))
    y1 = max(0, int(bbox_norm[1] * H))
    x2 = min(W, int(bbox_norm[2] * W))
    y2 = min(H, int(bbox_norm[3] * H))
    if x2 <= x1 + 5 or y2 <= y1 + 5:
        raise ValueError(f"Bounding box demasiado pequeño: {bbox_norm}")
    crop = img.crop((x1, y1, x2, y2))
    return _resize_img(crop, MAX_CROP_SIDE)


def _extract_json(text: str) -> dict:
    text = text.strip()
    stripped = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    if start < 0:
        raise ValueError(f"No se encontró JSON: {text[:300]}")
    depth = 0
    for i in range(start, len(stripped)):
        if stripped[i] == "{":
            depth += 1
        elif stripped[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(stripped[start:i+1])
    raise ValueError("JSON no balanceado")


# ── API pública ───────────────────────────────────────────────────────────────

def sintetizar_piezas(anotaciones: list[dict],
                      imagenes_dir: Path,
                      api_key: Optional[str] = None,
                      incluir_imagenes_completas: bool = True) -> dict:
    """
    Analiza todas las anotaciones + imágenes y devuelve la lista de piezas finales.

    Args:
        anotaciones: lista de dicts con {id, imagen, bbox_norm, descripcion, ...}
        imagenes_dir: carpeta donde están las imágenes originales
        api_key: Anthropic key (o env var)
        incluir_imagenes_completas: si True, envía también las imágenes completas
            (hasta MAX_IMAGENES_COMPLETAS, las más pesadas) como vista de conjunto.

    Returns: {"piezas": [...], "razonamiento_global": "...",
              "anotaciones_contextuales_ids": [...], "_meta": {...}}
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY")
    if not anotaciones:
        raise ValueError("No hay anotaciones para sintetizar")

    client = anthropic.Anthropic(api_key=api_key)

    # Construir contenido multimodal: imágenes completas primero, luego crops
    content = []

    if incluir_imagenes_completas:
        imgs_por_peso = []
        for p in imagenes_dir.iterdir():
            if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                imgs_por_peso.append((p.stat().st_size, p))
        imgs_por_peso.sort(reverse=True)
        imgs_completas = [p for _, p in imgs_por_peso[:MAX_IMAGENES_COMPLETAS]]

        if imgs_completas:
            content.append({"type": "text",
                            "text": "=== IMÁGENES COMPLETAS DE LA NOTA (vista de conjunto) ==="})
            for p in imgs_completas:
                img = _resize_img(Image.open(p).convert("RGB"), MAX_IMG_SIDE)
                b64, mime = _encode_image(img)
                content.append({"type": "text", "text": f"Imagen: {p.name}"})
                content.append({"type": "image",
                                "source": {"type": "base64", "media_type": mime, "data": b64}})

    # Cada anotación: texto de descripción + crop
    content.append({"type": "text",
                    "text": f"\n=== {len(anotaciones)} ANOTACIONES DEL USUARIO ==="})
    for a in anotaciones:
        aid  = a.get("id", "?")
        desc = a.get("descripcion", "")
        imagen = a.get("imagen")
        bbox   = a.get("bbox_norm")

        content.append({"type": "text",
                        "text": f"\n--- Anotación #{aid} (imagen: {imagen}) ---\nDescripción del usuario:\n\"{desc}\""})
        try:
            if imagen and bbox:
                crop = _crop_from_bbox(imagenes_dir / imagen, tuple(bbox))
                b64, mime = _encode_image(crop)
                content.append({"type": "image",
                                "source": {"type": "base64", "media_type": mime, "data": b64}})
        except Exception as e:
            content.append({"type": "text",
                            "text": f"(error preparando crop: {e})"})

    content.append({"type": "text",
                    "text": "\n=== FIN ===\n\nSintetiza. Devuelve solo el JSON."})

    msg = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
    )

    raw = "".join(b.text for b in msg.content if b.type == "text")
    data = _extract_json(raw)

    data["_meta"] = {
        "model":         MODEL,
        "input_tokens":  msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
        "cache_read_input_tokens":     getattr(msg.usage, "cache_read_input_tokens", 0),
        "cache_creation_input_tokens": getattr(msg.usage, "cache_creation_input_tokens", 0),
        "n_anotaciones": len(anotaciones),
        "n_imagenes_completas": MAX_IMAGENES_COMPLETAS if incluir_imagenes_completas else 0,
    }
    return data
