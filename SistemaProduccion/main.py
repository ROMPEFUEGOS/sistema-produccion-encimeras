"""
main.py — Orquestador del Sistema de Diseño de Producción

Flujo completo:
  1. Busca la tarjeta en Trello (COBRADO / COBRADO 2025)
  2. Descarga las imágenes de la tarjeta
  3. Extrae medidas con Claude Vision
  4. Genera DXF de producción
  5. (Opcional) Genera PDF con auto-dimensioner
  6. (Opcional) Sube el PDF a la tarjeta de Trello

Uso:
    python3 main.py T7060
    python3 main.py T7060 --guardar
    python3 main.py T7060 --guardar --pdf
    python3 main.py T7060 --guardar --pdf --subir
"""

import os
import sys
import json
import subprocess
from pathlib import Path

# Añadir el directorio padre al path para imports
_BASE = Path(__file__).parent.parent
sys.path.insert(0, str(_BASE))
sys.path.insert(0, str(Path(__file__).parent))

from trello_client import cargar_config, TrelloClient
from medidas_extractor import extraer_medidas, guardar_medidas
from dxf_produccion import generar_dxf


# ── Config ─────────────────────────────────────────────────────────────────────

CARPETA_DISEÑOS = _BASE / "1-DISEÑOS MAQUINA"
CARPETA_TMP     = Path("/tmp/sistema_produccion")
DIMENSIONER     = _BASE / "dxf_auto_dim_v1.3.py"

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not API_KEY:
    raise RuntimeError("Falta variable de entorno ANTHROPIC_API_KEY")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _titulo_carpeta(card_name: str) -> str:
    """Limpia el nombre de tarjeta para usarlo como nombre de carpeta."""
    import re, unicodedata
    # Eliminar caracteres problemáticos pero mantener la estructura
    nombre = unicodedata.normalize("NFC", card_name)
    nombre = re.sub(r'[<>:"/\\|?*]', '-', nombre)
    return nombre[:120].strip()


def _grosor_del_nombre(nombre: str) -> int | None:
    """Intenta extraer el grosor (mm) del nombre de la tarjeta."""
    import re
    m = re.search(r'(\d+)\s*(?:mm|cm)', nombre, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 'cm' in m.group(0).lower():
            val *= 10
        if val in (8, 12, 20, 30, 40):
            return val
    # Buscar "2cm", "12mm", etc.
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*cm', nombre, re.IGNORECASE)
    if m:
        val = round(float(m.group(1).replace(',', '.')) * 10)
        return val
    return None


# ── Pipeline principal ─────────────────────────────────────────────────────────

def procesar(numero: str, guardar: bool = True, pdf: bool = False,
             subir: bool = False, verbose: bool = True) -> dict:
    """
    Procesa un trabajo completo de inicio a fin.
    Devuelve dict con rutas generadas y metadatos.
    """
    resultado = {"numero": numero, "ok": False}

    # 1. Buscar tarjeta en Trello
    if verbose: print(f"\n{'='*60}")
    if verbose: print(f"  {numero}")
    if verbose: print(f"{'='*60}")
    if verbose: print("1. Buscando en Trello...")

    trello = cargar_config()
    card = trello.buscar_tarjeta(numero)
    if not card:
        print(f"  ✗ Tarjeta no encontrada para '{numero}'")
        resultado["error"] = "tarjeta_no_encontrada"
        return resultado

    if verbose: print(f"  ✓ {card['name']}")
    resultado["card_name"] = card["name"]

    # Carpeta de trabajo
    if guardar:
        titulo = _titulo_carpeta(card["name"])
        carpeta = CARPETA_DISEÑOS / titulo
    else:
        carpeta = CARPETA_TMP / numero
    carpeta.mkdir(parents=True, exist_ok=True)

    # 2. Descargar adjuntos
    if verbose: print("2. Descargando adjuntos...")
    adjs = trello.obtener_adjuntos(card["id"])
    info = trello.clasificar_adjuntos(adjs)

    imagenes = []
    for att in info["imagenes"]:
        dest = carpeta / att["name"]
        if not dest.exists():
            try:
                trello._download(att["url"], trello.api_key, trello.token, dest)
                if verbose: print(f"  ↓ {att['name']} ({att.get('bytes',0)//1024}KB)")
            except Exception as e:
                print(f"  ✗ {att['name']}: {e}")
                continue
        imagenes.append(dest)

    if not imagenes:
        print("  ✗ No hay imágenes en la tarjeta — sin nota de medidas.")
        resultado["error"] = "sin_imagenes"
        return resultado

    resultado["imagenes"] = [str(p) for p in imagenes]

    # 3. Extraer medidas con Claude Vision
    if verbose: print(f"3. Extrayendo medidas ({len(imagenes)} imagen(es))...")
    grosor = _grosor_del_nombre(card["name"])
    if verbose and grosor: print(f"  Grosor detectado: {grosor}mm")

    medidas_path = carpeta / f"{numero}_medidas.json"

    if medidas_path.exists():
        if verbose: print("  → Usando extracción previa (ya existe _medidas.json)")
        with open(medidas_path, encoding="utf-8") as f:
            medidas = json.load(f)
    else:
        try:
            medidas = extraer_medidas(imagenes, API_KEY, grosor_mm=grosor)
        except Exception as e:
            print(f"  ✗ Error extrayendo medidas: {e}")
            resultado["error"] = str(e)
            return resultado

        if guardar:
            guardar_medidas(medidas, carpeta, numero)
            if verbose: print(f"  ✓ Medidas guardadas: {medidas_path.name}")

    tokens_in  = medidas.get("_tokens_input", 0)
    tokens_out = medidas.get("_tokens_output", 0)
    npiezas    = len(medidas.get("piezas", []))
    confianza  = medidas.get("confianza", "?")
    if verbose:
        print(f"  ✓ {npiezas} piezas | confianza={confianza} | "
              f"tokens: {tokens_in}↑ {tokens_out}↓")

    for adv in medidas.get("advertencias", []):
        if verbose: print(f"  ⚠ {adv}")

    resultado["medidas"] = medidas
    resultado["piezas"]  = npiezas

    # 4. Generar DXF de producción
    if verbose: print("4. Generando DXF de producción...")
    dxf_nombre = _titulo_carpeta(card["name"]) + ".dxf"
    dxf_path   = carpeta / dxf_nombre

    try:
        generar_dxf(medidas, dxf_path)
        resultado["dxf"] = str(dxf_path)
        if verbose: print(f"  ✓ {dxf_path.name}")
    except Exception as e:
        print(f"  ✗ Error generando DXF: {e}")
        resultado["error_dxf"] = str(e)
        return resultado

    # 5. Generar PDF con auto-dimensioner (opcional)
    if pdf and DIMENSIONER.exists():
        if verbose: print("5. Generando PDF acotado...")
        try:
            r = subprocess.run(
                ["python3", str(DIMENSIONER), str(dxf_path)],
                capture_output=True, text=True, timeout=60
            )
            pdf_path = dxf_path.with_suffix(".pdf")
            if pdf_path.exists():
                resultado["pdf"] = str(pdf_path)
                if verbose: print(f"  ✓ {pdf_path.name}")
            else:
                if verbose: print(f"  ⚠ El dimensioner no generó PDF")
        except Exception as e:
            print(f"  ✗ Error generando PDF: {e}")
    elif pdf:
        print("  ⚠ dxf_auto_dim_v1.3.py no encontrado — PDF no generado")

    # 6. Subir PDF a Trello (opcional)
    if subir and resultado.get("pdf"):
        if verbose: print("6. Subiendo PDF a Trello...")
        # Reutilizamos TrelloUploader del módulo existente
        try:
            from trello_uploader import TrelloUploader
            uploader = TrelloUploader(
                api_key=trello.api_key,
                token=trello.token,
                board_name="Planificador de Trabajo"
            )
            uploader._board_id = card.get("idBoard", "62a382a99f14ff1369e0da58")
            uploader._attach_pdf(card["id"], resultado["pdf"])
            if verbose: print("  ✓ PDF subido a Trello")
        except Exception as e:
            print(f"  ✗ Error subiendo PDF: {e}")

    resultado["ok"] = True
    return resultado


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 main.py <NUMERO> [--guardar] [--pdf] [--subir]")
        print("  NUMERO: número de medida (ej: T7060, V0275, J0335)")
        print("  --guardar: guarda resultados en 1-DISEÑOS MAQUINA/")
        print("  --pdf:     genera PDF acotado con el auto-dimensioner")
        print("  --subir:   sube el PDF a la tarjeta de Trello")
        sys.exit(1)

    numero  = sys.argv[1]
    guardar = "--guardar" in sys.argv
    pdf     = "--pdf"     in sys.argv
    subir   = "--subir"   in sys.argv

    resultado = procesar(numero, guardar=guardar, pdf=pdf, subir=subir)

    if resultado.get("ok"):
        print(f"\n✓ Completado: {numero}")
        if resultado.get("dxf"):    print(f"  DXF: {resultado['dxf']}")
        if resultado.get("pdf"):    print(f"  PDF: {resultado['pdf']}")
    else:
        print(f"\n✗ Error: {resultado.get('error', 'desconocido')}")
        sys.exit(1)
