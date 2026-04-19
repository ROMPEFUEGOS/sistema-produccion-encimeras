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
            ext = acab.get("extension_mm") if isinstance(acab, dict) else None
            desde = (acab.get("desde") or "").lower() if isinstance(acab, dict) else ""
            # desde_frente=True: el tramo pulido empieza en 'a' (inicio de la arista).
            # Para edges de un rect CCW, a = vértice anterior en sentido CCW.
            # "desde=frente" significa: desde el extremo más cercano al frente (y min).
            if desde == "frente":
                desde_frente = (a[1] < b[1]) or (a[1] == b[1] and a[0] < b[0])
            elif desde == "fondo":
                desde_frente = not ((a[1] < b[1]) or (a[1] == b[1] and a[0] < b[0]))
            else:
                desde_frente = True
            _marcar_pulido(msp, a, b, extension_mm=ext, desde_frente=desde_frente)
        else:
            _line(msp, a[0], a[1], b[0], b[1], layer=LAYER_CORTE)


def _marcar_pulido(msp, a, b, offset=15.0, extension_mm=None, desde_frente=False):
    """
    Dibuja una línea paralela al borde en layer 1007 (guía visual, no mecaniza)
    a {offset}mm hacia el interior de la pieza. Sirve como marcador del pulido.

    Si `extension_mm` está definido, solo se marca ese tramo (no toda la arista).
    `desde_frente`=True → empieza desde a; False → desde b.
    """
    import math
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1:
        return
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux  # normal hacia interior (CCW)

    # Si hay extensión parcial, recortar el segmento
    if extension_mm and extension_mm > 0 and extension_mm < length:
        ext = float(extension_mm)
        if desde_frente:
            # Empieza en a, termina a `ext` mm en dirección ab
            ax, ay = a
            bx, by = a[0] + ux * ext, a[1] + uy * ext
        else:
            # Empieza a `length-ext` mm, termina en b
            ax, ay = a[0] + ux * (length - ext), a[1] + uy * (length - ext)
            bx, by = b
    else:
        ax, ay = a; bx, by = b

    ax2, ay2 = ax + nx * offset, ay + ny * offset
    bx2, by2 = bx + nx * offset, by + ny * offset
    _line(msp, ax2, ay2, bx2, by2, layer=LAYER_GUIA)


def _hueco_rect(msp, x, y, w, h, layer=LAYER_CORTE, lt=LT_TAB):
    """
    Dibuja un hueco rectangular (placa, fregadero rectangular).
    Usa TAB por defecto para que el disco se detenga en las esquinas.
    """
    _rect(msp, x, y, w, h, layer=layer, lt=lt)


def _hueco_rect_con_radios(msp, x, y, w, h, radio: float,
                           layer_lineas=LAYER_CORTE, lt_lineas=LT_TAB,
                           layer_arcos=LAYER_FRESA):
    """
    Dibuja un hueco rectangular con las 4 esquinas redondeadas a radio `radio`.
    Cada lado recto va como LINE en `layer_lineas` (disco), y cada esquina
    como ARC en `layer_arcos` (fresadora — el disco no puede curvas grandes).

    Según CAM Rules: radios > 20mm van en 0-CON (fresado). Radios <= 20mm
    podrían ir en capa de corte, pero para uniformidad usamos 0-CON siempre.
    """
    import math
    r = float(radio)
    # Vertices del rectángulo
    x0, y0 = x, y                 # inf-izq
    x1, y1 = x + w, y             # inf-der
    x2, y2 = x + w, y + h         # sup-der
    x3, y3 = x, y + h             # sup-izq

    # Lados rectos (acortados por r en cada extremo)
    # Lado inferior: (x0+r, y0) → (x1-r, y0)
    _line(msp, x0 + r, y0, x1 - r, y0, layer=layer_lineas, lt=lt_lineas)
    # Lado derecho: (x1, y1+r) → (x2, y2-r)
    _line(msp, x1, y1 + r, x2, y2 - r, layer=layer_lineas, lt=lt_lineas)
    # Lado superior: (x2-r, y2) → (x3+r, y3)
    _line(msp, x2 - r, y2, x3 + r, y3, layer=layer_lineas, lt=lt_lineas)
    # Lado izquierdo: (x3, y3-r) → (x0, y0+r)
    _line(msp, x3, y3 - r, x0, y0 + r, layer=layer_lineas, lt=lt_lineas)

    # Arcos en las 4 esquinas (centro a r,r desde la esquina hacia el interior del hueco)
    # CCW del rectángulo: inf-izq, inf-der, sup-der, sup-izq
    # Esquina inf-izq: centro=(x0+r, y0+r), arc de 180° a 270°
    msp.add_arc(center=(x0 + r, y0 + r), radius=r,
                start_angle=180, end_angle=270,
                dxfattribs={"layer": layer_arcos})
    # Esquina inf-der: centro=(x1-r, y1+r), arc 270° a 360°
    msp.add_arc(center=(x1 - r, y1 + r), radius=r,
                start_angle=270, end_angle=360,
                dxfattribs={"layer": layer_arcos})
    # Esquina sup-der: centro=(x2-r, y2-r), arc 0° a 90°
    msp.add_arc(center=(x2 - r, y2 - r), radius=r,
                start_angle=0, end_angle=90,
                dxfattribs={"layer": layer_arcos})
    # Esquina sup-izq: centro=(x3+r, y3-r), arc 90° a 180°
    msp.add_arc(center=(x3 + r, y3 - r), radius=r,
                start_angle=90, end_angle=180,
                dxfattribs={"layer": layer_arcos})


def _hueco_fregadero_con_curvas(msp, cx, cy, w, h):
    """Compat: fregadero sin radio específico → usa radio=30mm como default."""
    _hueco_rect_con_radios(msp, cx - w/2, cy - h/2, w, h, radio=30.0)


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


def _dibujar_contorno_custom(msp, pieza: dict, x_off: float, y_off: float) -> tuple[float, float]:
    """
    Dibuja el contorno de una pieza con forma no rectangular usando el campo
    `contorno_custom` de la pieza. Cada arista va en la capa que corresponde
    según `acabados_contorno[i]` (inglete/bisel/pulido/null).

    Los radios de esquina (`radios_esquina_mm`) se loguean con warning por
    ahora — se dibujan como esquinas vivas. Fillet con arco queda para
    iteración siguiente.
    """
    cc = pieza.get("contorno_custom") or {}
    verts  = cc.get("vertices_mm") or []
    radios = cc.get("radios_esquina_mm") or []
    acabs  = cc.get("acabados_contorno") or []

    N = len(verts)
    if N < 3:
        return 0.0, 0.0

    if any((r or 0) > 0 for r in radios):
        print(f"    ⚠ Pieza '{pieza.get('tipo')}' con radios de esquina — dibujadas como esquinas vivas (fillet pendiente)")

    while len(acabs) < N:
        acabs.append(None)

    doc = msp.doc

    for i in range(N):
        a = verts[i]
        b = verts[(i + 1) % N]
        ax, ay = a[0] + x_off, a[1] + y_off
        bx, by = b[0] + x_off, b[1] + y_off

        acab = acabs[i] if isinstance(acabs[i], dict) else {}
        tipo = (acab.get("tipo") or "").strip().lower() if acab.get("tipo") else None
        angulo = acab.get("angulo")

        if tipo in ("inglete", "bisel"):
            if angulo is None:
                angulo = ANGULO_INGLETE_DEFAULT
            layer = _layer_inclinacion(doc, angulo)
            _line(msp, ax, ay, bx, by, layer=layer)
        elif tipo == "pulido":
            _line(msp, ax, ay, bx, by, layer=LAYER_CORTE)
            ext = acab.get("extension_mm")
            desde = (acab.get("desde") or "").lower()
            a_pt, b_pt = (ax, ay), (bx, by)
            if desde == "frente":
                desde_frente = (a_pt[1] < b_pt[1]) or (a_pt[1] == b_pt[1] and a_pt[0] < b_pt[0])
            elif desde == "fondo":
                desde_frente = not ((a_pt[1] < b_pt[1]) or (a_pt[1] == b_pt[1] and a_pt[0] < b_pt[0]))
            else:
                desde_frente = True
            _marcar_pulido(msp, a_pt, b_pt, extension_mm=ext, desde_frente=desde_frente)
        else:
            _line(msp, ax, ay, bx, by, layer=LAYER_CORTE)

    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    return max(xs) - min(xs), max(ys) - min(ys)


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

    Si la pieza tiene `contorno_custom` con >=3 vértices válidos, se valida
    el contorno en lugar de largo/ancho.
    """
    problemas = []
    tipo = (pieza.get("tipo") or "").lower()

    # Contorno custom para formas no rectangulares
    cc = pieza.get("contorno_custom")
    if cc:
        verts = cc.get("vertices_mm") or []
        if len(verts) < 3:
            problemas.append("contorno_custom con menos de 3 vértices")
        else:
            for i, v in enumerate(verts):
                if not isinstance(v, (list, tuple)) or len(v) < 2:
                    problemas.append(f"contorno_custom vértice {i} inválido")
                    break
                if v[0] is None or v[1] is None:
                    problemas.append(f"contorno_custom vértice {i} con null")
                    break
        # Para contorno custom, las demás validaciones de largo/ancho no aplican
        # (la geometría está en los vértices).
    else:
        largo = pieza.get("largo_mm")
        ancho = pieza.get("ancho_mm")
        alto  = pieza.get("alto_mm")

        if largo in (None, 0):
            problemas.append("largo_mm")

        if tipo in ("encimera", "isla", "cascada"):
            if ancho in (None, 0):
                problemas.append("ancho_mm (fondo de la encimera)")
        elif tipo in ("chapeado", "frontal", "pilastra", "costado"):
            if (alto in (None, 0)) and (ancho in (None, 0)):
                problemas.append("alto_mm (altura del chapeado)")
        elif tipo in ("copete", "rodapie", "zocalo", "paso", "tabica"):
            if (alto in (None, 0)) and (ancho in (None, 0)):
                problemas.append("alto_mm (altura de la tira)")
        else:
            if (ancho in (None, 0)) and (alto in (None, 0)):
                problemas.append("ancho_mm o alto_mm")

    # Huecos: placa/fregadero tienen defaults controlados (ver reglas_negocio.md),
    # por lo que no se flagean aquí — el código aplica defaults y anota en el PDF.
    # Sí validamos grifo/enchufe (sin defaults: necesitan posición explícita).
    for i, h in enumerate(pieza.get("huecos") or []):
        if not isinstance(h, dict):
            problemas.append(f"hueco[{i}] formato inválido")
            continue
        tipo_h = (h.get("tipo") or "").lower()
        if tipo_h in ("enchufe", "grifo"):
            if h.get("distancia_frente_mm") in (None,):
                problemas.append(f"hueco[{i}] {tipo_h}: distancia_frente_mm")
            pos = (h.get("posicion") or "").lower()
            if pos in ("izquierda", "derecha") and h.get("distancia_lado_mm") in (None,):
                problemas.append(f"hueco[{i}] {tipo_h}: distancia_lado_mm")
    return problemas


def _dims_para_cursor(pieza: dict) -> tuple[float, float]:
    """(w, h) físicos de la pieza para avanzar el cursor en el DXF."""
    cc = pieza.get("contorno_custom")
    if cc and cc.get("vertices_mm"):
        xs = [v[0] for v in cc["vertices_mm"] if v and v[0] is not None]
        ys = [v[1] for v in cc["vertices_mm"] if v and v[1] is not None]
        if xs and ys:
            return max(xs) - min(xs), max(ys) - min(ys)

    tipo = (pieza.get("tipo") or "").lower()
    largo = float(pieza.get("largo_mm") or 0)
    if tipo in ("encimera", "isla", "cascada"):
        h = float(pieza.get("ancho_mm") or pieza.get("alto_mm") or 0)
    else:
        h = float(pieza.get("alto_mm") or pieza.get("ancho_mm") or 0)
    return largo, h


def _dibujar_encimera(msp, pieza: dict, x: float, y: float):
    """Encimera (rectangular, con descuadro, o contorno custom)."""
    if pieza.get("contorno_custom"):
        w, h = _dibujar_contorno_custom(msp, pieza, x, y)
        _dibujar_huecos(msp, pieza.get("huecos", []), x, y, w, h, pieza)
        return w, h

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


def _aplicar_guion(valor: float, pieza: dict, grosor_global: float) -> float:
    """
    Aplica descuento del guión si corresponde. Resta grosor+2mm al valor.
    El grosor puede venir de la propia pieza (grosor_mm) o del global del pedido.
    """
    if not pieza.get("tiene_guion"):
        return valor
    grosor = pieza.get("grosor_mm") or grosor_global
    if not grosor:
        return valor  # sin grosor conocido, no podemos descontar
    return max(0, valor - (float(grosor) + 2.0))


def _dibujar_chapeado(msp, pieza: dict, x: float, y: float, grosor_global: float = 0):
    """Chapeado / frontal / pilastra / costado (panel vertical). largo × alto."""
    if pieza.get("contorno_custom"):
        w, h = _dibujar_contorno_custom(msp, pieza, x, y)
        _dibujar_huecos(msp, pieza.get("huecos", []), x, y, w, h, pieza)
        return w, h

    tipo = (pieza.get("tipo") or "").lower()
    w = float(pieza["largo_mm"])

    # Para costados, 'ancho_mm' es el fondo (lo que se ve en planta) — usar eso
    # como altura visible si alto_mm no está. Para chapeados puros alto_mm es obligatorio.
    if tipo == "costado":
        h_raw = pieza.get("alto_mm") or pieza.get("ancho_mm")
    else:
        h_raw = pieza.get("alto_mm")
    if h_raw is None:
        raise ValueError(f"Pieza {tipo} sin alto_mm — no se puede dibujar")
    h = float(h_raw)

    # Aplicar guión si corresponde (el descuento suele ir en la altura)
    if pieza.get("tiene_guion"):
        h_final = _aplicar_guion(h, pieza, grosor_global)
        if h_final != h:
            pieza.setdefault("_defaults_aplicados", []).append(
                f"guión aplicado: alto {h:.0f} → {h_final:.0f} (restado grosor {grosor_global or pieza.get('grosor_mm')}+2)")
            h = h_final

    d_izq = float(pieza.get("descuadro_izq_mm") or 0)
    d_der = float(pieza.get("descuadro_der_mm") or 0)

    _rect_con_acabados(
        msp, x, y, w, h,
        acabados=_acabados_de_pieza(pieza),
        descuadro_izq=d_izq, descuadro_der=d_der,
    )
    _dibujar_huecos(msp, pieza.get("huecos", []), x, y, w, h, pieza)
    return w, h


def _dibujar_tira(msp, pieza: dict, x: float, y: float, grosor_global: float = 0):
    """Copete, rodapié, zócalo, paso — largas y estrechas. largo × alto (altura)."""
    if pieza.get("contorno_custom"):
        w, h = _dibujar_contorno_custom(msp, pieza, x, y)
        return w, h

    tipo = (pieza.get("tipo") or "").lower()
    w = float(pieza["largo_mm"])

    # Altura: SIEMPRE alto_mm. Copete sin alto → default 50mm (convención taller).
    h_raw = pieza.get("alto_mm")
    if h_raw is None:
        if tipo == "copete":
            h_raw = 50.0
            pieza.setdefault("_defaults_aplicados", []).append(
                "copete sin alto en nota → usado 50mm estándar")
        else:
            raise ValueError(f"Pieza {tipo} sin alto_mm — no se puede dibujar")
    h = float(h_raw)

    # Guión: para copete/rodapié suele estar en el largo
    if pieza.get("tiene_guion"):
        w_final = _aplicar_guion(w, pieza, grosor_global)
        if w_final != w:
            pieza.setdefault("_defaults_aplicados", []).append(
                f"guión aplicado: largo {w:.0f} → {w_final:.0f} (restado grosor {grosor_global or pieza.get('grosor_mm')}+2)")
            w = w_final

    _rect_con_acabados(msp, x, y, w, h, acabados=_acabados_de_pieza(pieza))
    return w, h


def _dibujar_huecos(msp, huecos: list, base_x, base_y, pieza_w, pieza_h, pieza: dict):
    """
    Dibuja huecos dentro de una pieza (placa, fregadero, grifo, enchufe).
    base_x, base_y = esquina inferior izquierda de la pieza.

    Defaults controlados (documentados en reglas_negocio.md): si falta
    `distancia_frente_mm`, `largo_mm`, `ancho_mm` o `posicion` en placa/fregadero,
    se aplica un default estándar Y se anota en `pieza._defaults_aplicados` para
    que el PDF lo indique al operario.

    Fregadero sin largo/ancho → NO se dibuja; se añade un TEXT "FALTAN MEDIDAS"
    en la posición esperada, capa DEFPOINTS (CAM lo ignora).
    """
    # Reset para evitar acumular entre ejecuciones (la UI llama generar_dxf varias veces)
    pieza["_defaults_aplicados"] = []
    defaults_log = pieza["_defaults_aplicados"]

    for idx, hueco in enumerate(huecos):
        tipo = (hueco.get("tipo") or "").lower()
        hw   = hueco.get("largo_mm")
        hh   = hueco.get("ancho_mm") or hueco.get("alto_mm")
        pos  = (hueco.get("posicion") or "").lower()
        dist_frente = hueco.get("distancia_frente_mm")
        dist_lado   = hueco.get("distancia_lado_mm")

        # ── PLACA ───────────────────────────────────────────────────────────
        if tipo == "placa":
            # Defaults de dimensión
            if not hw or not hh:
                if not hw and not hh:
                    defaults_log.append(f"hueco[{idx}] placa: dimensiones NO en nota → usadas 562×492 estándar")
                    hw, hh = 562.0, 492.0
                elif not hw:
                    defaults_log.append(f"hueco[{idx}] placa: largo_mm NO en nota → usado 562 estándar")
                    hw = 562.0
                elif not hh:
                    defaults_log.append(f"hueco[{idx}] placa: ancho_mm NO en nota → usado 492 estándar")
                    hh = 492.0
            hw = float(hw); hh = float(hh)

            # Default distancia frente
            if dist_frente is None:
                defaults_log.append(f"hueco[{idx}] placa: distancia_frente_mm NO en nota → usado 70 estándar")
                dist_frente = 70.0
            dist_frente = float(dist_frente)

            # Posición
            if not pos:
                defaults_log.append(f"hueco[{idx}] placa: posicion NO en nota → usado 'centro'")
                pos = "centro"

            # distancia_lado_mm = distancia del borde al CENTRO del hueco (convención plano cocina)
            if "izq" in pos:
                if dist_lado is None:
                    print(f"    ⚠ Hueco placa #{idx} 'izquierda' omitido: falta distancia_lado_mm"); continue
                hx = base_x + float(dist_lado) - hw / 2
            elif "der" in pos:
                if dist_lado is None:
                    print(f"    ⚠ Hueco placa #{idx} 'derecha' omitido: falta distancia_lado_mm"); continue
                hx = base_x + pieza_w - float(dist_lado) - hw / 2
            elif "centro" in pos:
                hx = base_x + (pieza_w - hw) / 2
            else:
                print(f"    ⚠ Hueco placa #{idx} omitido: posicion='{pos}' desconocida"); continue
            hy = base_y + dist_frente

            # Radios de esquina (opcional)
            r_esq = hueco.get("radio_esquina_mm") or 0
            if r_esq and r_esq > 0 and r_esq < min(hw, hh) / 2:
                _hueco_rect_con_radios(msp, hx, hy, hw, hh, radio=float(r_esq))
            else:
                _hueco_rect(msp, hx, hy, hw, hh)
            continue

        # ── FREGADERO ───────────────────────────────────────────────────────
        if tipo == "fregadero":
            subtipo = (hueco.get("subtipo") or "").lower()

            # Si falta largo O ancho → NO dibujar; TEXTO en DEFPOINTS
            if not hw or not hh:
                # Ubicación estimada para el texto (centro de la pieza o como pos indique)
                # Default distancia frente si no hay
                est_dist = 100.0 if "bajo" in subtipo else 80.0
                if dist_frente is not None:
                    est_dist = float(dist_frente)
                if "izq" in pos and dist_lado is not None:
                    tx = base_x + float(dist_lado) + 245  # centro estimado (490/2)
                elif "der" in pos and dist_lado is not None:
                    tx = base_x + pieza_w - float(dist_lado) - 245
                else:
                    tx = base_x + pieza_w / 2
                ty = base_y + est_dist + 200
                texto = "FREGADERO — FALTAN MEDIDAS"
                try:
                    msp.add_text(texto, dxfattribs={
                        "layer": "DEFPOINTS",
                        "height": 40,
                        "insert": (tx, ty),
                    })
                except Exception:
                    pass
                defaults_log.append(f"hueco[{idx}] fregadero: medidas NO en nota → NO DIBUJADO, texto de aviso")
                continue

            # Default distancia frente según subtipo
            if dist_frente is None:
                if "bajo" in subtipo:
                    defaults_log.append(f"hueco[{idx}] fregadero bajo: distancia_frente_mm NO en nota → usado 100 estándar")
                    dist_frente = 100.0
                elif "sobre" in subtipo:
                    defaults_log.append(f"hueco[{idx}] fregadero sobre: distancia_frente_mm NO en nota → usado 80 estándar")
                    dist_frente = 80.0
                else:
                    defaults_log.append(f"hueco[{idx}] fregadero (subtipo desconocido): distancia_frente_mm NO en nota → usado 80 estándar")
                    dist_frente = 80.0
            dist_frente = float(dist_frente)

            if not pos:
                defaults_log.append(f"hueco[{idx}] fregadero: posicion NO en nota → usado 'centro'")
                pos = "centro"

            hw = float(hw); hh = float(hh)

            # distancia_lado_mm = distancia del borde al CENTRO del hueco
            if "izq" in pos:
                if dist_lado is None:
                    print(f"    ⚠ Hueco fregadero #{idx} 'izquierda' omitido: falta distancia_lado_mm"); continue
                hx = base_x + float(dist_lado) - hw / 2
            elif "der" in pos:
                if dist_lado is None:
                    print(f"    ⚠ Hueco fregadero #{idx} 'derecha' omitido: falta distancia_lado_mm"); continue
                hx = base_x + pieza_w - float(dist_lado) - hw / 2
            elif "centro" in pos:
                hx = base_x + (pieza_w - hw) / 2
            else:
                print(f"    ⚠ Hueco fregadero #{idx} omitido: posicion='{pos}' desconocida"); continue
            hy = base_y + dist_frente

            # Radio de esquina explícito > fallback a keyword "curva" en notas
            r_esq = hueco.get("radio_esquina_mm") or 0
            if r_esq and r_esq > 0 and r_esq < min(hw, hh) / 2:
                _hueco_rect_con_radios(msp, hx, hy, hw, hh, radio=float(r_esq))
            elif "curva" in (hueco.get("notas") or "").lower():
                _hueco_fregadero_con_curvas(msp, hx + hw/2, hy + hh/2, hw, hh)
            else:
                _hueco_rect(msp, hx, hy, hw, hh)
            continue

        if tipo in ("grifo", "enchufe"):
            radio = R_GRIFO if tipo == "grifo" else R_ENCHUFE
            if dist_frente is None:
                # Default para enchufes en chapeado/frontal: centrado vertical (alto/2)
                parent_tipo = (pieza.get("tipo") or "").lower()
                if tipo == "enchufe" and parent_tipo in ("chapeado", "frontal", "pilastra", "costado"):
                    dist_frente = pieza_h / 2
                    defaults_log.append(
                        f"hueco[{idx}] enchufe en {parent_tipo}: distancia_frente_mm NO en nota → usado alto/2 = {dist_frente:.0f}mm")
                else:
                    print(f"    ⚠ Hueco {tipo} #{idx} omitido: falta distancia_frente_mm"); continue
            # Grifo/enchufe son círculos; distancia_lado_mm = al centro del círculo
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
    grosor_global = float(medidas.get("grosor_mm") or 0)

    dibujadas = 0
    omitidas  = []

    for i, pieza in enumerate(piezas):
        problemas = validar_pieza(pieza)
        # Separar problemas bloqueantes (geometría propia) de los no bloqueantes (huecos)
        bloqueantes = [p for p in problemas if not p.startswith("hueco[")]
        warn_huecos = [p for p in problemas if p.startswith("hueco[")]

        if bloqueantes:
            omitidas.append({"index": i + 1, "tipo": pieza.get("tipo"),
                              "notas": pieza.get("notas",""), "faltan": bloqueantes})
            print(f"  ⚠ Pieza #{i+1} ({pieza.get('tipo')}) OMITIDA — faltan: {', '.join(bloqueantes)}")
            continue

        if warn_huecos:
            print(f"  ⚠ Pieza #{i+1} se dibuja pero con huecos incompletos (se omiten esos huecos): {', '.join(warn_huecos)}")

        tipo = (pieza.get("tipo") or "").lower()
        w_p, h_p = _dims_para_cursor(pieza)
        x, y = cursor.siguiente(w_p, h_p)

        try:
            if tipo in ("encimera", "isla"):
                _dibujar_encimera(msp, pieza, x, y)
            elif tipo in ("chapeado", "frontal", "pilastra", "costado"):
                _dibujar_chapeado(msp, pieza, x, y, grosor_global=grosor_global)
            elif tipo in ("copete", "rodapie", "zocalo", "paso", "tabica"):
                _dibujar_tira(msp, pieza, x, y, grosor_global=grosor_global)
            else:
                # Genérico: solo si el usuario ha especificado ambas dimensiones
                w = float(pieza["largo_mm"])
                h_raw = pieza.get("alto_mm") or pieza.get("ancho_mm")
                if h_raw is None:
                    raise ValueError("sin alto_mm ni ancho_mm")
                _rect(msp, x, y, w, float(h_raw))
            dibujadas += 1
        except Exception as ex:
            omitidas.append({"index": i + 1, "tipo": pieza.get("tipo"),
                             "notas": pieza.get("notas",""), "faltan": [str(ex)]})
            print(f"  ⚠ Pieza #{i+1} ({pieza.get('tipo')}) OMITIDA al dibujar: {ex}")
            continue

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
