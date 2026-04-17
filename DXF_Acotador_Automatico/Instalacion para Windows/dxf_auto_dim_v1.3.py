#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║           DXF AUTO-DIMENSIONER  v1.3                     ║
║  Detecta piezas, huecos, descuadros → PDF anotado        ║
║  v1.3: acotación completa de formas no uniformes         ║
║         • cadena de cotas por segmentos (L, T, escal.)   ║
║         • cotas en aristas diagonales (longitud+ángulo)  ║
║         • radio en arcos/esquinas redondeadas            ║
║         • ángulos en esquinas no ortogonales             ║
║         • 4 cotas de posición por hueco                  ║
╚══════════════════════════════════════════════════════════╝
Uso:
    python dxf_auto_dim_v1.3.py archivo.dxf
    python dxf_auto_dim_v1.3.py archivo.dxf -o resultado.pdf
    python dxf_auto_dim_v1.3.py archivo.dxf -t 5.0
"""
import os, sys, re, math, argparse, datetime, warnings
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.path import Path as MplPath
from matplotlib.backends.backend_pdf import PdfPages
import networkx as nx

warnings.filterwarnings('ignore')

# ── CONFIGURACIÓN ──────────────────────────────────────────────────────────────
MIN_AREA    = 10.0   # mm²: área mínima de polígono válido
ARC_SEGS    = 48     # segmentos para aproximar arcos/círculos
DSQR_THR    = 0.12   # threshold descuadro: 12% de la dimensión menor
CORNER_ANGLE = 15.0  # grados: cambio de dirección mínimo para ser esquina real

# Colores
COL_DIM    = '#1155CC'
COL_CHAIN  = '#1155CC'   # cadenas de cotas (igual que DIM pero más delgado)
COL_HOLE   = '#CC4400'
COL_DIST   = '#007733'
COL_DSQR   = '#880099'
COL_DIAG   = '#0077AA'   # cotas de aristas diagonales
COL_ARC    = '#006688'   # cotas de radios
COL_ANGLE  = '#664400'   # anotaciones de ángulo
COL_PIECE  = '#1A1A1A'
COL_FILL   = '#F7F3EC'
COL_HFILL  = '#DDEEFF'
COL_GRID   = '#E5E5E5'

# ══════════════════════════════════════════════════════════════════════════════
#  PARSER DXF — soporta AC1009..AC1021
# ══════════════════════════════════════════════════════════════════════════════

def _parse_entity_pairs(pairs, blocks=None):
    """
    Extrae entidades geométricas de una lista de pares (code, value).
    Si se pasan blocks, expande INSERT con la geometría del bloque.
    Retorna lista de entidades.
    """
    SUPPORTED = {'LINE', 'ARC', 'CIRCLE', 'LWPOLYLINE', 'POLYLINE', 'VERTEX', 'SEQEND', 'INSERT', 'SPLINE'}
    entities = []
    cur = None
    in_polyline = False
    vertex_buf  = []
    cur_polyline = None

    for c, v in pairs:
        if c == 0:
            if cur and cur.get('type') not in ('VERTEX', 'SEQEND', 'INSERT', 'SPLINE', None):
                entities.append(cur)
            if cur and cur.get('type') == 'SPLINE':
                _flush_spline(cur, entities)
            if v == 'SEQEND' and in_polyline:
                if vertex_buf:
                    poly = {**cur_polyline, 'vertices': vertex_buf[:],
                            'type': 'LWPOLYLINE', 'closed': True}
                    entities.append(poly)
                in_polyline = False; vertex_buf = []; cur_polyline = None
            if v in SUPPORTED:
                cur = {'type': v, 'layer': '0', 'color': 256}
                if v == 'POLYLINE':
                    in_polyline = True; vertex_buf = []; cur_polyline = cur
                elif v == 'VERTEX' and in_polyline:
                    cur = {'type': 'VERTEX', '_x': 0.0, '_y': 0.0}
                elif v == 'SPLINE':
                    cur = {'type': 'SPLINE', 'layer': '0', '_knots': [], '_ctrl': [], '_fit': [],
                           '_degree': 3, '_flags': 0, '_pending_x': None}
            else:
                # Flush INSERT if blocks available
                if cur and cur.get('type') == 'INSERT' and blocks is not None:
                    _expand_insert(cur, blocks, entities)
                cur = None
            continue
        if cur is None: continue
        if c == 100: continue
        t = cur.get('type')
        if c == 8:   cur['layer'] = v
        elif c == 62:
            try: cur['color'] = int(v)
            except: pass
        if t == 'LINE':
            if   c == 10: cur['x1'] = float(v)
            elif c == 20: cur['y1'] = float(v)
            elif c == 11: cur['x2'] = float(v)
            elif c == 21: cur['y2'] = float(v)
        elif t in ('CIRCLE', 'ARC'):
            if   c == 10: cur['cx'] = float(v)
            elif c == 20: cur['cy'] = float(v)
            elif c == 40: cur['r']  = float(v)
            elif c == 50: cur['sa'] = float(v)
            elif c == 51: cur['ea'] = float(v)
        elif t == 'LWPOLYLINE':
            if   c == 70:
                try: cur['closed'] = bool(int(v) & 1)
                except: pass
            elif c == 10: cur.setdefault('vertices', []).append([float(v), 0.0])
            elif c == 20:
                if cur.get('vertices'): cur['vertices'][-1][1] = float(v)
        elif t == 'VERTEX':
            if   c == 10: cur['_x'] = float(v)
            elif c == 20:
                cur['_y'] = float(v)
                vertex_buf.append([cur['_x'], cur['_y']])
        elif t == 'INSERT':
            if   c == 2:  cur['block_name'] = v
            elif c == 10: cur['ix'] = float(v)
            elif c == 20: cur['iy'] = float(v)
            elif c == 41: cur['sx'] = float(v)
            elif c == 42: cur['sy'] = float(v)
            elif c == 50: cur['rot'] = float(v)
        elif t == 'SPLINE':
            if   c == 70:
                try: cur['_flags'] = int(v)
                except: pass
            elif c == 71:
                try: cur['_degree'] = int(v)
                except: pass
            elif c == 40:
                try: cur['_knots'].append(float(v))
                except: pass
            elif c == 10:
                try: cur['_pending_x'] = float(v)
                except: pass
            elif c == 20:
                if cur['_pending_x'] is not None:
                    cur['_ctrl'].append([cur['_pending_x'], float(v)])
                    cur['_pending_x'] = None
            elif c == 11:
                try: cur['_fit_pending_x'] = float(v)
                except: pass
            elif c == 21:
                px = cur.pop('_fit_pending_x', None)
                if px is not None:
                    cur['_fit'].append([px, float(v)])

    if cur and cur.get('type') not in ('VERTEX', 'SEQEND', None):
        if cur.get('type') == 'INSERT' and blocks is not None:
            _expand_insert(cur, blocks, entities)
        elif cur.get('type') == 'SPLINE':
            _flush_spline(cur, entities)
        elif cur.get('type') != 'INSERT':
            entities.append(cur)

    return entities


def _bspline_eval(degree, knots, ctrl_pts, n_samples=64):
    """
    Evalúa una B-spline usando el algoritmo de de Boor.
    Retorna lista de (x, y) puntos en la curva.
    """
    if len(ctrl_pts) < degree + 1 or len(knots) < 2:
        return ctrl_pts  # fallback: usar puntos de control directamente
    k = degree
    t = knots
    p = np.array(ctrl_pts, dtype=float)
    n = len(p) - 1
    t_min, t_max = t[k], t[n + 1] if n + 1 < len(t) else t[-1]
    if t_max <= t_min:
        return ctrl_pts

    result = []
    for u in np.linspace(t_min, t_max, n_samples, endpoint=False):
        # Find knot span
        if u >= t_max:
            u = t_max - 1e-10
        span = k
        for i in range(k, n + 1):
            if i + 1 < len(t) and t[i] <= u < t[i + 1]:
                span = i
                break
        # de Boor
        d = p[span - k:span + 1].copy()
        for r in range(1, k + 1):
            for j in range(k, r - 1, -1):
                ti = j + span - k
                denom = t[ti + k - r + 1] - t[ti] if ti + k - r + 1 < len(t) else 0
                alpha = (u - t[ti]) / denom if abs(denom) > 1e-12 else 0.0
                d[j] = (1 - alpha) * d[j - 1] + alpha * d[j]
        result.append((d[k][0], d[k][1]))
    return result


def _flush_spline(spline, entities):
    """Convierte un SPLINE en una LWPOLYLINE para procesamiento posterior."""
    fit_pts = spline.get('_fit', [])
    ctrl_pts = spline.get('_ctrl', [])
    knots = spline.get('_knots', [])
    degree = spline.get('_degree', 3)
    flags = spline.get('_flags', 0)
    closed = bool(flags & 1)

    if fit_pts:
        # Fit points lie on the curve — use directly
        verts = fit_pts
    elif ctrl_pts and knots:
        # Evaluate B-spline from control points + knots
        try:
            verts = _bspline_eval(degree, knots, ctrl_pts, n_samples=max(64, len(ctrl_pts) * 4))
        except Exception:
            verts = ctrl_pts  # fallback
    elif ctrl_pts:
        verts = ctrl_pts
    else:
        return

    if len(verts) < 3:
        return

    # Emit as LWPOLYLINE
    entities.append({
        'type': 'LWPOLYLINE',
        'layer': spline.get('layer', '0'),
        'color': spline.get('color', 256),
        'vertices': [list(p) for p in verts],
        'closed': closed,
    })


def _expand_insert(ins, blocks, entities):
    """Expande un INSERT aplicando transformación a las entidades del bloque."""
    bname = ins.get('block_name', '')
    if bname not in blocks:
        return
    ix = ins.get('ix', 0.0)
    iy = ins.get('iy', 0.0)
    sx = ins.get('sx', 1.0)
    sy = ins.get('sy', 1.0)
    rot_deg = ins.get('rot', 0.0)
    cos_r = math.cos(math.radians(rot_deg))
    sin_r = math.sin(math.radians(rot_deg))

    def tx(x, y):
        # Scale then rotate then translate
        xs = x * sx
        ys = y * sy
        return ix + xs * cos_r - ys * sin_r, iy + xs * sin_r + ys * cos_r

    for ent in blocks[bname]:
        import copy
        e = copy.deepcopy(ent)
        t = e.get('type')
        if t == 'LINE':
            e['x1'], e['y1'] = tx(e.get('x1',0), e.get('y1',0))
            e['x2'], e['y2'] = tx(e.get('x2',0), e.get('y2',0))
        elif t in ('CIRCLE', 'ARC'):
            e['cx'], e['cy'] = tx(e.get('cx',0), e.get('cy',0))
            e['r'] = e.get('r', 0) * max(abs(sx), abs(sy))
            if t == 'ARC':
                e['sa'] = (e.get('sa', 0) + rot_deg) % 360
                e['ea'] = (e.get('ea', 0) + rot_deg) % 360
        elif t == 'LWPOLYLINE':
            verts = e.get('vertices', [])
            e['vertices'] = [list(tx(p[0], p[1])) for p in verts]
        entities.append(e)


def _parse_blocks_section(pairs):
    """
    Extrae definiciones de bloques de la sección BLOCKS del DXF.
    Retorna dict {nombre_bloque: [entidades]}.
    Ignora bloques internos (nombres que empiezan con '*').
    """
    blocks = {}
    # Find BLOCKS section
    blk_start = blk_end = len(pairs)
    in_blk = False
    for idx, (c, v) in enumerate(pairs):
        if c == 2 and v == 'BLOCKS':
            blk_start = idx; in_blk = True
        elif in_blk and c == 0 and v == 'ENDSEC':
            blk_end = idx; break

    if blk_start == len(pairs):
        return blocks

    # Parse blocks
    current_name = None
    current_pairs = []
    in_block = False

    for c, v in pairs[blk_start:blk_end]:
        if c == 0 and v == 'BLOCK':
            current_pairs = []
            in_block = True
            current_name = None
        elif c == 0 and v == 'ENDBLK':
            if current_name and not current_name.startswith('*') and current_pairs:
                ents = _parse_entity_pairs(current_pairs)
                if ents:
                    blocks[current_name] = ents
            in_block = False
            current_name = None
            current_pairs = []
        elif in_block and c == 2 and current_name is None:
            current_name = v
        elif in_block and current_name:
            current_pairs.append((c, v))

    return blocks


def parse_dxf(filepath: str):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        raw = f.readlines()

    pairs = []
    i = 0
    while i + 1 < len(raw):
        try:
            pairs.append((int(raw[i].strip()), raw[i + 1].strip()))
        except ValueError:
            pass
        i += 2

    units_map = {1: 'pulgadas', 2: 'pies', 4: 'mm', 5: 'cm', 6: 'm'}
    meta = {'units': 4, 'units_name': 'mm'}
    for idx, (c, v) in enumerate(pairs):
        if c == 9 and v == '$INSUNITS' and idx + 1 < len(pairs):
            try:
                u = int(pairs[idx + 1][1])
                meta['units'] = u
                meta['units_name'] = units_map.get(u, f'u{u}')
            except:
                pass

    # Parse BLOCKS section first (for INSERT expansion)
    blocks = _parse_blocks_section(pairs)

    # Find ENTITIES section
    start = end = len(pairs)
    in_ent = False
    for idx, (c, v) in enumerate(pairs):
        if c == 2 and v == 'ENTITIES':
            start = idx; in_ent = True
        elif in_ent and c == 0 and v == 'ENDSEC':
            end = idx; break

    entities = _parse_entity_pairs(pairs[start:end], blocks=blocks)
    return entities, meta


# ══════════════════════════════════════════════════════════════════════════════
#  TOLERANCIA ADAPTATIVA
# ══════════════════════════════════════════════════════════════════════════════

def auto_tolerance(entities) -> float:
    lines = [e for e in entities if e['type'] == 'LINE']
    if len(lines) < 4: return 0.5
    pts = []
    for l in lines:
        pts.append((l.get('x1', 0), l.get('y1', 0)))
        pts.append((l.get('x2', 0), l.get('y2', 0)))
    gaps = []
    step = max(1, len(pts) // 200)
    for i in range(0, len(pts), step):
        for j in range(i + 1, min(i + 30, len(pts))):
            d = math.dist(pts[i], pts[j])
            if 0.01 < d < 20: gaps.append(d)
    if not gaps: return 0.5
    gaps.sort()
    p75 = gaps[int(len(gaps) * 0.75)]
    return max(0.5, min(p75 * 1.5, 15.0))


# ══════════════════════════════════════════════════════════════════════════════
#  GEOMETRÍA BÁSICA
# ══════════════════════════════════════════════════════════════════════════════

def arc_pts(cx, cy, r, sa, ea, n=ARC_SEGS):
    if ea <= sa: ea += 360.0
    t = np.linspace(math.radians(sa), math.radians(ea), n + 1)
    return list(zip(cx + r * np.cos(t), cy + r * np.sin(t)))

def circle_pts(cx, cy, r, n=ARC_SEGS * 2):
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return list(zip(cx + r * np.cos(t), cy + r * np.sin(t)))

def poly_area(coords):
    n = len(coords)
    if n < 3: return 0.0
    xs = np.array([p[0] for p in coords])
    ys = np.array([p[1] for p in coords])
    return abs(np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1))) / 2.0

def poly_centroid(coords):
    return sum(p[0] for p in coords)/len(coords), sum(p[1] for p in coords)/len(coords)

def bounding_box(coords):
    xs = [p[0] for p in coords]; ys = [p[1] for p in coords]
    return min(xs), min(ys), max(xs), max(ys)

def pt_in_poly(px, py, coords):
    if len(coords) < 3: return False
    path = MplPath(coords + [coords[0]])
    return bool(path.contains_point((px, py)))

def snap(x, y, tol):
    inv = 1.0 / tol
    return (round(x * inv) / inv, round(y * inv) / inv)

def perimeter(coords):
    n = len(coords)
    return sum(math.dist(coords[i], coords[(i+1)%n]) for i in range(n))


# ══════════════════════════════════════════════════════════════════════════════
#  ANÁLISIS DE FORMA: ESQUINAS Y ARISTAS
# ══════════════════════════════════════════════════════════════════════════════

def find_corners(coords, min_angle_deg=CORNER_ANGLE):
    """
    Detecta esquinas verdaderas donde cambia la dirección ≥ min_angle_deg.
    Filtra puntos de interpolación de arcos (cambio ~1.9° en 48 segmentos/90°).
    Devuelve lista de índices.
    """
    n = len(coords)
    if n < 4:
        return list(range(n))
    corners = []
    for i in range(n):
        a = coords[(i - 1) % n]
        b = coords[i]
        c = coords[(i + 1) % n]
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-6 or l2 < 1e-6: continue
        cos_a = max(-1.0, min(1.0, (v1[0]*v2[0] + v1[1]*v2[1]) / (l1 * l2)))
        if math.degrees(math.acos(cos_a)) >= min_angle_deg:
            corners.append(i)
    return corners  # puede ser vacío → indica forma curvilínea pura


def fit_circle_lstsq(pts):
    """
    Ajuste mínimos cuadrados de círculo a puntos.
    Devuelve (cx, cy, r) o None si el ajuste es malo.
    """
    if len(pts) < 4:
        return None
    xs = np.array([p[0] for p in pts], dtype=float)
    ys = np.array([p[1] for p in pts], dtype=float)
    A = np.column_stack([2*xs, 2*ys, np.ones(len(xs))])
    b = xs**2 + ys**2
    try:
        res, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        cx, cy = res[0], res[1]
        r = math.sqrt(max(0, res[2] + cx**2 + cy**2))
        if r < 1e-3: return None
        residuals = np.abs(np.sqrt((xs-cx)**2 + (ys-cy)**2) - r)
        if np.mean(residuals) < r * 0.06:
            return (cx, cy, r)
    except Exception:
        pass
    return None


def _circumradius3(a, b, c):
    """
    Radio del círculo circunscrito a 3 puntos.
    Usa R = |ab|·|bc|·|ca| / (2·|cross|) — numéricamente estable
    incluso con coordenadas grandes (evita cancelación catastrófica).
    Devuelve inf si los puntos son colineales.
    """
    ab = math.dist(a, b)
    bc = math.dist(b, c)
    ca = math.dist(c, a)
    # Área del triángulo usando cross product con coordenadas relativas a 'a'
    bx, by = b[0]-a[0], b[1]-a[1]
    cx_, cy_ = c[0]-a[0], c[1]-a[1]
    cross = abs(bx*cy_ - by*cx_)
    if cross < 1e-12: return float('inf')
    return (ab * bc * ca) / (2.0 * cross)


def _get_edges_by_curvature(coords):
    """
    Clasificación de aristas por radio de curvatura local.
    Usado cuando las esquinas no son detectables por cambio de dirección
    (e.g. arcos tangentes a rectas — unión suave, 0° de cambio de dirección).
    Agrupa puntos consecutivos con radio similar: arco vs. recta.
    """
    n = len(coords)
    bb = bounding_box(coords)
    diag = math.dist((bb[0], bb[1]), (bb[2], bb[3]))
    # Umbral: arcos reales tienen radio << diag; rectas tienen radio → ∞
    arc_thr = diag * 0.45

    # Calcular radio circunscrito en cada punto
    radii = [_circumradius3(coords[(i-1)%n], coords[i], coords[(i+1)%n]) for i in range(n)]

    # Etiquetar: 'arc' si radio < umbral, 'straight' en caso contrario
    labels = ['arc' if r < arc_thr else 'straight' for r in radii]

    # Buscar punto de inicio en un cambio de etiqueta (para no empezar en mitad de un run)
    start = 0
    for i in range(n):
        if labels[i] != labels[(i-1)%n]:
            start = i; break

    # Construir runs de etiquetas iguales — sin bug de off-by-one en el wrap
    runs = []
    consumed = 0
    idx = start
    while consumed < n:
        lbl = labels[idx % n]
        run_len = 0
        while consumed + run_len < n and labels[(idx + run_len) % n] == lbl:
            run_len += 1
        if run_len == 0:
            break
        # Incluir el punto de cierre (inicio del próximo run) para que las aristas conecten
        run_pts = [coords[(idx + k) % n] for k in range(run_len + 1)]
        runs.append({'label': lbl, 'pts': run_pts})
        idx      = (idx + run_len) % n
        consumed += run_len

    ORTHO_TOL = 5.0
    edges = []
    for run in runs:
        pts = run['pts']
        if len(pts) < 2: continue
        p0, p1 = pts[0], pts[-1]
        chord = math.dist(p0, p1)
        if chord < 0.5: continue

        if run['label'] == 'arc' and len(pts) >= 3:
            circ = fit_circle_lstsq(pts)
            if circ:
                cx, cy, r = circ
                edges.append({'type': 'arc', 'start': p0, 'end': p1, 'pts': pts,
                              'length': round(chord, 2), 'radius': round(r, 2),
                              'arc_cx': cx, 'arc_cy': cy})
                continue

        dx, dy = p1[0]-p0[0], p1[1]-p0[1]
        angle = math.degrees(math.atan2(dy, dx))
        abs_a = abs(angle % 180)
        if abs_a < ORTHO_TOL or abs_a > 180-ORTHO_TOL:   etype = 'horiz'
        elif abs(abs_a - 90) < ORTHO_TOL:                  etype = 'vert'
        else:                                               etype = 'diag'
        edges.append({'type': etype, 'start': p0, 'end': p1, 'pts': pts,
                      'length': round(chord, 2), 'angle_deg': round(angle, 2)})
    return edges


def get_shape_edges(coords):
    """
    Clasifica cada arista del polígono como:
      'horiz' → horizontal
      'vert'  → vertical
      'diag'  → oblicua recta
      'arc'   → arco circular
    Devuelve lista de dicts con: type, start, end, pts, length, + datos propios.

    Estrategia dual:
      1. Buscar esquinas reales (cambio de dirección ≥ CORNER_ANGLE).
         Si hay esquinas → segmentar entre ellas.
      2. Si no hay esquinas (uniones tangentes, forma curvilínea):
         usar clasificación por radio de curvatura local.
    """
    corners_idx = find_corners(coords)

    # Sin esquinas reales (e.g. forma con arcos tangentes, 0° de cambio de dirección)
    # → fallback a curvatura
    if not corners_idx or len(corners_idx) < 3:
        return _get_edges_by_curvature(coords)

    # Muchas esquinas detectadas en un polígono GRANDE → probable problema de arcos tangentes.
    # Polígonos pequeños (≤ 20 puntos) son formas simples: todas sus esquinas son reales.
    # Solo activar curvatura para polígonos grandes con alta proporción de "esquinas".
    if len(coords) >= 20 and len(corners_idx) >= len(coords) * 0.6:
        return _get_edges_by_curvature(coords)

    n   = len(coords)
    nc  = len(corners_idx)
    edges = []
    ORTHO_TOL = 5.0

    for i in range(nc):
        i0 = corners_idx[i]
        i1 = corners_idx[(i + 1) % nc]

        if i1 >= i0:
            seg_pts = coords[i0:i1 + 1]
        else:
            seg_pts = coords[i0:] + coords[:i1 + 1]

        if len(seg_pts) < 2:
            continue

        p0    = seg_pts[0]
        p1    = seg_pts[-1]
        chord = math.dist(p0, p1)
        if chord < 0.01:
            continue

        edge = {'start': p0, 'end': p1, 'pts': seg_pts, 'length': round(chord, 2)}

        # Muchos puntos intermedios → candidato a arco
        if len(seg_pts) >= 5:
            circle = fit_circle_lstsq(seg_pts)
            if circle is not None:
                cx, cy, r = circle
                edge.update({'type': 'arc', 'radius': round(r, 2),
                             'arc_cx': cx, 'arc_cy': cy})
                edges.append(edge)
                continue

        # Arista recta — clasificar por ángulo
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        angle = math.degrees(math.atan2(dy, dx))
        edge['angle_deg'] = round(angle, 2)

        abs_a = abs(angle % 180)
        if abs_a < ORTHO_TOL or abs_a > 180 - ORTHO_TOL:
            edge['type'] = 'horiz'
        elif abs(abs_a - 90) < ORTHO_TOL:
            edge['type'] = 'vert'
        else:
            edge['type'] = 'diag'

        edges.append(edge)

    return edges


def corner_angle_deg(a, b, c):
    """Ángulo interior en el vértice b (entre segmentos a→b y b→c)."""
    v1 = (a[0]-b[0], a[1]-b[1])
    v2 = (c[0]-b[0], c[1]-b[1])
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if l1 < 1e-6 or l2 < 1e-6: return 90.0
    cos_a = max(-1.0, min(1.0, (v1[0]*v2[0]+v1[1]*v2[1])/(l1*l2)))
    return math.degrees(math.acos(cos_a))


# ══════════════════════════════════════════════════════════════════════════════
#  EXTRACCIÓN DE CONTORNOS
# ══════════════════════════════════════════════════════════════════════════════

def extract_contours(entities, tol):
    segments    = []
    direct_polys = []
    for e in entities:
        t = e['type']
        if t == 'CIRCLE':
            cx = e.get('cx', 0); cy = e.get('cy', 0); r = e.get('r', 0)
            if r > 0: direct_polys.append(circle_pts(cx, cy, r))
        elif t == 'ARC':
            cx = e.get('cx', 0); cy = e.get('cy', 0)
            r = e.get('r', 0); sa = e.get('sa', 0); ea = e.get('ea', 0)
            if r <= 0: continue
            pts = arc_pts(cx, cy, r, sa, ea)
            sp = snap(pts[0][0], pts[0][1], tol)
            ep = snap(pts[-1][0], pts[-1][1], tol)
            if math.dist(sp, ep) < tol * 2:
                direct_polys.append(pts)
            else:
                # Los puntos intermedios del arco NO se snapean para preservar
                # la precisión geométrica necesaria para detectar radios de arco.
                # Solo los extremos se snapean para la conectividad.
                mid = [(p[0], p[1]) for p in pts[1:-1]]
                segments.append((sp, ep, mid))
        elif t == 'LINE':
            x1=e.get('x1',0); y1=e.get('y1',0); x2=e.get('x2',0); y2=e.get('y2',0)
            if math.dist((x1,y1),(x2,y2)) < tol*0.1: continue
            sp = snap(x1,y1,tol); ep = snap(x2,y2,tol)
            if sp != ep: segments.append((sp, ep, []))
        elif t == 'LWPOLYLINE':
            verts = e.get('vertices', [])
            if len(verts) < 3: continue
            pts = [(v[0], v[1]) for v in verts]
            closed = e.get('closed', False)
            if not closed: closed = math.dist(pts[0], pts[-1]) < tol*2
            if closed:
                if math.dist(pts[0], pts[-1]) < tol: pts = pts[:-1]
                direct_polys.append(pts)
            else:
                for i in range(len(pts)-1):
                    sp = snap(pts[i][0],pts[i][1],tol)
                    ep = snap(pts[i+1][0],pts[i+1][1],tol)
                    if sp != ep: segments.append((sp,ep,[]))
    return direct_polys, segments


def chain_segments(segments):
    if not segments: return []
    G = nx.Graph(); seg_mid = {}
    for s, e, mid in segments:
        if not G.has_edge(s, e):
            G.add_edge(s, e)
            seg_mid[(s,e)] = mid
            seg_mid[(e,s)] = list(reversed(mid))
    polys = []
    try: cycles = nx.cycle_basis(G)
    except: return []
    for cycle in cycles:
        if len(cycle) < 3: continue
        pts = []
        for i in range(len(cycle)):
            a = cycle[i]; b = cycle[(i+1)%len(cycle)]
            pts.append((a[0], a[1]))
            for mx,my in seg_mid.get((a,b), seg_mid.get((b,a), [])):
                pts.append((mx, my))
        if poly_area(pts) >= MIN_AREA: polys.append(pts)
    return polys


def all_polygons(entities, tol):
    direct, segments = extract_contours(entities, tol)
    chained = chain_segments(segments)
    all_p = [pts for pts in direct if poly_area(pts) >= MIN_AREA] + chained
    unique = []
    for pts in all_p:
        cx, cy = poly_centroid(pts); a = poly_area(pts)
        if not any(abs(a-poly_area(q)) < max(a*0.01,2.0) and
                   math.dist((cx,cy),poly_centroid(q)) < tol*6 for q in unique):
            unique.append(pts)
    return unique


# ══════════════════════════════════════════════════════════════════════════════
#  DETECCIÓN DE PIEZAS Y HUECOS
# ══════════════════════════════════════════════════════════════════════════════

def build_pieces(polygons):
    if not polygons: return []
    by_area = sorted(polygons, key=poly_area, reverse=True)
    used = [False] * len(by_area)
    pieces = []
    for i, outer in enumerate(by_area):
        if used[i]: continue
        used[i] = True; holes = []
        outer_area = poly_area(outer)
        for j in range(i+1, len(by_area)):
            if used[j]: continue
            inner = by_area[j]
            if poly_area(inner) > outer_area * 0.70: continue
            cx, cy = poly_centroid(inner)
            if not pt_in_poly(cx, cy, outer): continue
            if any(pt_in_poly(cx, cy, h) for h in holes): continue
            holes.append(inner); used[j] = True
        pieces.append({'index': len(pieces)+1, 'outer': outer, 'holes': holes})
    return pieces


# ══════════════════════════════════════════════════════════════════════════════
#  MEDICIONES
# ══════════════════════════════════════════════════════════════════════════════

def measure_hole(hcoords, piece_bb):
    minx, miny, maxx, maxy = bounding_box(hcoords)
    cx, cy = (minx+maxx)/2, (miny+maxy)/2
    hw, hh = maxx-minx, maxy-miny
    area_h = poly_area(hcoords)
    r_enc  = max(hw, hh) / 2
    circ   = area_h / (math.pi * r_enc**2) if r_enc > 0 else 0
    is_circ = circ > 0.80 and abs(hw-hh) < max(hw,hh)*0.20
    p_minx, p_miny, p_maxx, p_maxy = piece_bb
    return {
        'coords':      hcoords,
        'cx': cx, 'cy': cy,
        'width':       round(hw, 2),
        'height':      round(hh, 2),
        'area':        round(area_h, 2),
        'is_circle':   is_circ,
        'radius':      round((hw+hh)/4, 2),
        'dist_left':   round(minx - p_minx, 2),
        'dist_right':  round(p_maxx - maxx, 2),
        'dist_bottom': round(miny - p_miny, 2),
        'dist_top':    round(p_maxy - maxy, 2),
    }


def measure_descuadro(outer, minx, miny, maxx, maxy):
    w, h = maxx-minx, maxy-miny
    result = {}
    def pts_near_val(axis, val, frac=0.12):
        t = max(min(w,h)*frac, 2.0)
        return [(x,y) for x,y in outer if abs((x if axis=='x' else y)-val) < t]
    for side, axis, val in [('left','x',minx),('right','x',maxx),
                             ('top','y',maxy),('bottom','y',miny)]:
        pts = sorted(pts_near_val(axis, val), key=lambda p: p[1 if axis=='x' else 0])
        if len(pts) >= 2:
            d = round((pts[-1][0]-pts[0][0]) if axis=='x' else (pts[-1][1]-pts[0][1]), 2)
            if abs(d) >= 0.5: result[side] = d
    return result


def classify_shape(outer):
    n = len(outer)
    if n <= 6:  return 'rectangular'
    if n <= 12: return 'irregular'
    return 'curvilíneo'


def measure_piece(piece):
    outer = piece['outer']
    minx, miny, maxx, maxy = bounding_box(outer)
    bb = (minx, miny, maxx, maxy)
    dq = measure_descuadro(outer, minx, miny, maxx, maxy)
    return {
        'width':     round(maxx-minx, 2),
        'height':    round(maxy-miny, 2),
        'area':      round(poly_area(outer), 2),
        'perimeter': round(perimeter(outer), 2),
        'shape':     classify_shape(outer),
        'minx': minx, 'miny': miny, 'maxx': maxx, 'maxy': maxy,
        'cx': (minx+maxx)/2, 'cy': (miny+maxy)/2,
        'holes':     [measure_hole(h, bb) for h in piece['holes']],
        'descuadro': dq,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  FUNCIONES DE DIBUJO BÁSICAS
# ══════════════════════════════════════════════════════════════════════════════

def draw_poly(ax, coords, edge=COL_PIECE, fill=COL_FILL, lw=1.8, zorder=2):
    pts = list(coords) + [coords[0]]
    xs, ys = zip(*pts)
    if fill: ax.fill(xs, ys, color=fill, zorder=zorder-1)
    ax.plot(xs, ys, color=edge, lw=lw, zorder=zorder,
            solid_capstyle='round', solid_joinstyle='round')


def dim_h(ax, x1, x2, y, label, dy=0, color=COL_DIM, fs=7):
    yd = y + dy
    if abs(x2-x1) < 0.01: return
    ax.annotate('', xy=(x2,yd), xytext=(x1,yd),
                arrowprops=dict(arrowstyle='<->', color=color, lw=1.1, mutation_scale=9))
    ax.plot([x1,x1],[y,yd], color=color, lw=0.6, ls='--', zorder=3)
    ax.plot([x2,x2],[y,yd], color=color, lw=0.6, ls='--', zorder=3)
    ax.text((x1+x2)/2, yd, f' {label} ', ha='center', va='center',
            fontsize=fs, color=color, zorder=5,
            bbox=dict(boxstyle='round,pad=0.15', fc='white', ec=color, lw=0.5, alpha=0.93))


def dim_v(ax, y1, y2, x, label, dx=0, color=COL_DIM, fs=7):
    xd = x + dx
    if abs(y2-y1) < 0.01: return
    ax.annotate('', xy=(xd,y2), xytext=(xd,y1),
                arrowprops=dict(arrowstyle='<->', color=color, lw=1.1, mutation_scale=9))
    ax.plot([x,xd],[y1,y1], color=color, lw=0.6, ls='--', zorder=3)
    ax.plot([x,xd],[y2,y2], color=color, lw=0.6, ls='--', zorder=3)
    ax.text(xd, (y1+y2)/2, f' {label} ', ha='center', va='center',
            fontsize=fs, color=color, rotation=90, zorder=5,
            bbox=dict(boxstyle='round,pad=0.15', fc='white', ec=color, lw=0.5, alpha=0.93))


def draw_descuadro_indicator(ax, side, value, minx, miny, maxx, maxy, gap):
    color = COL_DSQR; sign = '+' if value > 0 else ''
    if side == 'left':
        x0,y0 = minx,miny; x1,y1 = minx+value,maxy
        label = f'⊠ IZQ {sign}{value:.2f}'; lx,ly = minx-gap*0.5,(miny+maxy)/2
    elif side == 'right':
        x0,y0 = maxx,miny; x1,y1 = maxx+value,maxy
        label = f'⊠ DER {sign}{value:.2f}'; lx,ly = maxx+gap*0.5,(miny+maxy)/2
    elif side == 'top':
        x0,y0 = minx,maxy; x1,y1 = maxx,maxy+value
        label = f'⊠ SUP {sign}{value:.2f}'; lx,ly = (minx+maxx)/2,maxy+gap*0.5
    else:
        x0,y0 = minx,miny; x1,y1 = maxx,miny+value
        label = f'⊠ INF {sign}{value:.2f}'; lx,ly = (minx+maxx)/2,miny-gap*0.5
    ax.annotate('', xy=(x1,y1), xytext=(x0,y0),
                arrowprops=dict(arrowstyle='->', color=color, lw=2.0, mutation_scale=11), zorder=6)
    ax.text(lx, ly, label, ha='center', va='center', fontsize=7.5, color=color,
            zorder=7, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', fc='#F8EEFF', ec=color, lw=0.8, alpha=0.95))


def compute_dim_gap(w, h):
    short = min(w, h); long_ = max(w, h)
    gap = short * 0.09 + long_ * 0.025
    return max(12.0, min(gap, 70.0))


# ══════════════════════════════════════════════════════════════════════════════
#  ACOTACIÓN AVANZADA DE FORMAS NO UNIFORMES
# ══════════════════════════════════════════════════════════════════════════════

def draw_chain_dims_h(ax, ref_pts, miny, gap, units, color=COL_CHAIN):
    """Cadena de cotas horizontales. Solo usa X valores de los puntos dados."""
    xs = sorted(set(round(p[0], 1) for p in ref_pts))
    if len(xs) < 2: return

    # Coordenada Y más baja para cada X (de dónde parte la línea de referencia)
    low_y = {}
    for p in ref_pts:
        xr = round(p[0], 1)
        if xr not in low_y or p[1] < low_y[xr]:
            low_y[xr] = p[1]

    has_steps = len(xs) > 2

    if has_steps:
        y_seg = miny - gap * 1.35
        y_tot = miny - gap * 2.75

        for i in range(len(xs) - 1):
            x1, x2 = xs[i], xs[i+1]
            d = x2 - x1
            if d < 0.5: continue
            lbl = f"{d:.0f}" if d >= 10 else f"{d:.2f}"
            yf1 = low_y.get(x1, miny)
            yf2 = low_y.get(x2, miny)
            ax.plot([x1,x1],[yf1,y_seg], color=color, lw=0.4, ls=':', zorder=3, alpha=0.55)
            ax.plot([x2,x2],[yf2,y_seg], color=color, lw=0.4, ls=':', zorder=3, alpha=0.55)
            ax.annotate('', xy=(x2,y_seg), xytext=(x1,y_seg),
                        arrowprops=dict(arrowstyle='<->', color=color, lw=0.9, mutation_scale=7.5))
            ax.text((x1+x2)/2, y_seg, f' {lbl} ', ha='center', va='center',
                    fontsize=6.0, color=color, zorder=5,
                    bbox=dict(boxstyle='round,pad=0.10', fc='white', ec=color, lw=0.35, alpha=0.93))
    else:
        y_tot = miny - gap * 1.9

    total = xs[-1] - xs[0]
    lbl_tot = f"{total:.2f} {units}"
    ax.plot([xs[0],xs[0]], [miny,y_tot], color=color, lw=0.6, ls='--', zorder=3)
    ax.plot([xs[-1],xs[-1]], [miny,y_tot], color=color, lw=0.6, ls='--', zorder=3)
    ax.annotate('', xy=(xs[-1],y_tot), xytext=(xs[0],y_tot),
                arrowprops=dict(arrowstyle='<->', color=color, lw=1.2, mutation_scale=10))
    ax.text((xs[0]+xs[-1])/2, y_tot, f' {lbl_tot} ', ha='center', va='center',
            fontsize=8 if not has_steps else 7.5, color=color, fontweight='bold', zorder=5,
            bbox=dict(boxstyle='round,pad=0.16', fc='white', ec=color, lw=0.6, alpha=0.95))


def draw_chain_dims_v(ax, ref_pts, maxx, gap, units, color=COL_CHAIN):
    """Cadena de cotas verticales. Solo usa Y valores de los puntos dados."""
    ys = sorted(set(round(p[1], 1) for p in ref_pts))
    if len(ys) < 2: return

    high_x = {}
    for p in ref_pts:
        yr = round(p[1], 1)
        if yr not in high_x or p[0] > high_x[yr]:
            high_x[yr] = p[0]

    has_steps = len(ys) > 2

    if has_steps:
        x_seg = maxx + gap * 1.35
        x_tot = maxx + gap * 2.75

        for i in range(len(ys) - 1):
            y1, y2 = ys[i], ys[i+1]
            d = y2 - y1
            if d < 0.5: continue
            lbl = f"{d:.0f}" if d >= 10 else f"{d:.2f}"
            xf1 = high_x.get(y1, maxx)
            xf2 = high_x.get(y2, maxx)
            ax.plot([xf1,x_seg],[y1,y1], color=color, lw=0.4, ls=':', zorder=3, alpha=0.55)
            ax.plot([xf2,x_seg],[y2,y2], color=color, lw=0.4, ls=':', zorder=3, alpha=0.55)
            ax.annotate('', xy=(x_seg,y2), xytext=(x_seg,y1),
                        arrowprops=dict(arrowstyle='<->', color=color, lw=0.9, mutation_scale=7.5))
            ax.text(x_seg, (y1+y2)/2, f' {lbl} ', ha='center', va='center',
                    fontsize=6.0, color=color, rotation=90, zorder=5,
                    bbox=dict(boxstyle='round,pad=0.10', fc='white', ec=color, lw=0.35, alpha=0.93))
    else:
        x_tot = maxx + gap * 1.9

    total = ys[-1] - ys[0]
    lbl_tot = f"{total:.2f} {units}"
    ax.plot([maxx,x_tot],[ys[0],ys[0]], color=color, lw=0.6, ls='--', zorder=3)
    ax.plot([maxx,x_tot],[ys[-1],ys[-1]], color=color, lw=0.6, ls='--', zorder=3)
    ax.annotate('', xy=(x_tot,ys[-1]), xytext=(x_tot,ys[0]),
                arrowprops=dict(arrowstyle='<->', color=color, lw=1.2, mutation_scale=10))
    ax.text(x_tot, (ys[0]+ys[-1])/2, f' {lbl_tot} ', ha='center', va='center',
            fontsize=8 if not has_steps else 7.5, color=color, fontweight='bold',
            rotation=90, zorder=5,
            bbox=dict(boxstyle='round,pad=0.16', fc='white', ec=color, lw=0.6, alpha=0.95))


def draw_edge_label(ax, p0, p1, label, color=COL_DIAG, fs=6.0):
    """
    Cota de longitud + ángulo sobre una arista diagonal.
    Flecha paralela al segmento, offset perpendicular al exterior.
    """
    dx, dy = p1[0]-p0[0], p1[1]-p0[1]
    length = math.hypot(dx, dy)
    if length < 0.5: return

    # Normal perpendicular (izq del vector de dirección)
    nx, ny = -dy/length, dx/length
    offset = max(8.0, length * 0.05)

    # Puntos del segmento de cota (paralelos al borde, offset hacia afuera)
    a0 = (p0[0]+nx*offset, p0[1]+ny*offset)
    a1 = (p1[0]+nx*offset, p1[1]+ny*offset)

    ax.annotate('', xy=a1, xytext=a0,
                arrowprops=dict(arrowstyle='<->', color=color, lw=0.9, mutation_scale=8))
    # Líneas de referencia del borde a la cota
    ax.plot([p0[0],a0[0]], [p0[1],a0[1]], color=color, lw=0.4, ls=':', zorder=3, alpha=0.55)
    ax.plot([p1[0],a1[0]], [p1[1],a1[1]], color=color, lw=0.4, ls=':', zorder=3, alpha=0.55)

    # Rotación del texto alineada con el segmento
    angle = math.degrees(math.atan2(dy, dx))
    if angle > 90:  angle -= 180
    if angle < -90: angle += 180

    mx, my = (a0[0]+a1[0])/2, (a0[1]+a1[1])/2
    ax.text(mx, my, f' {label} ', ha='center', va='center',
            fontsize=fs, color=color, rotation=angle, zorder=5,
            bbox=dict(boxstyle='round,pad=0.12', fc='white', ec=color, lw=0.4, alpha=0.93))


def draw_arc_radius(ax, pts_arc, radius, arc_cx, arc_cy, color=COL_ARC, gap=20, fs=6.5):
    """Etiqueta R=xx en el punto medio de un arco."""
    mid = pts_arc[len(pts_arc)//2]
    dx, dy = mid[0]-arc_cx, mid[1]-arc_cy
    d = math.hypot(dx, dy)
    if d < 0.01: return
    nd = dx/d, dy/d
    # línea desde centro hacia el arco
    ax.plot([arc_cx, mid[0]], [arc_cy, mid[1]],
            color=color, lw=0.6, ls='-.', zorder=4, alpha=0.65)
    ax.plot(arc_cx, arc_cy, '+', color=color, ms=5, mew=1.0, zorder=5)
    offset = gap * 0.55
    lx, ly = mid[0]+nd[0]*offset, mid[1]+nd[1]*offset
    ax.text(lx, ly, f' R{radius:.1f} ', ha='center', va='center',
            fontsize=fs, color=color, zorder=6,
            bbox=dict(boxstyle='round,pad=0.12', fc='#E8F6FF', ec=color, lw=0.45, alpha=0.93))


def draw_circle_leader(ax, hcx, hcy, r, diameter_label, m, gap, color=COL_HOLE):
    """
    Dibuja un hueco circular con línea de referencia (leader) y flecha.
    El texto se sitúa fuera de la zona congestionada, en la dirección
    del borde de la pieza más cercano al centro del hueco.
    """
    # ── Determinar dirección del leader ──────────────────────────────────────
    # Calcular posición relativa del hueco respecto al centro de la pieza
    half_w = m['width']  / 2.0
    half_h = m['height'] / 2.0
    rel_x = (hcx - m['cx']) / half_w if half_w > 0 else 0.0
    rel_y = (hcy - m['cy']) / half_h if half_h > 0 else 0.0

    # Elegir la cara más cercana → leader sale hacia fuera por ahí
    if abs(rel_y) >= abs(rel_x):
        angle_deg = 90.0 if rel_y >= 0 else -90.0   # arriba o abajo
    else:
        angle_deg = 0.0 if rel_x >= 0 else 180.0    # derecha o izquierda

    angle_rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)

    # ── Longitud del leader ───────────────────────────────────────────────────
    # Suficientemente largo para salir del relleno del hueco y del área de cotas
    leader_len = max(gap * 1.8, r * 5.0, 50.0)

    # Punto de tangencia en el borde del círculo
    px, py = hcx + cos_a * r, hcy + sin_a * r

    # Posición del texto (más allá del borde)
    tx, ty = hcx + cos_a * (r + leader_len), hcy + sin_a * (r + leader_len)

    # ── Dibujo ────────────────────────────────────────────────────────────────
    # Cruz central
    ax.plot(hcx, hcy, '+', color=color, ms=7, mew=1.3, zorder=6)

    # Línea de radio (del centro al borde del círculo, en la dirección del leader)
    ax.plot([hcx, px], [hcy, py], color=color, lw=0.8, ls='-.', zorder=5)

    # Flecha desde texto hasta borde del círculo
    ax.annotate('', xy=(px, py), xytext=(tx, ty),
                arrowprops=dict(arrowstyle='->', color=color,
                                lw=1.0, mutation_scale=10))

    # Etiqueta del diámetro con caja bien visible
    ax.text(tx, ty, f' {diameter_label} ',
            ha='center', va='center',
            fontsize=8.5, color=color, fontweight='bold', zorder=8,
            bbox=dict(boxstyle='round,pad=0.3', fc='white',
                      ec=color, lw=0.8, alpha=0.98))


def draw_corner_angle(ax, corner, prev_pt, next_pt, gap, color=COL_ANGLE):
    """
    Marca ángulo en una esquina:
      - 90°: pequeño cuadrado
      - otro: texto con el ángulo
    Solo se dibuja si el ángulo es significativamente distinto de 90°.
    """
    v1 = (prev_pt[0]-corner[0], prev_pt[1]-corner[1])
    v2 = (next_pt[0]-corner[0], next_pt[1]-corner[1])
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if l1 < 1e-6 or l2 < 1e-6: return
    v1n = (v1[0]/l1, v1[1]/l1)
    v2n = (v2[0]/l2, v2[1]/l2)
    cos_a = max(-1.0, min(1.0, v1n[0]*v2n[0]+v1n[1]*v2n[1]))
    angle = math.degrees(math.acos(cos_a))

    size = min(gap*0.28, min(l1,l2)*0.18, 15.0)

    if abs(angle-90) < 8:
        # Cuadradito de ángulo recto
        p1 = (corner[0]+v1n[0]*size, corner[1]+v1n[1]*size)
        p2 = (corner[0]+v2n[0]*size, corner[1]+v2n[1]*size)
        pm = (p1[0]+v2n[0]*size, p1[1]+v2n[1]*size)
        ax.plot([p1[0],pm[0],p2[0]], [p1[1],pm[1],p2[1]],
                color=color, lw=0.6, zorder=4, alpha=0.6)
    else:
        # Ángulo de texto
        mid_dir = ((v1n[0]+v2n[0])/2, (v1n[1]+v2n[1])/2)
        md = math.hypot(*mid_dir)
        if md < 0.01: return
        mid_dir = (mid_dir[0]/md, mid_dir[1]/md)
        dist = size * 2.0 + gap * 0.15
        lx = corner[0] + mid_dir[0]*dist
        ly = corner[1] + mid_dir[1]*dist
        ax.text(lx, ly, f'{angle:.1f}°', ha='center', va='center',
                fontsize=5.5, color=color, zorder=5, alpha=0.92,
                bbox=dict(boxstyle='round,pad=0.08', fc='#FFFAF0',
                          ec=color, lw=0.3, alpha=0.88))


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER — PÁGINA DE PIEZA  (v1.3)
# ══════════════════════════════════════════════════════════════════════════════

def render_piece_page(piece, m, pdf, dxf_name, page_num, total_pages, units='mm'):
    fig, ax = plt.subplots(figsize=(11.69, 8.27))  # A4 apaisado

    gap = compute_dim_gap(m['width'], m['height'])

    # ── Análisis de forma ─────────────────────────────────────────────────────
    outer = piece['outer']
    edges = get_shape_edges(outer)
    has_arcs  = any(e['type'] == 'arc'  for e in edges)
    has_diags = any(e['type'] == 'diag' for e in edges)

    # Esquinas reales para marcas de ángulo
    corners_idx = find_corners(outer)
    corner_pts  = [outer[i] for i in corners_idx] if corners_idx else []

    # Cadena de cotas: solo usar X/Y de aristas ORTOGONALES (H o V).
    # Los extremos de aristas diagonales/arcos no van en la cadena ortogonal;
    # se anotan directamente sobre la propia arista.
    h_xs: set = {round(m['minx'], 1), round(m['maxx'], 1)}
    v_ys: set = {round(m['miny'], 1), round(m['maxy'], 1)}
    for e in edges:
        if e['type'] == 'horiz':
            # Solo añadir X si el segmento es REALMENTE horizontal (|dy| mínimo)
            if abs(e['end'][1] - e['start'][1]) < 0.5:
                h_xs.update([round(e['start'][0],1), round(e['end'][0],1)])
            v_ys.update([round(e['start'][1],1), round(e['end'][1],1)])
        elif e['type'] == 'vert':
            # Solo añadir X si el segmento es REALMENTE vertical (|dx| mínimo)
            if abs(e['end'][0] - e['start'][0]) < 0.5:
                h_xs.update([round(e['start'][0],1), round(e['end'][0],1)])
            v_ys.update([round(e['start'][1],1), round(e['end'][1],1)])

    has_steps_h = len(h_xs) > 2
    has_steps_v = len(v_ys) > 2

    # Puntos de referencia para líneas de testigo de la cadena
    chain_ref_pts = [(p[0], p[1]) for p in outer
                     if round(p[0],1) in h_xs or round(p[1],1) in v_ys]

    # Padding adaptativo
    chain_levels = max(2 if has_steps_h else 1, 2 if has_steps_v else 1)
    pad = gap * (3.2 + chain_levels * 0.9 + (0.6 if has_diags or has_arcs else 0))
    pad = min(pad, max(m['width'], m['height']) * 0.6)

    ax.set_xlim(m['minx'] - pad, m['maxx'] + pad)
    ax.set_ylim(m['miny'] - pad, m['maxy'] + pad)
    ax.set_aspect('equal', adjustable='datalim')
    ax.set_facecolor('#F9F9F9')
    ax.grid(True, color=COL_GRID, lw=0.4, zorder=0)
    ax.tick_params(labelsize=6)
    ax.set_xlabel(f'X ({units})', fontsize=7)
    ax.set_ylabel(f'Y ({units})', fontsize=7)

    # ── Pieza y huecos ────────────────────────────────────────────────────────
    draw_poly(ax, outer, edge=COL_PIECE, fill=COL_FILL, lw=2.0)
    for h in piece['holes']:
        draw_poly(ax, h, edge='#334466', fill=COL_HFILL, lw=1.4)

    # ── Número watermark ──────────────────────────────────────────────────────
    fsize = max(14, min(m['width'], m['height']) / 10)
    ax.text(m['cx'], m['cy'], f"#{piece['index']}",
            ha='center', va='center', fontsize=fsize,
            color='#00000015', fontweight='bold', zorder=1)

    # ── COTAS PRINCIPALES: cadenas horizontales y verticales ──────────────────
    draw_chain_dims_h(ax, chain_ref_pts, m['miny'], gap, units, COL_DIM)
    draw_chain_dims_v(ax, chain_ref_pts, m['maxx'], gap, units, COL_DIM)

    # ── ARISTAS DIAGONALES: longitud + ángulo ─────────────────────────────────
    for e in edges:
        if e['type'] == 'diag':
            a = e['angle_deg']
            a_display = abs(a) if abs(a) <= 90 else 180 - abs(a)
            lbl = f"{e['length']:.1f}  {a_display:.1f}°"
            draw_edge_label(ax, e['start'], e['end'], lbl, COL_DIAG)

    # ── ARCOS: etiqueta de radio ───────────────────────────────────────────────
    # Deduplica por radio para no anotar el mismo radio múltiples veces
    labeled_radii = set()
    for e in edges:
        if e['type'] == 'arc':
            r_key = round(e['radius'], 0)
            draw_arc_radius(ax, e['pts'], e['radius'],
                           e['arc_cx'], e['arc_cy'], COL_ARC, gap)
            labeled_radii.add(r_key)

    # ── ÁNGULOS EN ESQUINAS ────────────────────────────────────────────────────
    if corner_pts:
        nc = len(corner_pts)
        for i in range(nc):
            draw_corner_angle(ax,
                              corner_pts[i],
                              corner_pts[(i-1) % nc],
                              corner_pts[(i+1) % nc],
                              gap, COL_ANGLE)

    # ── COTAS DE HUECOS ───────────────────────────────────────────────────────
    for idx, hd in enumerate(m['holes']):
        hcx, hcy = hd['cx'], hd['cy']
        hw, hh2  = hd['width'], hd['height']
        gs = gap * 0.55

        if hd['is_circle']:
            r = hd['radius']
            draw_circle_leader(ax, hcx, hcy, r, f'Ø{r*2:.2f}', m, gap, COL_HOLE)
        else:
            # Ancho del hueco
            dy_h = -gs if hcy < m['cy'] else gs
            y_h  = hcy - hh2/2 if hcy < m['cy'] else hcy + hh2/2
            dim_h(ax, hcx-hw/2, hcx+hw/2, y_h, f"{hw:.2f}",
                  dy=dy_h, color=COL_HOLE, fs=6.5)
            # Alto del hueco
            dim_v(ax, hcy-hh2/2, hcy+hh2/2, hcx+hw/2,
                  f"{hh2:.2f}", dx=gs, color=COL_HOLE, fs=6.5)

        # ── Posición del hueco: las 4 distancias a bordes ─────────────────
        gs2 = gs * 0.65

        # Izquierda
        if hd['dist_left'] > 1.0:
            dim_h(ax, m['minx'], hcx-hw/2, hcy,
                  f"{hd['dist_left']:.2f}", dy=gs2, color=COL_DIST, fs=6)
        # Derecha
        if hd['dist_right'] > 1.0:
            dim_h(ax, hcx+hw/2, m['maxx'], hcy,
                  f"{hd['dist_right']:.2f}", dy=gs2, color=COL_DIST, fs=6)
        # Inferior
        if hd['dist_bottom'] > 1.0:
            dim_v(ax, m['miny'], hcy-hh2/2, hcx-hw/2,
                  f"{hd['dist_bottom']:.2f}", dx=-gs2, color=COL_DIST, fs=6)
        # Superior
        if hd['dist_top'] > 1.0:
            dim_v(ax, hcy+hh2/2, m['maxy'], hcx-hw/2,
                  f"{hd['dist_top']:.2f}", dx=-gs2, color=COL_DIST, fs=6)

        # Distancia entre huecos consecutivos
        if idx > 0:
            prev = m['holes'][idx-1]
            inter = (hcx-hw/2) - (prev['cx']+prev['width']/2)
            if inter > 1.0:
                mid_y = min(hcy, prev['cy'])
                dim_h(ax, prev['cx']+prev['width']/2, hcx-hw/2,
                      mid_y, f"e:{inter:.2f}",
                      dy=-gs*0.5, color=COL_DIST, fs=6)

    # ── DESCUADROS ────────────────────────────────────────────────────────────
    for side, val in m['descuadro'].items():
        draw_descuadro_indicator(ax, side, val,
                                  m['minx'], m['miny'], m['maxx'], m['maxy'], gap)

    # ── LEYENDA ───────────────────────────────────────────────────────────────
    legend_items = [
        mpatches.Patch(color=COL_DIM,  label=f"Ext: {m['width']:.1f}×{m['height']:.1f} {units}"),
    ]
    if has_steps_h or has_steps_v:
        legend_items.append(mpatches.Patch(color=COL_CHAIN,
                                            label='Cadena de cotas (pasos)'))
    if has_diags:
        legend_items.append(mpatches.Patch(color=COL_DIAG,  label='Aristas oblicuas (long.+ángulo)'))
    if has_arcs:
        legend_items.append(mpatches.Patch(color=COL_ARC,   label='Radios de arco'))
    if m['holes']:
        legend_items.append(mpatches.Patch(color=COL_HOLE,  label='Huecos'))
        legend_items.append(mpatches.Patch(color=COL_DIST,  label='Dist. a bordes (4 lados)'))
    if m['descuadro']:
        legend_items.append(mpatches.Patch(color=COL_DSQR,  label='Descuadros'))
    ax.legend(handles=legend_items, loc='lower right',
              fontsize=6.0, framealpha=0.92)

    # ── TÍTULO ────────────────────────────────────────────────────────────────
    shape_lbl = {'rectangular': '▭', 'irregular': '⬠', 'curvilíneo': '⬭'}
    edge_tags = []
    if has_steps_h or has_steps_v: edge_tags.append('escalon.')
    if has_diags:  edge_tags.append('oblicua')
    if has_arcs:   edge_tags.append('arco')
    shape_desc = m['shape'] + (f" [{', '.join(edge_tags)}]" if edge_tags else '')
    ax.set_title(
        f"{shape_lbl.get(m['shape'],'')} PIEZA #{piece['index']}   —   {dxf_name}   [{shape_desc}]",
        fontsize=9.5, fontweight='bold', pad=6)

    # ── FICHA INFERIOR ────────────────────────────────────────────────────────
    info = (f"Ancho: {m['width']:.2f} {units}   Alto: {m['height']:.2f} {units}   "
            f"Área: {m['area']:.0f} {units}²   "
            f"Perímetro: {m['perimeter']:.0f} {units}   "
            f"Huecos: {len(m['holes'])}   "
            f"Descuadros: {len(m['descuadro'])}")
    ax.text(0.5, -0.06, info, transform=ax.transAxes,
            ha='center', va='top', fontsize=7.5, color='#222222',
            bbox=dict(boxstyle='round,pad=0.3', fc='#FFFDE7', ec='#CCAA00', lw=0.8))
    ax.text(1.0, -0.06, f"Pág. {page_num} / {total_pages}",
            transform=ax.transAxes, ha='right', va='top', fontsize=7, color='#666666')

    fig.tight_layout()
    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER — PORTADA / RESUMEN
# ══════════════════════════════════════════════════════════════════════════════

def extract_filename_info(filepath):
    stem = Path(filepath).stem
    info = {'raw': stem, 'ref': '—', 'date': '—', 'desc': stem}
    m = re.search(r'\b(\d{4,})\b', stem)
    if m: info['ref'] = m.group(1)
    dm = re.search(r'(\d{4}[-_]\d{2}[-_]\d{2})', stem)
    if dm: info['date'] = dm.group(1).replace('_','-')
    else:
        dm2 = re.search(r'(\d{2}[-_]\d{2}[-_]\d{4})', stem)
        if dm2: info['date'] = dm2.group(1).replace('_','-')
    desc = re.sub(r'\d{4,}','',stem); desc = re.sub(r'\d{2}[-_]\d{2}[-_]\d{4}','',desc)
    desc = re.sub(r'[-_]+',' ',desc).strip()
    if desc: info['desc'] = desc.title()
    return info


def render_summary_page(pieces_data, dxf_path, pdf, tol_used, units='mm'):
    fig = plt.figure(figsize=(11.69, 8.27))
    gs  = fig.add_gridspec(3, 1, height_ratios=[0.16, 0.28, 0.56],
                           hspace=0.38, left=0.04, right=0.96,
                           top=0.94, bottom=0.04)
    ax_head  = fig.add_subplot(gs[0])
    ax_prev  = fig.add_subplot(gs[1])
    ax_table = fig.add_subplot(gs[2])
    for a in (ax_head, ax_prev, ax_table): a.axis('off')

    finfo  = extract_filename_info(dxf_path)
    total  = len(pieces_data)
    holes  = sum(len(pd['measurements']['holes']) for pd in pieces_data)
    area_t = sum(pd['measurements']['area'] for pd in pieces_data)
    gen    = datetime.datetime.now().strftime('%Y-%m-%d  %H:%M')
    n_desq = sum(1 for pd in pieces_data if pd['measurements']['descuadro'])

    header = (f"DXF AUTO-DIMENSIONER  v1.3    •    {Path(dxf_path).name}\n"
              f"Ref: {finfo['ref']}   •   Desc: {finfo['desc']}   •   "
              f"Generado: {gen}   •   Tol: {tol_used} mm")
    ax_head.text(0.5, 0.70, header, transform=ax_head.transAxes,
                 ha='center', va='center', fontsize=8.5,
                 bbox=dict(boxstyle='round,pad=0.5', fc='#1A3A6A', ec='#0A1A4A', lw=1.5),
                 color='white', fontfamily='monospace')
    stats = (f"Piezas: {total}   |   Huecos totales: {holes}   |   "
             f"Piezas con descuadro: {n_desq}   |   Área total: {area_t:.0f} {units}²")
    ax_head.text(0.5, 0.08, stats, transform=ax_head.transAxes,
                 ha='center', va='center', fontsize=8.5, color='#222222', fontweight='bold')

    # Miniaturas
    max_p = min(total, 10); cols = min(max_p, 10)
    for k in range(max_p):
        pd = pieces_data[k]; p = pd['piece']; m = pd['measurements']
        span = 0.88 / cols
        mini = fig.add_axes([0.05 + k*span, 0.52, span*0.92, 0.20])
        mini.set_aspect('equal', adjustable='datalim'); mini.axis('off')
        oc = p['outer']; xs, ys = zip(*oc)
        pad_m = max(m['width'], m['height']) * 0.12 + 2
        mini.set_xlim(m['minx']-pad_m, m['maxx']+pad_m)
        mini.set_ylim(m['miny']-pad_m, m['maxy']+pad_m)
        mini.fill(list(xs)+[xs[0]], list(ys)+[ys[0]], color=COL_FILL, zorder=1)
        mini.plot(list(xs)+[xs[0]], list(ys)+[ys[0]], color=COL_PIECE, lw=1.0, zorder=2)
        for h in p['holes']:
            hx, hy = zip(*h)
            mini.fill(list(hx)+[hx[0]], list(hy)+[hy[0]], color='white', zorder=3)
            mini.plot(list(hx)+[hx[0]], list(hy)+[hy[0]], color='#334466', lw=0.7, zorder=4)
        dq_sym = ' ⊠' if m['descuadro'] else ''
        mini.set_title(f"#{p['index']}{dq_sym}", fontsize=6.5, pad=2)
        mini.set_facecolor('#F2F2F2')

    # Tabla
    cols_lbl = ['#', 'Forma', f'Ancho ({units})', f'Alto ({units})',
                f'Área ({units}²)', 'Huecos', 'Aristas', '⊠ IZQ', '⊠ DER', '⊠ SUP', '⊠ INF']
    rows = []
    for pd in pieces_data:
        p, m = pd['piece'], pd['measurements']
        dq = m['descuadro']
        edges = get_shape_edges(p['outer'])
        arc_cnt  = sum(1 for e in edges if e['type'] == 'arc')
        diag_cnt = sum(1 for e in edges if e['type'] == 'diag')
        aristas  = []
        if arc_cnt:  aristas.append(f"{arc_cnt}arc")
        if diag_cnt: aristas.append(f"{diag_cnt}diag")
        rows.append([
            f"#{p['index']}",
            m['shape'],
            f"{m['width']:.2f}",
            f"{m['height']:.2f}",
            f"{m['area']:.0f}",
            str(len(m['holes'])),
            ', '.join(aristas) if aristas else '—',
            f"{dq['left']:.2f}"   if 'left'   in dq else '—',
            f"{dq['right']:.2f}"  if 'right'  in dq else '—',
            f"{dq['top']:.2f}"    if 'top'    in dq else '—',
            f"{dq['bottom']:.2f}" if 'bottom' in dq else '—',
        ])

    if rows:
        tbl = ax_table.table(cellText=rows, colLabels=cols_lbl,
                             loc='center', bbox=[0.0, 0.02, 1.0, 0.95])
        tbl.auto_set_font_size(False); tbl.set_fontsize(7.0)
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor('#CCCCCC')
            if r == 0:
                cell.set_facecolor('#1A3A6A')
                cell.set_text_props(color='white', fontweight='bold')
            elif r % 2 == 0:
                cell.set_facecolor('#EEF3FF')
            else:
                cell.set_facecolor('#FFFFFF')
            if r > 0 and c >= 7:
                if rows[r-1][c] != '—':
                    cell.set_facecolor('#FFF0FF')
                    cell.set_text_props(color=COL_DSQR, fontweight='bold')
            if r > 0 and c == 5 and rows[r-1][c] != '0':
                cell.set_facecolor('#FFF3E0')
                cell.set_text_props(color='#884400', fontweight='bold')
            if r > 0 and c == 6 and rows[r-1][c] != '—':
                cell.set_facecolor('#E8F6FF')
                cell.set_text_props(color=COL_ARC, fontweight='bold')

    ax_table.text(0.5, 0.0,
                  '⊠ = Descuadro (mm)  |  arc = arco/radio  |  diag = arista oblicua',
                  transform=ax_table.transAxes, ha='center', va='top',
                  fontsize=6.5, color='#666666', style='italic')

    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ══════════════════════════════════════════════════════════════════════════════
#  RESOLUCIÓN PATH DE SALIDA
# ══════════════════════════════════════════════════════════════════════════════

def resolve_output_path(input_path, output_arg=None):
    if output_arg: return output_arg
    pdf_name = Path(input_path).stem + '.pdf'
    candidate = str(Path(input_path).parent / pdf_name)
    try:
        with open(candidate, 'ab') as _: pass
        return candidate
    except OSError:
        return str(Path.cwd() / pdf_name)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(
        description='DXF Auto-Dimensioner v1.3 → PDF con acotaciones completas')
    p.add_argument('dxf_file')
    p.add_argument('-o', '--output',    default=None)
    p.add_argument('-t', '--tolerance', type=float, default=None)
    p.add_argument('-m', '--min-area',  type=float, default=MIN_AREA)
    p.add_argument('-v', '--verbose',   action='store_true')
    return p.parse_args()


def main():
    args   = parse_args()
    dxf_in = args.dxf_file

    if not os.path.exists(dxf_in):
        print(f"✗ No se encontró: {dxf_in}")
        sys.exit(1)

    out = resolve_output_path(dxf_in, args.output)

    print(f"\n{'═'*58}")
    print(f"  DXF AUTO-DIMENSIONER  v1.3")
    print(f"{'═'*58}")
    print(f"  Entrada : {dxf_in}")
    print(f"  Salida  : {out}")
    print(f"{'─'*58}")

    print("→ Parseando DXF...")
    try:
        entities, meta = parse_dxf(dxf_in)
    except Exception as ex:
        print(f"✗ Error leyendo DXF: {ex}"); sys.exit(1)

    units = meta['units_name']
    counts = {}
    for e in entities:
        counts[e['type']] = counts.get(e['type'], 0) + 1
    print(f"  {sum(counts.values())} entidades  |  unidades: {units}")
    for t, n in sorted(counts.items()):
        print(f"    {t:<16} {n}")

    if args.tolerance is not None:
        tol = args.tolerance
        print(f"  Tolerancia (manual): {tol} mm")
    else:
        tol = auto_tolerance(entities)
        print(f"  Tolerancia (auto):   {tol} mm")

    print("→ Extrayendo contornos...")
    polygons = all_polygons(entities, tol)
    print(f"  Polígonos cerrados: {len(polygons)}")

    if not polygons:
        print(f"\n✗ No se detectaron polígonos. Prueba: -t {tol*3:.1f}")
        sys.exit(1)

    print("→ Detectando piezas y huecos...")
    pieces = build_pieces(polygons)
    print(f"  Piezas: {len(pieces)}")
    for p in pieces:
        a = poly_area(p['outer'])
        print(f"    #{p['index']}: área={a:.0f} {units}², huecos={len(p['holes'])}")

    print("→ Calculando medidas y clasificando aristas...")
    pieces_data = []
    for p in pieces:
        m = measure_piece(p)
        edges = get_shape_edges(p['outer'])
        arc_cnt  = sum(1 for e in edges if e['type'] == 'arc')
        diag_cnt = sum(1 for e in edges if e['type'] == 'diag')
        corners  = find_corners(p['outer'])
        xs_u = len(set(round(p['outer'][i][0],1) for i in corners))
        ys_u = len(set(round(p['outer'][i][1],1) for i in corners))
        tags = []
        if xs_u > 2 or ys_u > 2: tags.append(f"cadena X={xs_u} Y={ys_u}")
        if diag_cnt: tags.append(f"{diag_cnt} diag")
        if arc_cnt:  tags.append(f"{arc_cnt} arcos")
        dq = ', '.join(f"{k}={v:.2f}" for k,v in m['descuadro'].items())
        print(f"    #{p['index']}: {m['width']:.2f}×{m['height']:.2f} {units}  "
              f"[{m['shape']}]"
              + (f"  ({', '.join(tags)})" if tags else '')
              + (f"  ⊠ [{dq}]" if dq else ''))
        pieces_data.append({'piece': p, 'measurements': m})

    total_pgs = len(pieces) + 1
    print(f"\n→ Generando PDF ({total_pgs} páginas)...")

    try:
        with PdfPages(out) as pdf:
            render_summary_page(pieces_data, dxf_in, pdf, tol_used=tol, units=units)
            print("  ✓ Portada/resumen")
            for i, pd in enumerate(pieces_data):
                render_piece_page(
                    pd['piece'], pd['measurements'], pdf,
                    Path(dxf_in).name,
                    page_num=i+2, total_pages=total_pgs,
                    units=units)
                print(f"  ✓ Pieza #{pd['piece']['index']}")
    except Exception as ex:
        print(f"\n✗ Error generando PDF: {ex}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    print(f"\n{'═'*58}")
    print(f"  ✓  {out}")
    print(f"     {len(pieces)} piezas · {total_pgs} páginas")
    print(f"{'═'*58}\n")


if __name__ == '__main__':
    main()
