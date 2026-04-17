"""
dxf_produccion.py — Genera DXF de producción (formato máquina CNC) a partir
de los datos de medidas extraídos por medidas_extractor.py

Convenciones de capas y tipos de línea (según "Informacion para hacer diseños.docx"):
  Layer 0          → cortes normales con disco
  Layer 0-CON      → fresado (huecos con curvas grandes, r > 20mm)
  Layer 1006       → taladros (enchufes, grifos) — CIRCLE con r=35mm
  Layer 1002       → agrupación de pieza indivisible (envuelve con rectángulo)
  Layer 1007       → guía visual (no se corta) — solo para referencia

Tipos de línea (linetype):
  CONTINUOUS  → corte normal
  HIDDEN      → dirección de herramienta / ingletes
  DASHED      → TAB (el disco se para aquí, ej: cruce de L, cabezas de placa)
  DOTTED      → UTL (último pase lento)

Parámetros de máquina:
  Disco: 3.5mm de ancho
  Separación mínima entre piezas en la misma tabla: 5mm
  Distancia mínima interna de L desde esquina: 50mm
"""

import math
from pathlib import Path
from typing import Optional
import ezdxf
from ezdxf import enums


# ── Constantes ─────────────────────────────────────────────────────────────────

LAYER_CORTE     = "0"          # corte disco normal
LAYER_FRESA     = "0-CON"      # fresado (curvas grandes)
LAYER_TALADRO   = "1006"       # taladros (enchufes, grifos)
LAYER_GRUPO     = "1002"       # pieza indivisible
LAYER_GUIA      = "1007"       # guía visual

LT_NORMAL  = "CONTINUOUS"   # corte normal
LT_TAB     = "DASHED"       # pausa disco (TAB)
LT_INGLETE = "HIDDEN"       # dirección herramienta / ingletes
LT_UTL     = "DOTTED"       # último pase lento

R_ENCHUFE  = 35.0   # radio enchufe = 70mm diámetro (broca 7cm)
R_GRIFO    = 17.5   # radio grifo = 35mm diámetro
KERF       = 3.5    # ancho de disco en mm
SEP_PIEZAS = 20.0   # separación entre piezas en el DXF


# ── Helpers de dibujo ──────────────────────────────────────────────────────────

def _setup_linetypes(doc):
    """Asegura que los tipos de línea necesarios existen en el documento."""
    existing = [lt.dxf.name for lt in doc.linetypes]
    for lt in [LT_TAB, LT_INGLETE, LT_UTL]:
        if lt not in existing:
            doc.linetypes.new(lt, dxfattribs={"description": lt})


def _setup_layers(doc):
    """Crea las capas necesarias si no existen."""
    existing = [l.dxf.name for l in doc.layers]
    specs = [
        (LAYER_CORTE,   7,  LT_NORMAL),   # blanco
        (LAYER_FRESA,   3,  LT_NORMAL),   # verde
        (LAYER_TALADRO, 5,  LT_NORMAL),   # azul
        (LAYER_GRUPO,   1,  LT_NORMAL),   # rojo
        (LAYER_GUIA,    9,  LT_NORMAL),   # gris
    ]
    for name, color, lt in specs:
        if name not in existing:
            doc.layers.new(name, dxfattribs={"color": color, "linetype": lt})


def _line(msp, x0, y0, x1, y1, layer=LAYER_CORTE, lt=LT_NORMAL):
    msp.add_line(
        (x0, y0), (x1, y1),
        dxfattribs={"layer": layer, "linetype": lt}
    )


def _circle(msp, cx, cy, r, layer=LAYER_TALADRO):
    msp.add_circle((cx, cy), r, dxfattribs={"layer": layer})


def _rect(msp, x, y, w, h, layer=LAYER_CORTE, lt=LT_NORMAL,
          descuadro_izq=0.0, descuadro_der=0.0):
    """
    Dibuja un rectángulo como 4 LINE separadas.
    descuadro_izq / descuadro_der: desplazamiento en mm del lado izquierdo/derecho
    (positivo = la esquina de arriba se mueve hacia la derecha = pared empuja).
    El descuadro se aplica sólo a las esquinas superiores.

    Coordenadas:
      inf-izq = (x,           y)
      inf-der = (x+w,         y)
      sup-der = (x+w+d_der,   y+h)
      sup-izq = (x+d_izq,     y+h)
    """
    d_izq = float(descuadro_izq or 0)
    d_der = float(descuadro_der or 0)

    p0 = (x,          y)       # inf-izq
    p1 = (x + w,      y)       # inf-der
    p2 = (x + w + d_der, y + h)  # sup-der
    p3 = (x + d_izq,  y + h)  # sup-izq

    _line(msp, p0[0], p0[1], p1[0], p1[1], layer, lt)  # frente (inf)
    _line(msp, p1[0], p1[1], p2[0], p2[1], layer, lt)  # lado derecho
    _line(msp, p2[0], p2[1], p3[0], p3[1], layer, lt)  # pared (sup)
    _line(msp, p3[0], p3[1], p0[0], p0[1], layer, lt)  # lado izquierdo


def _hueco_rect(msp, x, y, w, h, layer=LAYER_CORTE, lt=LT_TAB):
    """
    Dibuja un hueco rectangular (placa, fregadero rectangular).
    Usa TAB por defecto para que el disco se detenga en las esquinas.
    """
    _rect(msp, x, y, w, h, layer=layer, lt=lt)


def _hueco_fregadero_con_curvas(msp, cx, cy, w, h):
    """
    Fregadero con esquinas redondeadas grandes → capa 0-CON (fresadora).
    Dibuja las líneas rectas en 0-CON.
    """
    # Para simplificar, dibujamos como rectángulo en 0-CON
    # (el cortador añadirá las curvas manualmente si procede)
    _rect(msp, cx - w/2, cy - h/2, w, h, layer=LAYER_FRESA)


# ── Generador de piezas individuales ──────────────────────────────────────────

class Cursor:
    """Lleva la posición X actual para colocar piezas una tras otra."""
    def __init__(self, x0=0.0, y0=0.0, sep=SEP_PIEZAS):
        self.x = x0
        self.y = y0
        self.sep = sep
        self.y_max = 0.0  # altura máxima en la fila actual

    def siguiente(self, w, h):
        """Devuelve (x, y) donde colocar la próxima pieza y avanza el cursor."""
        pos = (self.x, self.y)
        self.x += w + self.sep
        self.y_max = max(self.y_max, h)
        return pos


def _dibujar_encimera(msp, pieza: dict, x: float, y: float):
    """
    Encimera simple (rectangular o con descuadro).
    El frente es el lado inferior (y mínimo). Las paredes están arriba.
    """
    w = float(pieza.get("largo_mm") or pieza.get("ancho_mm") or 0)
    h = float(pieza.get("ancho_mm") or pieza.get("alto_mm") or 0)
    # Para encimeras: largo = ancho de la pieza (de izq a der)
    #                 ancho = fondo (profundidad, de frente a pared)
    # Si solo hay largo_mm sin ancho_mm usamos 620mm como fondo por defecto
    if not h:
        h = 620.0

    d_izq = float(pieza.get("descuadro_izq_mm") or 0)
    d_der = float(pieza.get("descuadro_der_mm") or 0)

    _rect(msp, x, y, w, h, descuadro_izq=d_izq, descuadro_der=d_der)

    # Huecos dentro de la encimera
    _dibujar_huecos(msp, pieza.get("huecos", []), x, y, w, h, pieza)

    return w, h


def _dibujar_chapeado(msp, pieza: dict, x: float, y: float):
    """
    Chapeado / frontal (panel vertical). largo × alto.
    """
    w = float(pieza.get("largo_mm") or 0)
    h = float(pieza.get("alto_mm") or pieza.get("ancho_mm") or 0)

    d_izq = float(pieza.get("descuadro_izq_mm") or 0)
    d_der = float(pieza.get("descuadro_der_mm") or 0)

    _rect(msp, x, y, w, h, descuadro_izq=d_izq, descuadro_der=d_der)

    # Huecos (enchufes principalmente)
    _dibujar_huecos(msp, pieza.get("huecos", []), x, y, w, h, pieza)

    return w, h


def _dibujar_tira(msp, pieza: dict, x: float, y: float):
    """Copete, rodapié — largas y estrechas."""
    w = float(pieza.get("largo_mm") or 0)
    h = float(pieza.get("alto_mm") or pieza.get("ancho_mm") or 50)
    _rect(msp, x, y, w, h)
    return w, h


def _dibujar_huecos(msp, huecos: list, base_x, base_y, pieza_w, pieza_h, pieza: dict):
    """
    Dibuja huecos dentro de una pieza (placa, fregadero, grifo, enchufe).
    base_x, base_y = esquina inferior izquierda de la pieza.
    """
    for hueco in huecos:
        tipo = hueco.get("tipo", "")
        hw   = float(hueco.get("largo_mm") or 0)
        hh   = float(hueco.get("ancho_mm") or hueco.get("alto_mm") or 0)
        pos  = (hueco.get("posicion") or "centro").lower()
        dist_frente = float(hueco.get("distancia_frente_mm") or 70)

        if tipo == "placa":
            if not hw: hw = 560
            if not hh: hh = 490
            # Centrar horizontalmente si posición centro
            if "izq" in pos:
                hx = base_x + 100
            elif "der" in pos:
                hx = base_x + pieza_w - hw - 100
            else:
                hx = base_x + (pieza_w - hw) / 2
            hy = base_y + dist_frente
            _hueco_rect(msp, hx, hy, hw, hh)

        elif tipo == "fregadero":
            if not hw: hw = 490
            if not hh: hh = 400
            if "izq" in pos:
                hx = base_x + 100
            elif "der" in pos:
                hx = base_x + pieza_w - hw - 100
            else:
                hx = base_x + (pieza_w - hw) / 2
            hy = base_y + dist_frente
            # Si el fregadero es "sobre encimera" es un hueco rectangular estándar
            subtipo = (hueco.get("subtipo") or "").lower()
            if "curva" in (hueco.get("notas") or "").lower():
                _hueco_fregadero_con_curvas(msp, hx + hw/2, hy + hh/2, hw, hh)
            else:
                _hueco_rect(msp, hx, hy, hw, hh)

        elif tipo == "grifo":
            # Agujero 35mm diámetro, detrás del fregadero
            # Posición aproximada: a la derecha del fregadero o según nota
            hx = base_x + pieza_w * 0.6
            hy = base_y + dist_frente + 50
            _circle(msp, hx, hy, R_GRIFO)

        elif tipo == "enchufe":
            # Agujero 70mm diámetro en capa 1006
            if "izq" in pos:
                hx = base_x + 150
            elif "der" in pos:
                hx = base_x + pieza_w - 150
            else:
                hx = base_x + pieza_w / 2
            # En chapeado: a media altura; en encimera: según distancia_frente
            if pieza.get("tipo") in ("chapeado",):
                hy = base_y + pieza_h / 2
            else:
                hy = base_y + dist_frente + 50
            cantidad = int(hueco.get("cantidad") or 1)
            for i in range(cantidad):
                _circle(msp, hx + i * 120, hy, R_ENCHUFE, layer=LAYER_TALADRO)


# ── Generador principal ────────────────────────────────────────────────────────

def generar_dxf(medidas: dict, salida: Path,
                separacion: float = SEP_PIEZAS) -> Path:
    """
    Genera el DXF de producción a partir del dict de medidas.

    Args:
        medidas: dict con 'piezas', 'cliente', 'numero', etc.
        salida:  Ruta de salida del .dxf
        separacion: Espacio entre piezas en mm

    Returns:
        Ruta del .dxf generado
    """
    doc = ezdxf.new("R2010")
    _setup_linetypes(doc)
    _setup_layers(doc)
    msp = doc.modelspace()

    piezas = medidas.get("piezas", [])
    cursor = Cursor(x0=0, y0=0, sep=separacion)

    for pieza in piezas:
        tipo = (pieza.get("tipo") or "encimera").lower()
        x, y = cursor.siguiente(
            float(pieza.get("largo_mm") or pieza.get("ancho_mm") or 600),
            float(pieza.get("alto_mm") or pieza.get("ancho_mm") or 600),
        )

        if tipo in ("encimera", "isla"):
            w, h = _dibujar_encimera(msp, pieza, x, y)
        elif tipo in ("chapeado", "frontal", "pilastra", "costado"):
            w, h = _dibujar_chapeado(msp, pieza, x, y)
        elif tipo in ("copete", "rodapie", "zocalo", "paso", "tabica"):
            w, h = _dibujar_tira(msp, pieza, x, y)
        else:
            # Genérico
            w = float(pieza.get("largo_mm") or 500)
            h = float(pieza.get("alto_mm") or pieza.get("ancho_mm") or 100)
            _rect(msp, x, y, w, h)

    salida.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(salida))
    print(f"✓ DXF guardado: {salida} ({len(piezas)} piezas)")
    return salida


# ── Generar desde JSON ─────────────────────────────────────────────────────────

def generar_desde_json(json_path: Path, salida: Optional[Path] = None) -> Path:
    import json as _json
    with open(json_path, encoding="utf-8") as f:
        medidas = _json.load(f)

    if salida is None:
        salida = json_path.parent / (json_path.stem.replace("_medidas", "") + "_produccion.dxf")

    return generar_dxf(medidas, salida)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python3 dxf_produccion.py <medidas.json> [salida.dxf]")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    salida    = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    out = generar_desde_json(json_path, salida)
    print(f"Generado: {out}")
