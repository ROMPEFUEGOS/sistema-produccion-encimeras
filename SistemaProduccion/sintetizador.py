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

# Archivo de reglas del negocio — se inyecta en el system prompt si existe
REGLAS_FILE = Path(__file__).parent / "reglas_negocio.md"


def _leer_reglas_negocio() -> str:
    """Lee el archivo de reglas del negocio si existe, devuelve string vacío si no."""
    if REGLAS_FILE.exists():
        return REGLAS_FILE.read_text(encoding="utf-8").strip()
    return ""


def _build_system_prompt(base: str) -> list[dict]:
    """Construye el system prompt como lista de bloques, con reglas_negocio.md al final."""
    reglas = _leer_reglas_negocio()
    bloques = [{"type": "text", "text": base,
                "cache_control": {"type": "ephemeral"}}]
    if reglas:
        bloques.append({"type": "text",
                        "text": f"\n\n=== REGLAS ACUMULADAS DEL NEGOCIO "
                                f"(lee con prioridad — sobrescriben al prompt base si hay conflicto) ===\n\n{reglas}"})
    return bloques


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

**REGLA CRÍTICA sobre contornos de pieza**:

> **"Si van separadas se dibujan separadas."** Una pieza = un único contorno cerrado
> en la nota. Varias piezas = varios contornos dibujados por separado.
>
> - NO interpretes escuadras internas, marcas de ángulo, líneas diagonales en medio
>   del dibujo o cualquier señal interna como "división de una pieza en dos".
>   Eso marca uniones con piezas adyacentes (que están dibujadas aparte), pilares,
>   referencias de montaje o pliegues visuales, pero la pieza sigue siendo UNA.
> - `forma = "L"` o `"U"` solo cuando el CONTORNO EXTERIOR dibujado realmente describe
>   esa forma (cambio real de dirección a lo largo del perímetro). Si el contorno
>   exterior es rectangular aunque tenga marcas interiores, `forma = "rectangular"`.
> - Si el usuario dibujó 2 rectángulos separados, son 2 piezas, aunque uno toque al
>   otro y sumen medidas coherentes entre ellos.
> - En caso de duda, CONFÍA en que si hubiera dos piezas estarían dibujadas como
>   contornos separados. Solo agrupa lo que el dibujo ya agrupa.

**Otras convenciones**:
- Inglete por defecto 45.5° (holgura de montaje). Si no se dice ángulo pero hay
  inglete, usa 45.5.
- Bisel: ángulo y profundidad variables, siempre que el usuario lo especifique.
- Pulido: post-proceso manual, sin ángulo.
- Aristas de una pieza: frente (lado visible inferior), fondo (pegado a pared),
  cabeza_izq, cabeza_der.
- Encimera: ancho_mm = fondo (profundidad). Chapeado: alto_mm = altura vertical.
- "B/E" o "bajoencimera" → subtipo="bajo_encimera"; "SE" o "sobre" → "sobre_encimera".
- "568-" (guión al final) → tiene_guion=true, se resta grosor+2mm del material.

### Contorno personalizado (obligatorio si la pieza NO es rectangular)

Cuando `forma != "rectangular"` (L, U, trapezoidal, irregular, con chaflán, con
esquina redondeada, con escalón, etc.), DEBES emitir el campo `contorno_custom`
con los vértices ordenados en sentido **antihorario (CCW)** empezando por la
esquina INFERIOR-IZQUIERDA.

Schema de `contorno_custom`:
```
{
  "vertices_mm": [[x0, y0], [x1, y1], ..., [xN, yN]],
  "radios_esquina_mm": [r0, r1, ..., rN]  // radio de fillet en cada vértice, 0 si es esquina viva
  "acabados_contorno": [
    {"tipo": "inglete"|"bisel"|"pulido"|null, "angulo": ..., "profundidad_mm": ...},
    ...  // uno por cada arista: la arista i va de vertice[i] a vertice[(i+1)%N]
  ]
}
```

Coordenadas en mm, origen = esquina inferior-izquierda de la pieza (0,0). Y
creciente hacia el fondo (pared), X creciente hacia la derecha.

Si una pieza rectangular necesita solo `acabados_aristas` (frente/fondo/cabezas),
no emitas `contorno_custom`. Si la forma es no-rectangular, emite `contorno_custom`
Y NO llenes `acabados_aristas` (los acabados van en `acabados_contorno`).

### Ejemplos de contornos

**1. Encimera trapezoidal** (pieza #2 de T3217): lado izq vertical 860mm, sup
1335mm, inf 1165mm, lado der diagonal:
```
"contorno_custom": {
  "vertices_mm": [[0,0], [1165,0], [1335,860], [0,860]],
  "radios_esquina_mm": [0, 0, 0, 0],
  "acabados_contorno": [
    {"tipo": "pulido"},     // arista inferior (frente)
    {"tipo": null},          // arista derecha diagonal (queda a copete, sin pulir)
    {"tipo": "pulido"},     // arista superior
    {"tipo": "pulido"}      // arista izquierda (cabeza izq)
  ]
}
```

**2. Encimera en L** (ancho total 2400, alto total 2200; tramo horizontal
2400×600, tramo vertical 600×2200):
```
"contorno_custom": {
  "vertices_mm": [[0,0], [2400,0], [2400,600], [600,600], [600,2200], [0,2200]],
  "radios_esquina_mm": [0, 0, 0, 0, 0, 0],
  "acabados_contorno": [
    {"tipo": "pulido"}, {"tipo": "pulido"}, {"tipo": null},
    {"tipo": null}, {"tipo": "pulido"}, {"tipo": "pulido"}
  ]
}
```

**3. Encimera con esquina redondeada** (rect 1500×600 con esquina sup-der r=50mm):
```
"contorno_custom": {
  "vertices_mm": [[0,0], [1500,0], [1500,600], [0,600]],
  "radios_esquina_mm": [0, 0, 50, 0],
  "acabados_contorno": [
    {"tipo": "pulido"}, {"tipo": null}, {"tipo": null}, {"tipo": null}
  ]
}
```

**4. Encimera con chaflán 45° en esquina** (rect 1500×600, chaflán 100mm×100mm
en esquina sup-der):
```
"contorno_custom": {
  "vertices_mm": [[0,0], [1500,0], [1500,500], [1400,600], [0,600]],
  "radios_esquina_mm": [0, 0, 0, 0, 0],
  "acabados_contorno": [
    {"tipo": "pulido"}, {"tipo": null}, {"tipo": "pulido"},  // el chaflán suele ir pulido
    {"tipo": null}, {"tipo": null}
  ]
}
```

**5. Encimera con escalón para columna** (2400×600 con muesca rectangular
400×100 en la pared a 800mm del borde izq):
```
"contorno_custom": {
  "vertices_mm": [[0,0], [2400,0], [2400,600], [1200,600], [1200,500], [800,500], [800,600], [0,600]],
  "radios_esquina_mm": [0, 0, 0, 0, 0, 0, 0, 0],
  "acabados_contorno": [
    {"tipo": "pulido"}, {"tipo": null}, {"tipo": null},
    {"tipo": null}, {"tipo": null}, {"tipo": null},
    {"tipo": null}, {"tipo": null}
  ]
}
```

**Reglas de dibujo del contorno**:
- Sentido antihorario (CCW): inferior→derecha→superior→izquierda.
- Primer vértice: esquina inferior-izquierda (0,0).
- Si la nota del usuario da medidas parciales (ej "1335 arriba, 1165 abajo"),
  deduce los vértices completos manteniendo coherencia del polígono.
- Si hay descuadros que afectan la geometría, INCLÚYELOS en los vértices (no
  uses descuadro_*_mm; el polígono ya los contiene).
- Las aristas diagonales se nombran por los vértices que unen (ej "1-2").

### Formato de respuesta

SOLO JSON válido, sin prosa alrededor, sin bloques ```:

{
  "piezas": [
    {
      "tipo": "encimera|chapeado|copete|rodapie|isla|costado|pilastra|paso|tabica|zocalo|gama|dintel|antepecho|otro",
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
  "razonamiento_global": "Análisis general de 2-3 frases...",
  "anotaciones_contextuales_ids": [1, 5, 8],
  "cliente": "...", "material": "...", "numero": "...",
  "grosor_mm": 20
}

### anotaciones_contextuales_ids

Lista las IDs de anotaciones que SON contexto global (símbolos, convenciones,
correcciones generales) y que por tanto NO corresponden a ninguna pieza concreta.

### ⚠ Metadatos top-level (rellena todos los que aparezcan en la libreta/nota)

- **numero**: nº de medida (ej "J0317", "T7060", "V0275")
- **referencia_cliente_final**: nº de pedido externo (ej "18422")
- **cliente_final**: nombre del cliente final (quien recibe la encimera)
- **cliente_intermedio**: distribuidor/mueblero (Valmi, Milano, ACyC, Cocimoble…)
- **tlf_cliente_final** / **tlf_cliente_intermedio**: teléfonos si aparecen
- **direccion**: dirección + ciudad de la obra
- **fecha_medicion**: fecha (dd/mm/aaaa o aaaa-mm-dd)
- **tomo_medidas**: iniciales del operario
- **material**: nombre ("Belvedere", "Silvestre", "Dekton Entzo"…)
- **grosor_mm**: grosor del material en mm (20, 12, 30). CRÍTICO: global del
  pedido. NUNCA lo metas en alto_mm/ancho_mm de piezas.
- **acabado_superficie**: "pulido" | "apomazado" | "abujardado" | "flameado" |
  "envejecido" | "natural" (default "pulido" si no se indica)
- **tipo_trabajo**: array con tags marcados, cualquiera de:
  `cocina_encimera`, `cocina_encimera_chapeado`, `cocina_isla`,
  `cocina_reposicion`, `bano_encimera`, `bano_plato_ducha`,
  `bano_revestimiento`, `recercado_ventana`, `recercado_puerta`,
  `escalera_peldanos`, `escalera_rodapie`, `revestimiento_fachada`,
  `lapida_funerario`, `mesa_sobremesa_banco`, `pieza_especial`.
- **cliente** (legacy, alias de cliente_final): emítelo también por compat.

### ⚠ Dimensiones por tipo de pieza (importante, evita errores en DXF)

| Tipo | `largo_mm` | `ancho_mm` | `alto_mm` |
|------|------------|------------|-----------|
| encimera / isla / cascada | largo | **fondo** (pared→frente) | null |
| chapeado / frontal / pilastra | largo horizontal | null | **altura vertical visible** |
| costado (cascada lateral isla) | largo | **fondo** (coincide encimera) | null |
| copete | largo | null | **altura** (típica 50) |
| rodapié / zócalo | largo | null | **altura** (típica 95-100) |

Si la altura de rodapié/copete/chapeado no aparece en la nota, `alto_mm = null`
y menciona "FALTA: altura" en razonamiento de esa pieza.
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

    # Streaming obligatorio para outputs largos (SDK lo exige si max_tokens alto).
    with client.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=_build_system_prompt(SYSTEM_PROMPT),
        messages=[{"role": "user", "content": content}],
    ) as stream:
        for _ in stream.text_stream:
            pass  # acumulación interna del SDK
        msg = stream.get_final_message()

    raw = "".join(b.text for b in msg.content if b.type == "text")
    stop_reason = getattr(msg, "stop_reason", None)
    try:
        data = _extract_json(raw)
    except Exception as e:
        dump_path = Path("/tmp") / f"sintetizar_raw_{msg.id[-8:]}.txt"
        dump_path.write_text(f"stop_reason: {stop_reason}\nusage: {msg.usage}\n\n{raw}",
                             encoding="utf-8")
        raise ValueError(
            f"Parse falló ({e}). stop_reason={stop_reason}. "
            f"Respuesta raw en {dump_path}. "
            f"Output tokens: {msg.usage.output_tokens}."
        )

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


REFINAR_SYSTEM = """Eres el mismo experto en fabricación de encimeras. En una llamada anterior
sintetizaste una lista de piezas a partir de las anotaciones del usuario. Ahora el
usuario te envía una CORRECCIÓN en lenguaje natural (ej: "la pieza 3 está mal,
debería ser 2450 no 2540"). Tu tarea es devolver la lista COMPLETA de piezas
actualizada aplicando la corrección y MANTENIENDO COHERENCIA con el resto.

Reglas:
- Devuelve SIEMPRE la lista completa (todas las piezas, no solo las modificadas).
- Si la corrección invalida piezas previas, elimínalas. Si genera nuevas, añádelas.
- Mantén los campos `razonamiento` y `anotaciones_ids` de cada pieza, actualizándolos
  si la corrección los afecta.
- En el `razonamiento_global`, AÑADE una línea al final indicando qué se cambió en
  este refinamiento (ej: "Refinado 2026-04-19: pieza #3 largo corregido a 2450").
- Si la corrección enseña una convención nueva que aplica en general (no solo a esta
  orden), MENCIÓNALA en `razonamiento_global` con el prefijo "REGLA CANDIDATA:" para
  que el operario pueda añadirla luego a reglas_negocio.md.
- Sigue todas las demás reglas del system prompt base y del archivo de reglas.

Formato: MISMO JSON que sintetizar_piezas, DEVUELVE TODOS LOS CAMPOS top-level:
  - piezas (array completa, no solo las cambiadas)
  - razonamiento_global (con línea al final indicando qué se cambió en este refinamiento)
  - anotaciones_contextuales_ids
  - cliente, numero, material
  - **grosor_mm** (IMPORTANTE: si el usuario o el razonamiento menciona grosor del
    material, emítelo al top-level; no omitas este campo)

SOLO JSON, sin prosa fuera.
"""


def refinar_piezas(piezas_actuales: list[dict],
                   anotaciones: list[dict],
                   correccion: str,
                   imagenes_dir: Path,
                   razonamiento_global_actual: str = "",
                   api_key: Optional[str] = None) -> dict:
    """
    Aplica una corrección en lenguaje natural a las piezas sintetizadas anteriormente.
    Devuelve la nueva lista de piezas completa.
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY")
    if not correccion or not correccion.strip():
        raise ValueError("Corrección vacía")

    client = anthropic.Anthropic(api_key=api_key)

    content = []

    # Imágenes completas (menos que en síntesis inicial para ahorrar tokens)
    imgs_por_peso = []
    for p in imagenes_dir.iterdir():
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            imgs_por_peso.append((p.stat().st_size, p))
    imgs_por_peso.sort(reverse=True)
    for _, p in imgs_por_peso[:2]:
        img = _resize_img(Image.open(p).convert("RGB"), MAX_IMG_SIDE)
        b64, mime = _encode_image(img)
        content.append({"type": "text", "text": f"Imagen: {p.name}"})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": b64}})

    content.append({"type": "text",
                    "text": "=== ANOTACIONES DEL USUARIO (referencia) ==="})
    for a in anotaciones:
        content.append({"type": "text",
                        "text": f"#{a.get('id')} ({a.get('imagen')}): {a.get('descripcion','')[:500]}"})

    content.append({"type": "text",
                    "text": f"\n=== SÍNTESIS ANTERIOR ===\n"
                            f"razonamiento_global: {razonamiento_global_actual}\n\n"
                            f"piezas actuales:\n{json.dumps(piezas_actuales, ensure_ascii=False, indent=2)}"})

    content.append({"type": "text",
                    "text": f"\n=== CORRECCIÓN DEL USUARIO ===\n{correccion.strip()}\n\n"
                            f"Devuelve el JSON completo actualizado."})

    with client.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=_build_system_prompt(REFINAR_SYSTEM),
        messages=[{"role": "user", "content": content}],
    ) as stream:
        for _ in stream.text_stream:
            pass
        msg = stream.get_final_message()

    raw = "".join(b.text for b in msg.content if b.type == "text")
    try:
        data = _extract_json(raw)
    except Exception as e:
        dump_path = Path("/tmp") / f"refinar_raw_{msg.id[-8:]}.txt"
        dump_path.write_text(raw, encoding="utf-8")
        raise ValueError(f"Parse falló ({e}). Raw en {dump_path}.")

    data["_meta"] = {
        "model":         MODEL,
        "input_tokens":  msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
    }
    return data
