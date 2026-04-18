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
LAYER_GUIA      = "1007"       # guía visual (pulido, marcas no mecanizadas)

LT_NORMAL  = "CONTINUOUS"   # corte normal
LT_TAB     = "DASHED"       # pausa disco (TAB)
LT_UTL     = "DOTTED"       # último pase lento

# Inglete por defecto: 45.5° (holgura estándar del negocio; ver feedback_acabados_aristas)
ANGULO_INGLETE_DEFAULT = 45.5

# Color cian para layer 1007 (pulido / guía visual)
COLOR_GUIA = 4

R_ENCHUFE  = 35.0   # radio enchufe = 70mm diámetro (broca 7cm)
R_GRIFO    = 17.5   # radio grifo = 35mm diámetro
KERF       = 3.5    # ancho de disco en mm
SEP_PIEZAS = 20.0   # separación entre piezas en el DXF


# ── Helpers de dibujo ──────────────────────────────────────────────────────────

def _setup_linetypes(doc):
    """Asegura que los tipos de línea necesarios existen en el documento."""
    existing = [lt.dxf.name for lt in doc.linetypes]
    for lt in [LT_TAB, LT_UTL]:
        if lt not in existing:
            doc.linetypes.new(lt, dxfattribs={"description": lt})


def _setup_layers(doc):
    """Crea las capas necesarias si no existen."""
    existing = [l.dxf.name for l in doc.layers]
    specs = [
        (LAYER_CORTE,   7,          LT_NORMAL),   # blanco
        (LAYER_FRESA,   3,          LT_NORMAL),   # verde
        (LAYER_TALADRO, 5,          LT_NORMAL),   # azul
        (LAYER_GRUPO,   1,          LT_NORMAL),   # rojo
        (LAYER_GUIA,    COLOR_GUIA, LT_NORMAL),   # cian — guía pulido
    ]
    for name, color, lt in specs:
        if name not in existing:
            doc.layers.new(name, dxfattribs={"color": color, "linetype": lt})


# ── Capas dinámicas para cortes inclinados (ingletes / biseles) ───────────────

def _format_angulo(angulo: float) -> str:
    """Formatea ángulo para nombre de capa CAM: 45.5 → '45_5', -45.5 → '-45_5'."""
    a = float(angulo)
    signo = "-" if a < 0 else ""
    ent, dec = divmod(abs(a), 1)
    if dec < 0.001:
        return f"{signo}{int(ent)}"
    dec_str = f"{dec:.2f}".rstrip("0").rstrip(".")[2:]  # "0.5" → "5", "0.25" → "25"
    return f"{signo}{int(ent)}_{dec_str}"


def _layer_inclinacion(doc, angulo: float) -> str:
    """
    Devuelve el nombre de la capa `1000INC{angulo}`. La crea si no existe.
    El signo indica la dirección del bisel.
    """
    nombre = f"1000INC{_format_angulo(angulo)}"
    existing = [l.dxf.name for l in doc.layers]
    if nombre not in existing:
        # Color 2 (amarillo) para que destaque en AutoCAD respecto a los cortes normales
        doc.layers.new(nombre, dxfattribs={"color": 2, "linetype": LT_NORMAL})
    return nombre


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
    Dibuja un rectángulo como 4 LINE separadas en la misma capa/linetype.
    Usado para huecos (placa, fregadero) y piezas sin acabados especiales.
    """
    d_izq = float(descuadro_izq or 0)
    d_der = float(descuadro_der or 0)

    p0 = (x,             y)
    p1 = (x + w,         y)
    p2 = (x + w + d_der, y + h)
    p3 = (x + d_izq,     y + h)

    _line(msp, p0[0], p0[1], p1[0], p1[1], layer, lt)
    _line(msp, p1[0], p1[1], p2[0], p2[1], layer, lt)
    _line(msp, p2[0], p2[1], p3[0], p3[1], layer, lt)
    _line(msp, p3[0], p3[1], p0[0], p0[1], layer, lt)


def _rect_con_acabados(msp, x, y, w, h, acabados: dict = None,
                       descuadro_izq=0.0, descuadro_der=0.0):
    """
    Contorno de pieza con acabado independiente por arista.

    Cada arista se dibuja en la capa CAM que corresponde:
      - inglete/bisel → layer 1000INC{angulo} (ej. 1000INC45_5)
      - pulido        → layer 0 + línea paralela en 1007 como marcador visual
      - null/None     → layer 0 (corte normal)

    acabados: dict con claves 'frente', 'fondo', 'cabeza_izq', 'cabeza_der'.
              Cada valor: {'tipo': 'inglete'|'bisel'|'pulido'|None,
                           'angulo': float|None, 'profundidad_mm': float|None}

    Descuadros: desplazamiento lateral de las esquinas superiores (pared que empuja).
    """
    doc      = msp.doc
    acabados = acabados or {}
    d_izq    = float(descuadro_izq or 0)
    d_der    = float(descuadro_der or 0)

    p0 = (x,             y)            # inf-izq
    p1 = (x + w,         y)            # inf-der
    p2 = (x + w + d_der, y + h)        # sup-der
    p3 = (x + d_izq,     y + h)        # sup-izq

    # Orden CCW: el interior queda a la izquierda del avance
    aristas = [
        ("frente",     p0, p1),
        ("cabeza_der", p1, p2),
        ("fondo",      p2, p3),
        ("cabeza_izq", p3, p0),
    ]

    for nombre, a, b in aristas:
        acab  = acabados.get(nombre) or {}
        tipo  = (acab.get("tipo") or "").strip().lower() if acab.get("tipo") else None
        angulo = acab.get("angulo")

        if tipo in ("inglete", "bisel"):
            if angulo is None:
                angulo = ANGULO_INGLETE_DEFAULT
            layer = _layer_inclinacion(doc, angulo)
            _line(msp, a[0], a[1], b[0], b[1], layer=layer)
        elif tipo == "pulido":
            _line(msp, a[0], a[1], b[0], b[1], layer=LAYER_CORTE)
            _marcar_pulido(msp, a, b)
        else:
            _line(msp, a[0], a[1], b[0], b[1], layer=LAYER_CORTE)


def _marcar_pulido(msp, a, b, offset=15.0):
    """
    Dibuja una línea paralela al borde en layer 1007 (guía visual, no mecaniza)
    a {offset}mm hacia el interior de la pieza. Sirve como marcador del pulido
    para el operario del taller (se ve en el DXF y en el PDF acotado).

    Para polígonos en sentido antihorario (el usado por _rect_con_acabados),
    el interior queda a la izquierda del vector de avance: normal = (-dy, dx).
    """
    import math
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1:
        return
    nx, ny = -dy / length, dx / length   # normal hacia el interior
    ax, ay = a[0] + nx * offset, a[1] + ny * offset
    bx, by = b[0] + nx * offset, b[1] + ny * offset
    _line(msp, ax, ay, bx, by, layer=LAYER_GUIA)


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


def _acabados_de_pieza(pieza: dict) -> dict:
    """
    Devuelve los acabados_aristas en formato nuevo, convirtiendo la lista
    legacy 'ingletes' si existe y 'acabados_aristas' no está presente.
    """
    acab = pieza.get("acabados_aristas")
    if isinstance(acab, dict) and acab:
        return acab

    # Compat: 'ingletes' es una lista de nombres de arista con inglete 45°
    ingletes = pieza.get("ingletes") or []
    if ingletes:
        return {
            nombre: {"tipo": "inglete", "angulo": ANGULO_INGLETE_DEFAULT,
                     "profundidad_mm": None}
            for nombre in ingletes
        }
    return {}


def validar_pieza(pieza: dict) -> list[str]:
    """
    Devuelve lista de strings de problemas bloqueantes para dibujar la pieza.
    Vacía = pieza dibujable con certeza (producción).
    Sin defaults: si falta una dimensión crítica, es un problema.
    """
    problemas = []
    tipo = (pieza.get("tipo") or "").lower()
    largo = pieza.get("largo_mm")
    ancho = pieza.get("ancho_mm")
    alto  = pieza.get("alto_mm")

    if largo in (None, 0):
        problemas.append("largo_mm")

    if tipo in ("encimera", "isla", "cascada"):
        if ancho in (None, 0):
            problemas.append("ancho_mm (fondo de la encimera)")
    elif tipo in ("chapeado", "frontal", "pilastra", "costado"):
        # Necesita alto o ancho_mm como altura vertical
        if (alto in (None, 0)) and (ancho in (None, 0)):
            problemas.append("alto_mm (altura del chapeado)")
    elif tipo in ("copete", "rodapie", "zocalo", "paso", "tabica"):
        # Tira fina: necesita altura
        if (alto in (None, 0)) and (ancho in (None, 0)):
            problemas.append("alto_mm (altura de la tira)")
    else:
        if (ancho in (None, 0)) and (alto in (None, 0)):
            problemas.append("ancho_mm o alto_mm")

    # Huecos: cada uno necesita sus medidas y ubicación completas
    for i, h in enumerate(pieza.get("huecos") or []):
        if not isinstance(h, dict):
            problemas.append(f"hueco[{i}] formato inválido")
            continue
        tipo_h = (h.get("tipo") or "").lower()
        if tipo_h in ("placa", "fregadero"):
            if not h.get("largo_mm"):  problemas.append(f"hueco[{i}] {tipo_h}: largo_mm")
            if not h.get("ancho_mm"):  problemas.append(f"hueco[{i}] {tipo_h}: ancho_mm")
            if h.get("distancia_frente_mm") in (None,):
                problemas.append(f"hueco[{i}] {tipo_h}: distancia_frente_mm")
            pos = (h.get("posicion") or "").lower()
            if pos in ("izquierda", "derecha") and h.get("distancia_lado_mm") in (None,):
                problemas.append(f"hueco[{i}] {tipo_h}: distancia_lado_mm ({pos})")
            if not pos:
                problemas.append(f"hueco[{i}] {tipo_h}: posicion")
        elif tipo_h in ("enchufe", "grifo"):
            # El Ø es una constante (broca), pero necesitamos dónde ponerlo
            if h.get("distancia_frente_mm") in (None,):
                problemas.append(f"hueco[{i}] {tipo_h}: distancia_frente_mm")
            pos = (h.get("posicion") or "").lower()
            if pos in ("izquierda", "derecha") and h.get("distancia_lado_mm") in (None,):
                problemas.append(f"hueco[{i}] {tipo_h}: distancia_lado_mm")
    return problemas


def _dims_para_cursor(pieza: dict) -> tuple[float, float]:
    """(w, h) físicos de la pieza para avanzar el cursor en el DXF."""
    tipo = (pieza.get("tipo") or "").lower()
    largo = float(pieza.get("largo_mm") or 0)
    if tipo in ("encimera", "isla", "cascada"):
        h = float(pieza.get("ancho_mm") or pieza.get("alto_mm") or 0)
    else:
        h = float(pieza.get("alto_mm") or pieza.get("ancho_mm") or 0)
    return largo, h


def _dibujar_encimera(msp, pieza: dict, x: float, y: float):
    """Encimera (rectangular o con descuadro). Frente = lado inferior."""
    w = float(pieza["largo_mm"])
    h = float(pieza.get("ancho_mm") or pieza.get("alto_mm"))

    d_izq = float(pieza.get("descuadro_izq_mm") or 0)
    d_der = float(pieza.get("descuadro_der_mm") or 0)

    _rect_con_acabados(
        msp, x, y, w, h,
        acabados=_acabados_de_pieza(pieza),
        descuadro_izq=d_izq, descuadro_der=d_der,
    )
    _dibujar_huecos(msp, pieza.get("huecos", []), x, y, w, h, pieza)
    return w, h


def _dibujar_chapeado(msp, pieza: dict, x: float, y: float):
    """Chapeado / frontal (panel vertical). largo × alto."""
    w = float(pieza["largo_mm"])
    h = float(pieza.get("alto_mm") or pieza.get("ancho_mm"))

    d_izq = float(pieza.get("descuadro_izq_mm") or 0)
    d_der = float(pieza.get("descuadro_der_mm") or 0)

    _rect_con_acabados(
        msp, x, y, w, h,
        acabados=_acabados_de_pieza(pieza),
        descuadro_izq=d_izq, descuadro_der=d_der,
    )
    _dibujar_huecos(msp, pieza.get("huecos", []), x, y, w, h, pieza)
    return w, h


def _dibujar_tira(msp, pieza: dict, x: float, y: float):
    """Copete, rodapié — largas y estrechas."""
    w = float(pieza["largo_mm"])
    h = float(pieza.get("alto_mm") or pieza.get("ancho_mm"))
    _rect_con_acabados(msp, x, y, w, h, acabados=_acabados_de_pieza(pieza))
    return w, h


def _dibujar_huecos(msp, huecos: list, base_x, base_y, pieza_w, pieza_h, pieza: dict):
    """
    Dibuja huecos dentro de una pieza (placa, fregadero, grifo, enchufe).
    base_x, base_y = esquina inferior izquierda de la pieza.

    NO usa defaults: si faltan medidas/posición críticas, el hueco se omite con
    warning. La validación previa en validar_pieza() ya debería haberlo filtrado.
    """
    for idx, hueco in enumerate(huecos):
        tipo = (hueco.get("tipo") or "").lower()
        hw   = hueco.get("largo_mm")
        hh   = hueco.get("ancho_mm") or hueco.get("alto_mm")
        pos  = (hueco.get("posicion") or "").lower()
        dist_frente = hueco.get("distancia_frente_mm")
        dist_lado   = hueco.get("distancia_lado_mm")

        if tipo in ("placa", "fregadero"):
            if not hw or not hh or dist_frente is None or not pos:
                print(f"    ⚠ Hueco {tipo} #{idx} omitido: faltan medidas/posición")
                continue
            hw = float(hw); hh = float(hh)
            if "izq" in pos:
                if dist_lado is None:
                    print(f"    ⚠ Hueco {tipo} #{idx} 'izquierda' omitido: falta distancia_lado_mm"); continue
                hx = base_x + float(dist_lado)
            elif "der" in pos:
                if dist_lado is None:
                    print(f"    ⚠ Hueco {tipo} #{idx} 'derecha' omitido: falta distancia_lado_mm"); continue
                hx = base_x + pieza_w - hw - float(dist_lado)
            elif "centro" in pos:
                hx = base_x + (pieza_w - hw) / 2
            else:
                print(f"    ⚠ Hueco {tipo} #{idx} omitido: posicion='{pos}' desconocida"); continue
            hy = base_y + float(dist_frente)

            if tipo == "placa":
                _hueco_rect(msp, hx, hy, hw, hh)
            else:  # fregadero
                if "curva" in (hueco.get("notas") or "").lower():
                    _hueco_fregadero_con_curvas(msp, hx + hw/2, hy + hh/2, hw, hh)
                else:
                    _hueco_rect(msp, hx, hy, hw, hh)

        elif tipo in ("grifo", "enchufe"):
            radio = R_GRIFO if tipo == "grifo" else R_ENCHUFE
            if dist_frente is None:
                print(f"    ⚠ Hueco {tipo} #{idx} omitido: falta distancia_frente_mm"); continue
            if "izq" in pos:
                if dist_lado is None:
                    print(f"    ⚠ Hueco {tipo} #{idx} 'izquierda' omitido: falta distancia_lado_mm"); continue
                hx = base_x + float(dist_lado)
            elif "der" in pos:
                if dist_lado is None:
                    print(f"    ⚠ Hueco {tipo} #{idx} 'derecha' omitido: falta distancia_lado_mm"); continue
                hx = base_x + pieza_w - float(dist_lado)
            elif "centro" in pos:
                hx = base_x + pieza_w / 2
            else:
                print(f"    ⚠ Hueco {tipo} #{idx} omitido: posicion='{pos}' desconocida"); continue
            hy = base_y + float(dist_frente)
            _circle(msp, hx, hy, radio, layer=LAYER_TALADRO)

        else:
            print(f"    ⚠ Hueco tipo='{tipo}' no reconocido (pieza {pieza.get('tipo')})")


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

    dibujadas = 0
    omitidas  = []

    for i, pieza in enumerate(piezas):
        problemas = validar_pieza(pieza)
        if problemas:
            omitidas.append({"index": i + 1, "tipo": pieza.get("tipo"),
                              "notas": pieza.get("notas",""), "faltan": problemas})
            print(f"  ⚠ Pieza #{i+1} ({pieza.get('tipo')}) OMITIDA — faltan: {', '.join(problemas)}")
            continue

        tipo = (pieza.get("tipo") or "").lower()
        w_p, h_p = _dims_para_cursor(pieza)
        x, y = cursor.siguiente(w_p, h_p)

        if tipo in ("encimera", "isla"):
            _dibujar_encimera(msp, pieza, x, y)
        elif tipo in ("chapeado", "frontal", "pilastra", "costado"):
            _dibujar_chapeado(msp, pieza, x, y)
        elif tipo in ("copete", "rodapie", "zocalo", "paso", "tabica"):
            _dibujar_tira(msp, pieza, x, y)
        else:
            # Genérico: solo si el usuario ha especificado ambas dimensiones
            w = float(pieza["largo_mm"])
            h = float(pieza.get("alto_mm") or pieza.get("ancho_mm"))
            _rect(msp, x, y, w, h)
        dibujadas += 1

    salida.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(salida))
    print(f"✓ DXF guardado: {salida} ({dibujadas}/{len(piezas)} piezas dibujadas)")
    if omitidas:
        print(f"  ⚠ {len(omitidas)} pieza(s) omitidas por dimensiones incompletas:")
        for o in omitidas:
            print(f"     #{o['index']} {o['tipo']}: {', '.join(o['faltan'])}")
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
