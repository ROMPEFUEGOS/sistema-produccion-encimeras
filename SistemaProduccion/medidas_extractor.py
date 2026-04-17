"""
medidas_extractor.py — Claude Vision para extraer dimensiones de notas
manuscritas de medición de cocinas de piedra (encimeras, chapeados, etc.)

Entrada: lista de rutas de imagen (fotos Trello de la nota de medidas)
Salida:  dict JSON con piezas, huecos, descuadros, material, cliente, etc.
"""

import base64
import json
import re
from pathlib import Path
from typing import Optional
from PIL import Image
import io

try:
    import anthropic
except ImportError:
    anthropic = None


# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Eres un experto en lectura de notas de medición manuscritas para fabricación
de encimeras de cocina y revestimientos de piedra natural y porcelánico.

Tu tarea es analizar fotos de notas de medición dibujadas a mano alzada en papel cuadriculado
y extraer TODOS los datos necesarios para fabricar las piezas.

══════════════════════════════════════════════════════
CONVENCIONES DE LAS NOTAS DE MEDICIÓN
══════════════════════════════════════════════════════

TIPOS DE PIEZA:
• encimera      — superficie horizontal sobre muebles bajos. Fondo habitual 600-650mm.
• chapeado      — panel vertical entre encimera y muebles altos (= frontal).
• copete        — franja estrecha pegada a pared, H típica 50mm (puede variar).
• rodapie       — franja al pie de los muebles bajos, H típica 70-100mm.
• isla          — encimera central sin apoyo en paredes.
• costado       — panel vertical lateral de isla (cascada/waterfall).
• pilastra      — revestimiento de arista de pilar.
• paso/tabica   — escalón.
• plato_ducha   — plato de ducha.

FORMAS:
• La encimera está dibujada como rectángulo con sus medidas en mm.
• Una L se dibuja como dos rectángulos unidos en esquina (o en forma de L).
• Las flechas "→2460" indican una medida en esa dirección hasta el límite.
• Descuadros: pequeños números (+3, -7) junto a las esquinas verticales de la pieza.
  Positivo = la pared empuja hacia dentro (pieza más ancha en ese lado).
  Negativo = la pared se aleja (pieza más estrecha en ese lado).
• "escalon." o "escalón" junto a la pieza = tiene descuadro tipo escalón.

HUECOS:
• Placa de cocina: rectángulo marcado dentro de la encimera con sus medidas.
  Si no aparecen medidas, el estándar es 560×490mm.
  Las líneas del hueco de placa se dibujan con guiones (línea de corte = TAB).
• Fregadero: rectángulo con etiqueta "freg", "fregadero", "B/E" (bajo encimera)
  o "Sobre" (sobre encimera). Si no hay medidas, estándar ~490×400mm.
• Grifo: círculo pequeño cerca del fregadero. Hueco de 35mm diámetro.
• Enchufe: círculo marcado con "E" o "enchuf" en el chapeado o encimera.
  Hueco de 70mm diámetro (broca 7cm), capa 1006.

NOTACIÓN "-" (GUIÓN DESPUÉS DEL NÚMERO):
• Ejemplo: "568-" en el chapeado → la medida debe descontarse el grosor del material.
• Si el material tiene 20mm → se resta 22mm (20+2): la pieza real = 568-22 = 546mm.
• Si tiene 12mm → se resta 14mm.
• Si tiene 30mm → se resta 32mm.
• Si no se especifica el grosor aún, déjalo como "568-" en el campo de notas.

ZONAS PULIDAS (X en las líneas):
• Una línea con una X en el centro = esa arista va pulida.
• Una medida pequeña (25-30mm) delimitada por "|X" = vuelo de la encimera (parte pulida
  que sobresale del frente de los muebles). Anota su longitud.

INGLETES:
• "Ing." o "ingletes" junto a una arista = esa arista lleva inglete a 45°.
• En rodapiés: las esquinas dibujadas en "L" significan que las cabezas van ingletadas.

MATERIALES PORCELÁNICOS (Dekton, Coverlam, Neolith, etc.):
• El fregadero va SOBRE encimera (el hueco es para el fregadero apoyado encima).
• Los pilares con chapeado porcelánico llevan ingletes en las esquinas vistas.

══════════════════════════════════════════════════════
FORMATO DE RESPUESTA (JSON estricto)
══════════════════════════════════════════════════════

Devuelve ÚNICAMENTE este JSON, sin texto adicional:

{
  "cliente": "nombre del cliente",
  "numero": "T7060",
  "material": "Belvedere 20mm",
  "notas_generales": "...",
  "confianza": "alta|media|baja",
  "advertencias": ["..."],
  "piezas": [
    {
      "tipo": "encimera|chapeado|copete|rodapie|isla|costado|pilastra|paso|tabica|otro",
      "forma": "rectangular|L|U|irregular",
      "largo_mm": 1180,
      "ancho_mm": 420,
      "alto_mm": null,
      "descuadro_izq_mm": 3,
      "descuadro_der_mm": -7,
      "descuadro_sup_mm": null,
      "descuadro_inf_mm": null,
      "tiene_guion": false,
      "zona": "pared norte|isla|...",
      "pulido_vuelo_mm": 25,
      "ingletes": ["cabeza_izq", "cabeza_der", "frente"],
      "notas": "...",
      "huecos": [
        {
          "tipo": "placa|fregadero|grifo|enchufe",
          "largo_mm": 560,
          "ancho_mm": 490,
          "subtipo": "sobre_encimera|bajo_encimera",
          "posicion": "izquierda|centro|derecha",
          "distancia_frente_mm": 70,
          "distancia_lado_mm": null,
          "notas": "..."
        }
      ]
    }
  ],
  "esquema_pieza_compleja": null
}

REGLAS IMPORTANTES:
1. Todos los valores numéricos en mm (enteros o decimales).
2. Si un valor no aparece claramente, usa null.
3. Para L-shapes: extrae las dos dimensiones generales (largo total × ancho total)
   y anota la forma como "L" con las medidas del recorte en "notas".
4. Si ves varias fotos, extrae datos de LA FOTO DE MEDIDAS MANUSCRITAS.
   Ignora fotos de obra, renders o catálogos de aparatos.
5. Si una medida tiene "-" (guión al final), marca tiene_guion: true en esa pieza.
6. Indica siempre la posición del hueco respecto al frente de la encimera
   (distancia_frente_mm) si aparece en la nota.
"""


# ── Preprocesado de imágenes ───────────────────────────────────────────────────

def _preparar_imagen(path: Path, max_px: int = 1600) -> tuple[str, str]:
    """
    Redimensiona la imagen si es necesario y la codifica en base64.
    Devuelve (base64_data, media_type).
    """
    try:
        img = Image.open(path)
        # Rotar según EXIF si procede
        try:
            from PIL.ExifTags import TAGS
            exif = img._getexif()
            if exif:
                for tag, val in exif.items():
                    if TAGS.get(tag) == 'Orientation':
                        rotations = {3: 180, 6: 270, 8: 90}
                        if val in rotations:
                            img = img.rotate(rotations[val], expand=True)
        except Exception:
            pass

        # Reducir si es muy grande
        w, h = img.size
        if max(w, h) > max_px:
            ratio = max_px / max(w, h)
            img = img.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)

        # Convertir a JPEG
        buf = io.BytesIO()
        img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=85)
        data = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
        return data, "image/jpeg"
    except Exception:
        # Fallback: leer tal cual
        raw = path.read_bytes()
        data = base64.standard_b64encode(raw).decode("utf-8")
        suffix = path.suffix.lower().lstrip(".")
        mtype = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "png": "image/png", "webp": "image/webp"}.get(suffix, "image/jpeg")
        return data, mtype


# ── Extractor principal ────────────────────────────────────────────────────────

def extraer_medidas(
    imagenes: list[Path],
    api_key: str,
    grosor_mm: Optional[int] = None,
    modelo: str = "claude-sonnet-4-6",
    max_imagenes: int = 4,
) -> dict:
    """
    Analiza hasta `max_imagenes` imágenes con Claude Vision y extrae las medidas.

    Args:
        imagenes:    Lista de rutas de imagen, ordenadas por relevancia (mayor=primero).
        api_key:     Anthropic API key.
        grosor_mm:   Grosor del material en mm (para resolver medidas con "-").
                     Si es None se deja sin resolver.
        modelo:      Modelo Claude a usar.
        max_imagenes: Máximo de imágenes a enviar en una sola llamada.

    Returns:
        dict con los datos extraídos.
    """
    if not anthropic:
        raise ImportError("Instala anthropic: pip install anthropic")

    client = anthropic.Anthropic(api_key=api_key)

    # Preparar contenido del mensaje
    content = []

    # Texto introductorio
    grosor_texto = f" El material tiene {grosor_mm}mm de grosor." if grosor_mm else ""
    content.append({
        "type": "text",
        "text": (
            f"Analiza las siguientes imágenes y extrae las medidas de fabricación.{grosor_texto}\n"
            f"Devuelve ÚNICAMENTE el JSON solicitado."
        )
    })

    # Añadir imágenes (máx max_imagenes)
    for img_path in imagenes[:max_imagenes]:
        try:
            b64, mtype = _preparar_imagen(img_path)
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mtype, "data": b64}
            })
            print(f"  + Imagen: {img_path.name} ({len(b64)//1024}KB base64)")
        except Exception as e:
            print(f"  ✗ Error preparando {img_path.name}: {e}")

    if len(content) == 1:
        return {"error": "No se pudieron cargar las imágenes", "piezas": []}

    # Llamada a Claude
    response = client.messages.create(
        model=modelo,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}]
    )

    raw = response.content[0].text.strip()

    # Extraer JSON de la respuesta
    resultado = _parsear_respuesta(raw)

    # Resolver medidas con "-" si tenemos el grosor
    if grosor_mm and resultado.get("piezas"):
        resultado = _resolver_guiones(resultado, grosor_mm)

    resultado["_modelo"] = modelo
    resultado["_tokens_input"]  = response.usage.input_tokens
    resultado["_tokens_output"] = response.usage.output_tokens

    return resultado


def _parsear_respuesta(texto: str) -> dict:
    """Extrae el JSON de la respuesta de Claude."""
    # Buscar bloque JSON entre ```json ... ``` o directamente
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    if m:
        texto = m.group(1)
    else:
        # Intentar encontrar el primer { ... } válido
        start = texto.find("{")
        end   = texto.rfind("}")
        if start != -1 and end != -1:
            texto = texto[start:end+1]

    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        return {
            "error": f"JSON inválido: {e}",
            "raw": texto[:500],
            "piezas": [],
            "advertencias": ["No se pudo parsear la respuesta de Claude"]
        }


def _resolver_guiones(datos: dict, grosor_mm: int) -> dict:
    """
    Aplica la regla del "-": a medidas con tiene_guion=True,
    resta (grosor_mm + 2) del valor correspondiente.
    """
    descuento = grosor_mm + 2
    for pieza in datos.get("piezas", []):
        if not pieza.get("tiene_guion"):
            continue
        # El guión normalmente afecta al alto del chapeado
        if pieza.get("alto_mm"):
            pieza["alto_mm"] = round(pieza["alto_mm"] - descuento, 1)
            pieza.setdefault("notas", "")
            pieza["notas"] += f" [guión resuelto: -{descuento}mm]"
        elif pieza.get("ancho_mm") and pieza.get("tipo") in ("chapeado", "copete"):
            pieza["ancho_mm"] = round(pieza["ancho_mm"] - descuento, 1)
            pieza.setdefault("notas", "")
            pieza["notas"] += f" [guión resuelto: -{descuento}mm]"
    return datos


# ── Guardar resultado ──────────────────────────────────────────────────────────

def guardar_medidas(resultado: dict, carpeta: Path, numero: str) -> Path:
    out = carpeta / f"{numero}_medidas.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    return out


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os
    from trello_client import cargar_config, TrelloClient

    if len(sys.argv) < 2:
        print("Uso: python3 medidas_extractor.py <NUMERO> [--guardar]")
        sys.exit(1)

    numero   = sys.argv[1]
    guardar  = "--guardar" in sys.argv
    api_key  = os.environ.get("ANTHROPIC_API_KEY", "")

    # Buscar en Trello
    trello = cargar_config()
    card   = trello.buscar_tarjeta(numero)
    if not card:
        print(f"No se encontró la tarjeta {numero}")
        sys.exit(1)
    print(f"✓ {card['name']}")

    # Descargar adjuntos
    tmp = Path(f"/tmp/{numero}_adjuntos")
    adjs  = trello.obtener_adjuntos(card["id"])
    info  = trello.clasificar_adjuntos(adjs)

    # Descargar imágenes
    imagenes = []
    for att in info["imagenes"]:
        dest = tmp / att["name"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            trello._download(att["url"], trello.api_key, trello.token, dest)
        imagenes.append(dest)

    if not imagenes:
        print("No hay imágenes en la tarjeta.")
        sys.exit(1)

    print(f"Analizando {len(imagenes)} imagen(es)...")
    resultado = extraer_medidas(imagenes, api_key)

    print(json.dumps(resultado, ensure_ascii=False, indent=2))

    if guardar:
        out = guardar_medidas(resultado, tmp, numero)
        print(f"\nGuardado: {out}")
