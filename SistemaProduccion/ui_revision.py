"""
ui_revision.py — UI de revisión humana del extractor de medidas.

Flujo:
  1. Usuario introduce número de orden (ej. J0042)
  2. Backend descarga de Trello la imagen de medidas y llama al extractor Claude
  3. UI muestra la nota + lista editable de piezas
  4. Usuario valida/corrige y pulsa "Generar DXF"
  5. Backend genera el DXF con dxf_produccion.py y lo deja disponible para descarga

Arranque:
  export ANTHROPIC_API_KEY=sk-ant-...
  python3 SistemaProduccion/ui_revision.py      # http://127.0.0.1:5000
"""

import os
import json
import shutil
import subprocess
import traceback
from pathlib import Path

from flask import (
    Flask, request, redirect, url_for, render_template_string,
    send_file, jsonify, abort,
)

# Imports del mismo paquete
import sys
sys.path.insert(0, str(Path(__file__).parent))
from trello_client import cargar_config, TrelloClient
from medidas_extractor import extraer_medidas
from anotador import anotar_pieza
from sintetizador import sintetizar_piezas
import dxf_produccion


# ── Configuración ─────────────────────────────────────────────────────────────

BASE_DIR  = Path(__file__).parent.parent
DATA_DIR  = BASE_DIR / "revisiones"        # persiste entre runs
DATA_DIR.mkdir(exist_ok=True)

DIMENSIONER_SCRIPT = BASE_DIR / "dxf_auto_dim_v1.3.py"

MODELO_EXTRACCION = "claude-opus-4-7"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB


# ── Utilidades ────────────────────────────────────────────────────────────────

def carpeta_orden(numero: str) -> Path:
    p = DATA_DIR / numero.upper()
    p.mkdir(exist_ok=True)
    return p


def cargar_estado(numero: str) -> dict:
    """Carga el JSON de medidas más reciente (corregido si existe, original si no)."""
    carp = carpeta_orden(numero)
    for nombre in ("medidas_corregidas.json", "medidas_originales.json"):
        p = carp / nombre
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return {}


def guardar_corregidas(numero: str, medidas: dict) -> Path:
    carp = carpeta_orden(numero)
    dest = carp / "medidas_corregidas.json"
    dest.write_text(json.dumps(medidas, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


# ── Rutas ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    # Lista de órdenes ya procesadas
    ordenes = []
    for sub in sorted(DATA_DIR.iterdir()):
        if not sub.is_dir(): continue
        estado = "sin procesar"
        if (sub / "medidas_corregidas.json").exists():
            estado = "corregida"
        elif (sub / "medidas_originales.json").exists():
            estado = "extraída"
        tiene_dxf = (sub / "produccion.dxf").exists()
        ordenes.append({"numero": sub.name, "estado": estado, "dxf": tiene_dxf})

    return render_template_string(TPL_INDEX, ordenes=ordenes)


@app.route("/procesar", methods=["POST"])
def procesar():
    """
    Descarga imágenes de la tarjeta y crea el estado inicial.

    Parámetro `modo`:
      - "anotar" (default): crea estado vacío, el usuario dibuja anotaciones pieza a pieza
      - "auto": llama a Claude extraer_medidas como sugerencia inicial
    """
    numero = request.form.get("numero", "").strip().upper()
    modo   = request.form.get("modo", "anotar")
    if not numero:
        return redirect(url_for("index"))

    try:
        carp = carpeta_orden(numero)
        trello = cargar_config()
        card = trello.buscar_tarjeta(numero)
        if not card:
            return f"Tarjeta {numero} no encontrada en Cobrado", 404

        (carp / "card_info.json").write_text(
            json.dumps({"id": card["id"], "name": card["name"]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        imgs = trello.descargar_adjuntos(card["id"], carp / "imagenes", solo_imagenes=True)
        if not imgs:
            return f"La tarjeta {numero} no tiene imágenes adjuntas", 400

        imgs.sort(key=lambda p: p.stat().st_size, reverse=True)

        if modo == "auto":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                return "Error: ANTHROPIC_API_KEY no está exportada", 500
            datos = extraer_medidas(imgs, api_key=api_key, modelo=MODELO_EXTRACCION)
            datos.setdefault("piezas", [])
            datos["_imagen_usada"] = imgs[0].name
        else:
            # Modo anotación: estado vacío, el usuario añadirá piezas a mano
            datos = {
                "cliente": "",
                "numero": numero,
                "material": "",
                "notas_generales": "",
                "piezas": [],
                "anotaciones": [],
                "_imagen_usada": imgs[0].name,
            }

        datos["_imagenes_disponibles"] = [p.name for p in imgs]
        datos.setdefault("anotaciones", [])

        (carp / "medidas_originales.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (carp / "medidas_corregidas.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        return f"<pre>{traceback.format_exc()}</pre>", 500

    return redirect(url_for("revisar", numero=numero))


@app.route("/revisar/<numero>")
def revisar(numero):
    numero = numero.upper()
    carp = carpeta_orden(numero)
    if not (carp / "medidas_corregidas.json").exists():
        return redirect(url_for("index"))

    datos = cargar_estado(numero)
    imgs = [p.name for p in (carp / "imagenes").iterdir()] if (carp / "imagenes").exists() else []
    imagen_actual = datos.get("_imagen_usada") or (imgs[0] if imgs else None)

    return render_template_string(
        TPL_REVISAR,
        numero=numero,
        datos=datos,
        datos_json=json.dumps(datos, ensure_ascii=False),
        imagenes=imgs,
        imagen_actual=imagen_actual,
    )


@app.route("/guardar/<numero>", methods=["POST"])
def guardar(numero):
    numero = numero.upper()
    try:
        medidas = request.get_json(force=True)
        guardar_corregidas(numero, medidas)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/dxf/<numero>", methods=["POST"])
def generar_dxf(numero):
    numero = numero.upper()
    try:
        medidas = request.get_json(force=True)
        guardar_corregidas(numero, medidas)

        carp = carpeta_orden(numero)
        salida = carp / "produccion.dxf"
        dxf_produccion.generar_dxf(medidas, salida)
        return jsonify({"ok": True, "dxf": str(salida.name)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/imagen/<numero>/<nombre>")
def imagen(numero, nombre):
    carp = carpeta_orden(numero)
    p = carp / "imagenes" / nombre
    if not p.exists():
        abort(404)
    return send_file(p)


@app.route("/descargar/<numero>/<archivo>")
def descargar(numero, archivo):
    carp = carpeta_orden(numero)
    p = carp / archivo
    if not p.exists():
        abort(404)
    return send_file(p, as_attachment=True)


@app.route("/ver/<numero>/<archivo>")
def ver(numero, archivo):
    """Sirve un archivo inline (el navegador lo abre en vez de descargar)."""
    carp = carpeta_orden(numero)
    p = carp / archivo
    if not p.exists():
        abort(404)
    return send_file(p, as_attachment=False)


@app.route("/reiniciar/<numero>", methods=["POST"])
def reiniciar(numero):
    """Restaura el estado al JSON original (descartando correcciones)."""
    numero = numero.upper()
    carp = carpeta_orden(numero)
    orig = carp / "medidas_originales.json"
    if orig.exists():
        shutil.copy(orig, carp / "medidas_corregidas.json")
    return jsonify({"ok": True})


@app.route("/reextraer/<numero>", methods=["POST"])
def reextraer(numero):
    """
    Re-ejecuta Claude sobre una imagen específica (la que el usuario marque
    como la nota de medidas). Sobrescribe medidas_originales y corregidas.
    """
    numero = numero.upper()
    try:
        payload = request.get_json(force=True)
        imagen = payload.get("imagen")
        if not imagen:
            return jsonify({"ok": False, "error": "Falta nombre de imagen"}), 400

        carp = carpeta_orden(numero)
        img_path = carp / "imagenes" / imagen
        if not img_path.exists():
            return jsonify({"ok": False, "error": f"No existe {imagen}"}), 404

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"ok": False, "error": "ANTHROPIC_API_KEY no exportada"}), 500

        datos = extraer_medidas([img_path], api_key=api_key, modelo=MODELO_EXTRACCION)
        datos.setdefault("piezas", [])
        datos["_imagen_usada"] = imagen
        # Mantener la lista de imágenes disponibles
        imgs_disp = sorted(
            (p.name for p in (carp / "imagenes").iterdir() if p.is_file()),
            key=lambda n: (carp / "imagenes" / n).stat().st_size,
            reverse=True,
        )
        datos["_imagenes_disponibles"] = imgs_disp

        (carp / "medidas_originales.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (carp / "medidas_corregidas.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return jsonify({"ok": True, "piezas": len(datos["piezas"]),
                        "tokens_in": datos.get("_tokens_input"),
                        "tokens_out": datos.get("_tokens_output")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e),
                        "trace": traceback.format_exc()}), 500


@app.route("/anotar/<numero>", methods=["POST"])
def anotar(numero):
    """
    Fase 1 (contexto): solo persiste la anotación. NO llama a Claude. Las piezas
    se deducen en la fase 2 (/sintetizar) a partir del conjunto de anotaciones.

    Body JSON: {imagen, bbox_norm:[x1,y1,x2,y2], descripcion}
    """
    numero = numero.upper()
    try:
        payload = request.get_json(force=True)
        imagen      = payload.get("imagen")
        bbox_norm   = payload.get("bbox_norm")
        descripcion = (payload.get("descripcion") or "").strip()

        if not imagen or not bbox_norm or not descripcion:
            return jsonify({"ok": False, "error": "Faltan campos (imagen/bbox_norm/descripcion)"}), 400

        carp = carpeta_orden(numero)
        if not (carp / "imagenes" / imagen).exists():
            return jsonify({"ok": False, "error": f"No existe {imagen}"}), 404

        datos = cargar_estado(numero)
        if not datos:
            datos = {"piezas": [], "anotaciones": [], "numero": numero}
        datos.setdefault("piezas", [])
        datos.setdefault("anotaciones", [])

        import datetime
        aid = max((a.get("id", 0) for a in datos["anotaciones"]), default=0) + 1
        anotacion = {
            "id":          aid,
            "imagen":      imagen,
            "bbox_norm":   bbox_norm,
            "descripcion": descripcion,
            "timestamp":   datetime.datetime.now().isoformat(timespec="seconds"),
        }
        datos["anotaciones"].append(anotacion)
        # Marcar que las piezas (si existen) están desactualizadas
        datos["piezas_stale"] = bool(datos.get("piezas"))
        guardar_corregidas(numero, datos)
        return jsonify({"ok": True, "anotacion": anotacion,
                        "total_anotaciones": len(datos["anotaciones"])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e),
                        "trace": traceback.format_exc()}), 500


@app.route("/borrar_anotacion/<numero>/<int:ann_id>", methods=["POST"])
def borrar_anotacion(numero, ann_id):
    """Elimina una anotación. Las piezas sintetizadas se marcan como desactualizadas."""
    numero = numero.upper()
    try:
        datos = cargar_estado(numero)
        if not datos or not datos.get("anotaciones"):
            return jsonify({"ok": False, "error": "Sin anotaciones"}), 404

        before = len(datos["anotaciones"])
        datos["anotaciones"] = [a for a in datos["anotaciones"] if a.get("id") != ann_id]
        if len(datos["anotaciones"]) == before:
            return jsonify({"ok": False, "error": "Anotación no encontrada"}), 404
        # Si había piezas, ahora están desactualizadas
        if datos.get("piezas"):
            datos["piezas_stale"] = True
        guardar_corregidas(numero, datos)
        return jsonify({"ok": True, "piezas_stale": bool(datos.get("piezas_stale"))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/sintetizar/<numero>", methods=["POST"])
def sintetizar(numero):
    """
    Fase 2: analiza todas las anotaciones y devuelve la lista final de piezas
    con razonamiento. Reemplaza datos.piezas con el resultado.
    """
    numero = numero.upper()
    try:
        datos = cargar_estado(numero)
        if not datos or not datos.get("anotaciones"):
            return jsonify({"ok": False, "error": "No hay anotaciones para sintetizar"}), 400

        carp = carpeta_orden(numero)
        imagenes_dir = carp / "imagenes"

        resultado = sintetizar_piezas(datos["anotaciones"], imagenes_dir)

        datos["piezas"]              = resultado.get("piezas", [])
        datos["razonamiento_global"] = resultado.get("razonamiento_global", "")
        datos["anotaciones_contextuales_ids"] = resultado.get("anotaciones_contextuales_ids", [])
        datos["piezas_stale"] = False
        import datetime
        datos["ultima_sintesis"] = datetime.datetime.now().isoformat(timespec="seconds")

        guardar_corregidas(numero, datos)
        meta = resultado.get("_meta", {})
        return jsonify({
            "ok":                  True,
            "piezas":              datos["piezas"],
            "razonamiento_global": datos["razonamiento_global"],
            "anotaciones_contextuales_ids": datos["anotaciones_contextuales_ids"],
            "tokens_in":           meta.get("input_tokens"),
            "tokens_out":          meta.get("output_tokens"),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e),
                        "trace": traceback.format_exc()}), 500


@app.route("/pdf/<numero>", methods=["POST"])
def generar_pdf(numero):
    """Genera el PDF acotado a partir del DXF actual usando dxf_auto_dim_v1.3.py."""
    numero = numero.upper()
    try:
        carp = carpeta_orden(numero)
        dxf = carp / "produccion.dxf"
        if not dxf.exists():
            # Auto-generar DXF primero si no existe
            medidas = request.get_json(force=True, silent=True) or cargar_estado(numero)
            if not medidas:
                return jsonify({"ok": False, "error": "Genera primero el DXF"}), 400
            guardar_corregidas(numero, medidas)
            dxf_produccion.generar_dxf(medidas, dxf)

        pdf = carp / "produccion.pdf"
        proc = subprocess.run(
            ["python3", str(DIMENSIONER_SCRIPT), str(dxf), "-o", str(pdf)],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            return jsonify({"ok": False, "error": "Dimensioner falló",
                            "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}), 500
        return jsonify({"ok": True, "pdf": pdf.name, "log": proc.stdout[-1500:]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e),
                        "trace": traceback.format_exc()}), 500


# ── Plantillas HTML (inline) ──────────────────────────────────────────────────

TPL_INDEX = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Revisión de medidas</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; }
form { display: flex; gap: 8px; margin-bottom: 2em; }
input[type=text] { flex: 1; padding: 10px; font-size: 16px; }
button { padding: 10px 20px; font-size: 16px; cursor: pointer; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
.pill { padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.pill-corr { background: #c8e6c9; }
.pill-extr { background: #fff3c4; }
.pill-sin  { background: #eee; }
a { color: #1565c0; text-decoration: none; }
a:hover { text-decoration: underline; }
</style>
</head>
<body>
<h1>Revisión de medidas</h1>

<form method="post" action="/procesar">
  <input type="text" name="numero" placeholder="Número de orden (ej. J0042)" autofocus>
  <select name="modo" style="padding:10px;font-size:14px;">
    <option value="anotar" selected>Anotar a mano (precisión 100%)</option>
    <option value="auto">Extraer con Claude (rápido, necesita revisión)</option>
  </select>
  <button type="submit">Descargar</button>
</form>

<h2>Órdenes procesadas</h2>
{% if ordenes %}
<table>
  <tr><th>Número</th><th>Estado</th><th>DXF</th><th></th></tr>
  {% for o in ordenes %}
  <tr>
    <td><strong>{{ o.numero }}</strong></td>
    <td>
      {% if o.estado == 'corregida' %}<span class="pill pill-corr">corregida</span>
      {% elif o.estado == 'extraída' %}<span class="pill pill-extr">extraída</span>
      {% else %}<span class="pill pill-sin">{{ o.estado }}</span>
      {% endif %}
    </td>
    <td>{% if o.dxf %}<a href="/descargar/{{ o.numero }}/produccion.dxf">descargar</a>{% else %}-{% endif %}</td>
    <td><a href="/revisar/{{ o.numero }}">revisar →</a></td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p><em>No hay órdenes procesadas aún.</em></p>
{% endif %}
</body>
</html>"""


TPL_REVISAR = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{{ numero }} — revisión</title>
<style>
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, sans-serif; font-size: 14px; }
header { background: #263238; color: white; padding: 10px 20px; display: flex; align-items: center; gap: 20px; }
header a { color: #90caf9; text-decoration: none; }
header h1 { margin: 0; font-size: 18px; font-weight: normal; }
header .spacer { flex: 1; }
header button { padding: 8px 14px; font-size: 14px; cursor: pointer; border: 0; border-radius: 3px; }
.btn-save { background: #1976d2; color: white; }
.btn-dxf  { background: #2e7d32; color: white; }
.btn-pdf  { background: #ef6c00; color: white; }
.btn-reset { background: #6a1b9a; color: white; }
.btn-annot { background: #c62828; color: white; }
.btn-annot.on { background: #2e7d32; }
.btn-sint  { background: #6a1b9a; color: white; }
.stale-banner { background: #fff3cd; color: #856404; border: 1px solid #ffeeba;
  padding: 8px 12px; margin-bottom: 8px; border-radius: 4px; font-size: 13px; }
.razonamiento-global { background: #e3f2fd; border: 1px solid #90caf9; color: #0d47a1;
  padding: 10px 12px; margin-bottom: 10px; border-radius: 4px; font-size: 13px;
  white-space: pre-wrap; }
.razonamiento-pieza { background: #f3e5f5; border-left: 3px solid #8e24aa;
  padding: 6px 10px; margin: 6px 0; font-size: 12px; color: #4a148c;
  white-space: pre-wrap; }
.anot-ids { font-size: 11px; color: #666; margin-left: 6px; }
main { display: grid; grid-template-columns: 1fr 1fr; height: calc(100vh - 52px); }
.panel-img { border-right: 1px solid #ddd; background: #eee; display: flex; flex-direction: column; overflow: hidden; }
.thumb-bar { display: flex; gap: 4px; padding: 4px; background: #263238; overflow-x: auto; flex: 0 0 auto; }
.thumb { position: relative; cursor: pointer; flex: 0 0 auto; border: 3px solid transparent; background: black; }
.thumb.active { border-color: #42a5f5; }
.thumb.nota  { border-color: #66bb6a; }
.thumb img { display: block; height: 72px; width: auto; }
.thumb-badge { position: absolute; top: 2px; right: 4px; font-size: 14px; filter: drop-shadow(0 0 2px rgba(0,0,0,0.8)); }
.thumb-size { position: absolute; bottom: 2px; left: 3px; background: rgba(0,0,0,0.7); color: white; padding: 1px 4px; font-size: 9px; border-radius: 2px; }
.thumb .mark-btn { position: absolute; bottom: 2px; right: 2px; background: rgba(0,0,0,0.75); color: white; border: 0; padding: 2px 5px; font-size: 10px; border-radius: 2px; cursor: pointer; }
.thumb .mark-btn:hover { background: rgba(102,187,106,0.9); }
.img-main { flex: 1; overflow: auto; background: #eee; padding: 10px; display: flex; align-items: flex-start; justify-content: center; }
.img-main img { max-width: 100%; display: block; }
.img-wrap { position: relative; display: inline-block; max-width: 100%; }
.annot-overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }
.annot-overlay.active { pointer-events: auto; cursor: crosshair; }
.img-wrap img.crosshair { cursor: crosshair; }
.annot-rect { position: absolute; border: 2px dashed #e53935; background: rgba(229,57,53,0.12); pointer-events: none; }
.annot-badge { position: absolute; border: 2px solid #2e7d32; background: rgba(46,125,50,0.10); cursor: pointer; }
.annot-badge.hilited { border-color: #1565c0; border-width: 3px; background: rgba(21,101,192,0.18); }
.annot-badge .num { position: absolute; top: -11px; left: -11px; background: #2e7d32; color: white;
  width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-weight: bold; font-size: 12px; border: 2px solid white; }
.annot-badge .del { position: absolute; top: -10px; right: -10px; background: #c62828; color: white; border: 0;
  width: 18px; height: 18px; border-radius: 50%; cursor: pointer; font-size: 11px; line-height: 1; padding: 0; }

.modal-bg { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 100; }
.modal-bg.open { display: flex; align-items: center; justify-content: center; }
.modal { background: white; padding: 20px; border-radius: 6px; max-width: 92vw; max-height: 92vh;
  width: 720px; display: flex; flex-direction: column; gap: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.3); }
.modal h3 { margin: 0; font-size: 16px; color: #263238; }
.modal img { max-width: 100%; max-height: 280px; object-fit: contain; border: 1px solid #ddd;
  background: #f5f5f5; align-self: center; }
.modal textarea { width: 100%; min-height: 110px; padding: 10px; font-size: 14px; font-family: inherit;
  resize: vertical; box-sizing: border-box; border: 1px solid #bbb; border-radius: 4px; }
.modal .hint { font-size: 11px; color: #666; line-height: 1.4; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
.modal-actions button { padding: 8px 16px; font-size: 14px; border-radius: 3px; cursor: pointer; }
.modal .btn-submit { background: #2e7d32; color: white; border: 0; }
.modal .btn-cancel { background: #eee; border: 1px solid #ccc; color: #333; }

.pieza.hilited { outline: 3px solid #1565c0; outline-offset: 2px; }
.panel-form { overflow-y: auto; padding: 12px; background: #fafafa; }
.meta { display: grid; grid-template-columns: auto 1fr; gap: 6px 10px; background: white; padding: 10px; border-radius: 4px; margin-bottom: 10px; }
.meta label { font-weight: 600; }
.meta input { padding: 4px 6px; }
.pieza { background: white; border: 1px solid #ddd; border-radius: 4px; padding: 10px; margin-bottom: 10px; }
.pieza.incompleta { border-color: #d32f2f; border-width: 2px; background: #fff5f5; }
.faltan-badge { background: #d32f2f; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: bold; }
.faltan-list { color: #d32f2f; font-size: 11px; margin: 4px 0; padding-left: 0; list-style: none; }
.faltan-list li { padding: 1px 0; }
.faltan-list li::before { content: "⚠ "; }
.pieza-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.pieza-head h3 { margin: 0; font-size: 15px; }
.pieza-head .remove { margin-left: auto; background: #c62828; color: white; border: 0; padding: 4px 8px; border-radius: 3px; cursor: pointer; }
.pieza-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px 10px; }
.pieza-grid label { font-size: 11px; color: #555; }
.pieza-grid input, .pieza-grid select { width: 100%; padding: 3px 5px; font-size: 13px; }
.pieza-grid .wide { grid-column: span 4; }
.acabados { margin-top: 8px; border-top: 1px dashed #ccc; padding-top: 6px; }
.acabados h4 { margin: 0 0 4px; font-size: 12px; color: #444; }
.acabado-row { display: grid; grid-template-columns: 80px 110px 70px 70px; gap: 4px 8px; margin-bottom: 3px; align-items: center; }
.acabado-row label { font-size: 11px; font-weight: 600; color: #555; text-align: right; }
.acabado-row select, .acabado-row input { padding: 2px 4px; font-size: 11px; }
.acabado-row .disabled { opacity: 0.3; pointer-events: none; background: #f5f5f5; }
.huecos { margin-top: 8px; border-top: 1px dashed #ccc; padding-top: 6px; }
.huecos h4 { margin: 0 0 4px; font-size: 12px; color: #444; }
.hueco { display: grid; grid-template-columns: repeat(5, 1fr) auto; gap: 6px; margin-bottom: 4px; align-items: end; }
.hueco .remove { background: #c62828; color: white; border: 0; padding: 4px 6px; border-radius: 3px; cursor: pointer; font-size: 11px; }
.hueco select, .hueco input { font-size: 12px; padding: 2px 4px; }
.add-btn { background: #455a64; color: white; border: 0; padding: 6px 10px; border-radius: 3px; cursor: pointer; font-size: 12px; margin-right: 6px; }
.status { margin-left: 10px; font-size: 13px; }
.status.ok { color: #2e7d32; }
.status.err { color: #c62828; }
details.notas { background: white; padding: 6px 10px; border-radius: 4px; margin-top: 6px; }
details.notas summary { cursor: pointer; color: #555; }
.advertencia { background: #fff3cd; border: 1px solid #ffeeba; padding: 6px 10px; border-radius: 4px; margin-bottom: 6px; }
</style>
</head>
<body>
<header>
  <a href="/">← volver</a>
  <h1>{{ numero }}</h1>
  <span id="status" class="status"></span>
  <div class="spacer"></div>
  <button class="btn-annot" id="btn-annot" onclick="toggleAnnotMode()">📍 Anotar</button>
  <button class="btn-sint"  id="btn-sint"  onclick="sintetizar()">🧠 Sintetizar piezas</button>
  <button class="btn-reset" onclick="reiniciar()">Descartar</button>
  <button class="btn-save" onclick="guardar()">💾</button>
  <button class="btn-dxf" onclick="generarDxf()">▶ DXF</button>
  <button class="btn-pdf" onclick="generarPdf()">📄 PDF</button>
</header>

<main>
  <div class="panel-img">
    {% if imagenes %}
    <div class="thumb-bar" id="thumbs"></div>
    {% endif %}
    <div class="img-main">
      {% if imagen_actual %}
      <div class="img-wrap" id="img-wrap">
        <img id="nota" src="/imagen/{{ numero }}/{{ imagen_actual }}">
        <div class="annot-overlay" id="annot-overlay"></div>
      </div>
      {% else %}
      <p style="padding:2em;"><em>No hay imagen descargada</em></p>
      {% endif %}
    </div>
  </div>

  <div class="panel-form" id="form-panel">
    <!-- El formulario se rellena con JS desde los datos -->
  </div>
</main>

<div class="modal-bg" id="modal-bg">
  <div class="modal">
    <h3>📝 Anotación de contexto</h3>
    <img id="modal-preview" alt="recorte">
    <textarea id="modal-desc" placeholder="Describe lo que ves en este recorte. Puede ser una pieza completa, una medida concreta, un símbolo que aclaras (ej. 'Esta X significa pulido'), una corrección, o cualquier contexto que creas necesario."></textarea>
    <div class="hint">
      <b>Esto NO genera una pieza directamente.</b> Solo guarda tu explicación como
      contexto. Cuando hayas marcado todo lo relevante de la nota, pulsa
      <b>🧠 Sintetizar piezas</b> en la cabecera y Claude deducirá la lista final
      analizando TODAS tus anotaciones juntas, con razonamiento por cada pieza.
    </div>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="cerrarModal()">Cancelar</button>
      <button class="btn-submit" onclick="enviarAnotacion()">Guardar anotación</button>
    </div>
  </div>
</div>

<script>
const NUMERO = "{{ numero }}";
const IMAGENES = {{ imagenes|tojson }};
const IMAGEN_NOTA = "{{ imagen_actual }}";
const TIPOS_PIEZA = ["encimera","chapeado","copete","rodapie","isla","costado","pilastra","paso","tabica","zocalo","otro"];
const FORMAS = ["rectangular","L","U","irregular"];
const TIPOS_HUECO = ["placa","fregadero","grifo","enchufe"];
const SUBTIPOS_HUECO = ["","sobre_encimera","bajo_encimera"];
const ARISTAS = ["frente","cabeza_der","fondo","cabeza_izq"];
const ARISTA_LABELS = {frente:"frente", cabeza_der:"cabeza der", fondo:"fondo", cabeza_izq:"cabeza izq"};
const TIPOS_ACABADO = ["","inglete","pulido","bisel"];
const ANGULO_INGLETE_DEFAULT = 45.5;

let datos = {{ datos_json|safe }};

function $(sel, el=document) { return el.querySelector(sel); }
function el(tag, props={}, ...children) {
  const e = document.createElement(tag);
  Object.entries(props).forEach(([k,v]) => {
    if (k === "class") e.className = v;
    else if (k === "style") e.setAttribute("style", v);
    else if (k.startsWith("on")) e[k.toLowerCase()] = v;
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (v !== null && v !== undefined) e[k] = v;
  });
  children.flat().forEach(c => {
    if (typeof c === "string") e.appendChild(document.createTextNode(c));
    else if (c) e.appendChild(c);
  });
  return e;
}

function selectBox(options, value) {
  const s = el("select");
  options.forEach(opt => {
    const o = el("option", {value: opt});
    o.textContent = opt || "—";
    if (opt === value) o.selected = true;
    s.appendChild(o);
  });
  return s;
}

function renderAcabadoRow(p, iPieza, arista) {
  p.acabados_aristas = p.acabados_aristas || {};
  const ac = p.acabados_aristas[arista] = p.acabados_aristas[arista] || {tipo: null, angulo: null, profundidad_mm: null};
  const tipo = ac.tipo || "";

  const row = el("div", {class: "acabado-row", dataset: {tipo: tipo}});
  row.appendChild(el("label", {}, ARISTA_LABELS[arista]));

  // Dropdown tipo
  const sel = el("select");
  TIPOS_ACABADO.forEach(t => {
    const o = el("option", {value: t});
    o.textContent = t || "ninguno";
    if (t === tipo) o.selected = true;
    sel.appendChild(o);
  });
  sel.dataset.pieza = iPieza;
  sel.dataset.edge = arista;
  sel.dataset.field = "tipo";
  sel.dataset.target = "acabado";
  row.appendChild(sel);

  // Input ángulo
  const angDisabled = !(tipo === "inglete" || tipo === "bisel");
  const angDefault = (tipo === "inglete" && ac.angulo == null) ? ANGULO_INGLETE_DEFAULT : (ac.angulo ?? "");
  const angInput = el("input", {type: "number", step: 0.1, value: angDefault, placeholder: "ángulo°",
                                class: angDisabled ? "disabled" : ""});
  angInput.dataset.pieza = iPieza;
  angInput.dataset.edge = arista;
  angInput.dataset.field = "angulo";
  angInput.dataset.target = "acabado";
  row.appendChild(angInput);

  // Input profundidad
  const profDisabled = tipo !== "bisel";
  const profInput = el("input", {type: "number", step: 0.5, value: ac.profundidad_mm ?? "", placeholder: "prof mm",
                                 class: profDisabled ? "disabled" : ""});
  profInput.dataset.pieza = iPieza;
  profInput.dataset.edge = arista;
  profInput.dataset.field = "profundidad_mm";
  profInput.dataset.target = "acabado";
  row.appendChild(profInput);

  return row;
}

function renderAcabados(p, i) {
  const cont = el("div", {class: "acabados"}, el("h4", {}, "Acabados de aristas"));
  ARISTAS.forEach(a => cont.appendChild(renderAcabadoRow(p, i, a)));
  return cont;
}

function renderHueco(h, iPieza, iHueco) {
  const row = el("div", {class: "hueco"});
  const fields = [
    ["tipo", selectBox(TIPOS_HUECO, h.tipo || "placa")],
    ["subtipo", selectBox(SUBTIPOS_HUECO, h.subtipo || "")],
    ["largo_mm", el("input", {type:"number", value: h.largo_mm ?? "", step: 1})],
    ["ancho_mm", el("input", {type:"number", value: h.ancho_mm ?? "", step: 1})],
    ["distancia_frente_mm", el("input", {type:"number", value: h.distancia_frente_mm ?? "", step: 1, placeholder:"dist frente"})],
  ];
  fields.forEach(([key, input]) => {
    input.dataset.pieza = iPieza;
    input.dataset.hueco = iHueco;
    input.dataset.field = key;
    input.dataset.target = "hueco";
    const wrap = el("div", {}, el("label", {style:"font-size:10px;color:#666"}, key), input);
    row.appendChild(wrap);
  });
  const btn = el("button", {class:"remove", onclick: () => {
    datos.piezas[iPieza].huecos.splice(iHueco, 1); render();
  }}, "✕");
  row.appendChild(btn);
  return row;
}

function piezaFaltantes(p) {
  // Misma lógica que validar_pieza() en dxf_produccion.py
  const faltan = [];
  const tipo = (p.tipo || "").toLowerCase();
  const largo = p.largo_mm;
  const ancho = p.ancho_mm;
  const alto  = p.alto_mm;
  if (!largo) faltan.push("largo_mm");
  if (["encimera","isla","cascada"].includes(tipo)) {
    if (!ancho) faltan.push("ancho_mm (fondo)");
  } else if (["chapeado","frontal","pilastra","costado","copete","rodapie","zocalo","paso","tabica"].includes(tipo)) {
    if (!alto && !ancho) faltan.push("alto_mm (altura)");
  } else {
    if (!ancho && !alto) faltan.push("ancho_mm / alto_mm");
  }
  (p.huecos || []).forEach((h, j) => {
    const t = (h.tipo || "").toLowerCase();
    if (t === "placa" || t === "fregadero") {
      if (!h.largo_mm) faltan.push(`hueco[${j+1}] ${t}: largo_mm`);
      if (!h.ancho_mm) faltan.push(`hueco[${j+1}] ${t}: ancho_mm`);
      if (h.distancia_frente_mm == null) faltan.push(`hueco[${j+1}] ${t}: distancia_frente_mm`);
      if (!h.posicion) faltan.push(`hueco[${j+1}] ${t}: posicion`);
      else if (["izquierda","derecha"].includes(h.posicion.toLowerCase()) && h.distancia_lado_mm == null)
        faltan.push(`hueco[${j+1}] ${t}: distancia_lado_mm`);
    } else if (t === "enchufe" || t === "grifo") {
      if (h.distancia_frente_mm == null) faltan.push(`hueco[${j+1}] ${t}: distancia_frente_mm`);
      if (!h.posicion) faltan.push(`hueco[${j+1}] ${t}: posicion`);
      else if (["izquierda","derecha"].includes(h.posicion.toLowerCase()) && h.distancia_lado_mm == null)
        faltan.push(`hueco[${j+1}] ${t}: distancia_lado_mm`);
    }
  });
  return faltan;
}

function renderPieza(p, i) {
  const faltan = piezaFaltantes(p);
  const piezaEl = el("div", {class: "pieza" + (faltan.length ? " incompleta" : "")});
  const head = el("div", {class:"pieza-head"},
    el("h3", {}, `#${i+1}`),
    selectBox(TIPOS_PIEZA, p.tipo || "encimera"),
    selectBox(FORMAS, p.forma || "rectangular"),
    ...(faltan.length ? [el("span", {class: "faltan-badge"}, `⚠ FALTAN ${faltan.length}`)] : []),
    el("button", {class:"remove", onclick: () => { datos.piezas.splice(i,1); render(); }}, "eliminar"),
  );
  // Tipo y forma (primeros dos selects del head)
  const [tipoSel, formaSel] = head.querySelectorAll("select");
  tipoSel.dataset.pieza = i; tipoSel.dataset.field = "tipo"; tipoSel.dataset.target = "pieza";
  formaSel.dataset.pieza = i; formaSel.dataset.field = "forma"; formaSel.dataset.target = "pieza";
  piezaEl.appendChild(head);

  if (faltan.length) {
    const ul = el("ul", {class: "faltan-list"});
    faltan.forEach(f => ul.appendChild(el("li", {}, f)));
    piezaEl.appendChild(ul);
  }

  // Razonamiento de la síntesis + anotaciones que sustentan esta pieza
  if (p.razonamiento) {
    const r = el("div", {class: "razonamiento-pieza"}, "🧠 " + p.razonamiento);
    if (p.anotaciones_ids && p.anotaciones_ids.length) {
      r.appendChild(el("span", {class: "anot-ids"},
        "  · basada en: " + p.anotaciones_ids.map(id => "A" + id).join(", ")));
    }
    piezaEl.appendChild(r);
  }

  const grid = el("div", {class:"pieza-grid"});
  const campos = [
    ["largo_mm", "largo", "number"],
    ["ancho_mm", "ancho/fondo", "number"],
    ["alto_mm", "alto", "number"],
    ["zona", "zona", "text"],
    ["descuadro_izq_mm", "desc izq", "number"],
    ["descuadro_der_mm", "desc der", "number"],
    ["descuadro_sup_mm", "desc sup", "number"],
    ["descuadro_inf_mm", "desc inf", "number"],
  ];
  campos.forEach(([key, label, tipo]) => {
    const inp = el("input", {type: tipo, value: p[key] ?? "", step: tipo === "number" ? 1 : null});
    inp.dataset.pieza = i; inp.dataset.field = key; inp.dataset.target = "pieza";
    grid.appendChild(el("div", {}, el("label", {}, label), inp));
  });

  // tiene_guion como checkbox
  const chk = el("input", {type: "checkbox", checked: !!p.tiene_guion});
  chk.dataset.pieza = i; chk.dataset.field = "tiene_guion"; chk.dataset.target = "pieza";
  grid.appendChild(el("div", {}, el("label", {}, "guion (-)"),
    el("div", {style: "display:flex;align-items:center;gap:6px"}, chk, el("span", {style:"font-size:11px;color:#666"}, "descuenta grosor+2mm"))));

  // notas
  const notas = el("textarea", {rows: 2, style:"width:100%;font-size:12px"}, p.notas || "");
  notas.dataset.pieza = i; notas.dataset.field = "notas"; notas.dataset.target = "pieza";
  grid.appendChild(el("div", {class:"wide"}, el("label", {}, "notas"), notas));

  piezaEl.appendChild(grid);

  // Acabados de aristas (inglete, pulido, bisel)
  piezaEl.appendChild(renderAcabados(p, i));

  // Huecos
  const huecos = el("div", {class:"huecos"},
    el("h4", {}, `Huecos (${(p.huecos||[]).length})`)
  );
  (p.huecos || []).forEach((h, j) => huecos.appendChild(renderHueco(h, i, j)));
  huecos.appendChild(el("button", {class:"add-btn", onclick: () => {
    p.huecos = p.huecos || [];
    p.huecos.push({tipo:"placa", largo_mm: 560, ancho_mm: 490});
    render();
  }}, "+ hueco"));
  piezaEl.appendChild(huecos);

  return piezaEl;
}

function render() {
  const panel = $("#form-panel");
  panel.innerHTML = "";

  // Metadatos de la orden
  const meta = el("div", {class:"meta"});
  [
    ["cliente", "Cliente"],
    ["numero", "Número"],
    ["material", "Material"],
    ["notas_generales", "Notas"],
  ].forEach(([key, label]) => {
    const inp = el("input", {type:"text", value: datos[key] || ""});
    inp.dataset.field = key; inp.dataset.target = "meta";
    meta.appendChild(el("label", {}, label));
    meta.appendChild(inp);
  });
  panel.appendChild(meta);

  // Advertencias del extractor
  (datos.advertencias || []).forEach(a => {
    panel.appendChild(el("div", {class:"advertencia"}, "⚠ " + a));
  });

  // Aviso de piezas desactualizadas
  if (datos.piezas_stale && datos.piezas && datos.piezas.length) {
    panel.appendChild(el("div", {class: "stale-banner"},
      "⚠ Las piezas mostradas están basadas en una síntesis anterior. " +
      "Desde entonces has añadido o eliminado anotaciones. Pulsa 🧠 Sintetizar para actualizar."));
  }

  // Razonamiento global de la última síntesis
  if (datos.razonamiento_global) {
    panel.appendChild(el("div", {class: "razonamiento-global"},
      "🧠 " + datos.razonamiento_global));
  }

  // Info resumen
  const nPiezas = (datos.piezas || []).length;
  const nAnots  = (datos.anotaciones || []).length;
  const summary = el("div", {style: "font-size:12px;color:#555;margin-bottom:8px"},
    `📍 ${nAnots} anotación(es) · 🧩 ${nPiezas} pieza(s) sintetizada(s)` +
    (datos.ultima_sintesis ? ` · última síntesis: ${datos.ultima_sintesis}` : ""));
  panel.appendChild(summary);

  // Piezas
  (datos.piezas || []).forEach((p, i) => panel.appendChild(renderPieza(p, i)));

  // Botón añadir pieza
  panel.appendChild(el("button", {class:"add-btn", style:"font-size:14px;padding:8px 14px",
    onclick: () => { datos.piezas.push({tipo:"encimera", forma:"rectangular", huecos:[]}); render(); }
  }, "+ Añadir pieza"));

  // Listener genérico de cambio
  panel.addEventListener("input", onChange);
  panel.addEventListener("change", onChange);
}

function onChange(ev) {
  const t = ev.target;
  if (!t.dataset.target) return;
  let val = t.value;
  if (t.type === "checkbox") val = t.checked;
  else if (t.type === "number") val = val === "" ? null : Number(val);

  if (t.dataset.target === "meta") {
    datos[t.dataset.field] = val;
  } else if (t.dataset.target === "pieza") {
    datos.piezas[Number(t.dataset.pieza)][t.dataset.field] = val;
  } else if (t.dataset.target === "hueco") {
    const p = datos.piezas[Number(t.dataset.pieza)];
    p.huecos[Number(t.dataset.hueco)][t.dataset.field] = val;
  } else if (t.dataset.target === "acabado") {
    const p = datos.piezas[Number(t.dataset.pieza)];
    p.acabados_aristas = p.acabados_aristas || {};
    const edge = t.dataset.edge;
    p.acabados_aristas[edge] = p.acabados_aristas[edge] || {};
    p.acabados_aristas[edge][t.dataset.field] = (val === "" ? null : val);

    // Si cambió el tipo y es inglete sin ángulo, auto-rellenar con 45.5
    if (t.dataset.field === "tipo") {
      if (val === "inglete" && p.acabados_aristas[edge].angulo == null) {
        p.acabados_aristas[edge].angulo = ANGULO_INGLETE_DEFAULT;
      }
      // Re-renderizar solo la fila afectada para habilitar/deshabilitar inputs
      const oldRow = t.closest(".acabado-row");
      const newRow = renderAcabadoRow(p, Number(t.dataset.pieza), edge);
      oldRow.replaceWith(newRow);
    }
  }
}

async function guardar() {
  setStatus("Guardando...");
  const res = await fetch(`/guardar/${NUMERO}`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(datos),
  });
  const j = await res.json();
  setStatus(j.ok ? "✓ Guardado" : "✗ " + j.error, j.ok);
}

function contarIncompletas() {
  return (datos.piezas || []).filter(p => piezaFaltantes(p).length > 0).length;
}

function confirmarIncompletas(verbo) {
  const n = contarIncompletas();
  if (n === 0) return true;
  return confirm(
    `⚠ Hay ${n} pieza(s) con dimensiones incompletas. ` +
    `Se OMITIRÁN del ${verbo}. ` +
    `¿Continuar de todos modos? (Recomendado: rellenar primero y volver a intentar.)`
  );
}

async function generarDxf() {
  if (!confirmarIncompletas("DXF")) return;
  setStatus("Generando DXF...");
  const res = await fetch(`/dxf/${NUMERO}`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(datos),
  });
  const j = await res.json();
  if (j.ok) {
    setStatus(`✓ DXF generado · `, true);
    const dlLink = el("a", {href: `/descargar/${NUMERO}/${j.dxf}`, style:"margin-right:10px"}, "descargar");
    const path = el("code", {style:"font-size:11px;color:#999"}, `revisiones/${NUMERO}/${j.dxf}`);
    $("#status").appendChild(dlLink);
    $("#status").appendChild(path);
  } else {
    setStatus("✗ " + j.error, false);
    console.error(j.trace);
  }
}

async function reiniciar() {
  if (!confirm("¿Descartar todas las correcciones y volver al JSON original?")) return;
  await fetch(`/reiniciar/${NUMERO}`, {method:"POST"});
  location.reload();
}

function renderThumbs() {
  const bar = $("#thumbs");
  if (!bar || !IMAGENES.length) return;
  bar.innerHTML = "";
  IMAGENES.forEach((img, idx) => {
    const isNota = (img === IMAGEN_NOTA);
    const thumb = el("div", {
      class: "thumb" + (isNota ? " nota active" : ""),
      title: img,
    });
    thumb.appendChild(el("img", {src: `/imagen/${NUMERO}/${img}`}));
    if (isNota) thumb.appendChild(el("span", {class: "thumb-badge"}, "📝"));
    thumb.appendChild(el("span", {class: "thumb-size"}, `#${idx+1}`));

    const btn = el("button", {class: "mark-btn", onclick: (ev) => {
      ev.stopPropagation();
      reextraerCon(img);
    }}, isNota ? "re-extraer" : "usar esta");
    thumb.appendChild(btn);

    thumb.addEventListener("click", () => {
      const notaImg = $("#nota");
      notaImg.src = `/imagen/${NUMERO}/${img}`;
      // Esperar a que cargue para reposicionar badges
      notaImg.onload = () => renderBadges();
      document.querySelectorAll(".thumb").forEach(t => t.classList.remove("active"));
      thumb.classList.add("active");
    });
    bar.appendChild(thumb);
  });
}

// ─────────────────────────────────────────────────────────────
//  MODO ANOTACIÓN
// ─────────────────────────────────────────────────────────────

let annotMode = false;
let drawingRect = null;
let currentAnnot = null;   // {bbox, rectEl}

function getCurrentImageName() {
  const src = $("#nota").src;
  return decodeURIComponent(src.substring(src.lastIndexOf("/") + 1));
}

function toggleAnnotMode() {
  annotMode = !annotMode;
  const overlay = $("#annot-overlay");
  if (!overlay) return;
  overlay.classList.toggle("active", annotMode);
  $("#nota").classList.toggle("crosshair", annotMode);
  const btn = $("#btn-annot");
  btn.classList.toggle("on", annotMode);
  btn.textContent = annotMode ? "✓ Dibuja rectángulos" : "📍 Anotar";
}

function _eventToNorm(ev) {
  const img = $("#nota");
  const rect = img.getBoundingClientRect();
  const x = (ev.clientX - rect.left) / rect.width;
  const y = (ev.clientY - rect.top) / rect.height;
  return {x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y))};
}

function _updateRectStyle(r) {
  const x = Math.min(r.x1, r.x2) * 100;
  const y = Math.min(r.y1, r.y2) * 100;
  const w = Math.abs(r.x2 - r.x1) * 100;
  const h = Math.abs(r.y2 - r.y1) * 100;
  r.el.style.left = x + "%";
  r.el.style.top = y + "%";
  r.el.style.width = w + "%";
  r.el.style.height = h + "%";
}

function setupDrawing() {
  const overlay = $("#annot-overlay");
  if (!overlay) return;

  overlay.addEventListener("mousedown", (ev) => {
    if (!annotMode) return;
    ev.preventDefault();
    const p = _eventToNorm(ev);
    const rectEl = el("div", {class: "annot-rect"});
    overlay.appendChild(rectEl);
    drawingRect = {x1: p.x, y1: p.y, x2: p.x, y2: p.y, el: rectEl};
    _updateRectStyle(drawingRect);
  });
  overlay.addEventListener("mousemove", (ev) => {
    if (!drawingRect) return;
    const p = _eventToNorm(ev);
    drawingRect.x2 = p.x; drawingRect.y2 = p.y;
    _updateRectStyle(drawingRect);
  });
  overlay.addEventListener("mouseup", () => {
    if (!drawingRect) return;
    const r = drawingRect;
    drawingRect = null;
    const bbox = [
      Math.min(r.x1, r.x2), Math.min(r.y1, r.y2),
      Math.max(r.x1, r.x2), Math.max(r.y1, r.y2),
    ];
    if (bbox[2] - bbox[0] < 0.015 || bbox[3] - bbox[1] < 0.015) {
      r.el.remove();
      return;
    }
    abrirModal(bbox, r.el);
  });
  // Si se suelta fuera del overlay
  window.addEventListener("mouseup", () => {
    if (drawingRect) {
      // Si el rectángulo es minúsculo, descartar
      const r = drawingRect;
      drawingRect = null;
      if (Math.abs(r.x2 - r.x1) < 0.015 || Math.abs(r.y2 - r.y1) < 0.015) {
        r.el.remove();
      }
    }
  });
}

function abrirModal(bbox, rectEl) {
  currentAnnot = {bbox, rectEl};
  $("#modal-desc").value = "";

  // Crop preview con canvas
  const img = $("#nota");
  const cW = Math.max(1, Math.round(img.naturalWidth  * (bbox[2] - bbox[0])));
  const cH = Math.max(1, Math.round(img.naturalHeight * (bbox[3] - bbox[1])));
  const canvas = document.createElement("canvas");
  canvas.width = cW; canvas.height = cH;
  canvas.getContext("2d").drawImage(img,
    bbox[0] * img.naturalWidth, bbox[1] * img.naturalHeight, cW, cH,
    0, 0, cW, cH);
  $("#modal-preview").src = canvas.toDataURL("image/jpeg", 0.9);

  $("#modal-bg").classList.add("open");
  setTimeout(() => $("#modal-desc").focus(), 50);
}

function cerrarModal() {
  if (currentAnnot && currentAnnot.rectEl) currentAnnot.rectEl.remove();
  currentAnnot = null;
  $("#modal-bg").classList.remove("open");
}

async function enviarAnotacion() {
  if (!currentAnnot) return;
  const desc = $("#modal-desc").value.trim();
  if (!desc) {
    alert("Describe la anotación antes de guardar");
    return;
  }
  const imagen = getCurrentImageName();
  const btn = document.querySelector(".modal .btn-submit");
  btn.disabled = true; btn.textContent = "Guardando...";
  setStatus("Guardando anotación...");

  try {
    const res = await fetch(`/anotar/${NUMERO}`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({imagen, bbox_norm: currentAnnot.bbox, descripcion: desc}),
    });
    const j = await res.json();
    if (j.ok) {
      datos.anotaciones = datos.anotaciones || [];
      datos.anotaciones.push(j.anotacion);
      if (datos.piezas && datos.piezas.length) datos.piezas_stale = true;
      if (currentAnnot.rectEl) currentAnnot.rectEl.remove();
      currentAnnot = null;
      $("#modal-bg").classList.remove("open");
      setStatus(`✓ Anotación #${j.anotacion.id} guardada · total: ${j.total_anotaciones}`, true);
      render();
      renderBadges();
    } else {
      setStatus("✗ " + j.error, false);
      alert("Error: " + j.error);
    }
  } finally {
    btn.disabled = false; btn.textContent = "Guardar anotación";
  }
}

async function sintetizar() {
  if (!datos.anotaciones || !datos.anotaciones.length) {
    alert("No hay anotaciones para sintetizar. Marca primero el contexto sobre la imagen.");
    return;
  }
  const aviso = datos.piezas && datos.piezas.length
    ? `Esto reemplazará las ${datos.piezas.length} pieza(s) actuales con una nueva síntesis a partir de las ${datos.anotaciones.length} anotaciones. ¿Continuar?`
    : `Sintetizar ${datos.anotaciones.length} anotación(es) en piezas finales. Puede tardar 15-40s. ¿Continuar?`;
  if (!confirm(aviso)) return;

  const btn = $("#btn-sint");
  btn.disabled = true; btn.textContent = "🧠 Sintetizando...";
  setStatus("Claude analizando anotaciones... (15-40s)");

  try {
    const res = await fetch(`/sintetizar/${NUMERO}`, {method: "POST"});
    const j = await res.json();
    if (j.ok) {
      datos.piezas              = j.piezas;
      datos.razonamiento_global = j.razonamiento_global;
      datos.anotaciones_contextuales_ids = j.anotaciones_contextuales_ids || [];
      datos.piezas_stale = false;
      setStatus(`✓ ${j.piezas.length} piezas sintetizadas · tokens ${j.tokens_in}→${j.tokens_out}`, true);
      render();
      renderBadges();
    } else {
      setStatus("✗ " + j.error, false);
      console.error(j.trace);
      alert("Error sintetizando: " + j.error);
    }
  } finally {
    btn.disabled = false; btn.textContent = "🧠 Sintetizar piezas";
  }
}

function renderBadges() {
  const overlay = $("#annot-overlay");
  if (!overlay) return;
  overlay.querySelectorAll(".annot-badge").forEach(n => n.remove());
  const currentImg = getCurrentImageName();
  const contextualIds = new Set(datos.anotaciones_contextuales_ids || []);
  (datos.anotaciones || []).forEach((a) => {
    if (a.imagen !== currentImg) return;
    const [x1, y1, x2, y2] = a.bbox_norm;
    const b = el("div", {class: "annot-badge", title: a.descripcion});
    b.style.left = (x1 * 100) + "%";
    b.style.top  = (y1 * 100) + "%";
    b.style.width  = ((x2 - x1) * 100) + "%";
    b.style.height = ((y2 - y1) * 100) + "%";
    // El badge muestra el id de anotación; si era contextual, color naranja
    if (contextualIds.has(a.id)) b.style.borderColor = "#ef6c00";
    b.appendChild(el("span", {class: "num"}, `A${a.id}`));
    const del = el("button", {class: "del", title: "eliminar anotación", onclick: (ev) => {
      ev.stopPropagation();
      borrarAnotacion(a.id);
    }}, "×");
    b.appendChild(del);
    b.onclick = () => {
      // Si hay pieza que cita esta anotación, hacer scroll a ella
      const pidx = (datos.piezas || []).findIndex(p =>
        (p.anotaciones_ids || []).includes(a.id));
      if (pidx >= 0) scrollToPieza(pidx);
    };
    overlay.appendChild(b);
  });
}

async function borrarAnotacion(ann_id) {
  if (!confirm("¿Eliminar esta anotación? Si había piezas sintetizadas quedarán desactualizadas.")) return;
  const res = await fetch(`/borrar_anotacion/${NUMERO}/${ann_id}`, {method: "POST"});
  const j = await res.json();
  if (!j.ok) { setStatus("✗ " + (j.error || "error"), false); return; }
  datos.anotaciones = (datos.anotaciones || []).filter(x => x.id !== ann_id);
  if (datos.piezas && datos.piezas.length) datos.piezas_stale = true;
  render();
  renderBadges();
  setStatus("✓ Anotación eliminada", true);
}

function scrollToPieza(pidx) {
  if (pidx == null) return;
  const piezas = $("#form-panel").querySelectorAll(".pieza");
  if (piezas[pidx]) {
    piezas[pidx].scrollIntoView({behavior: "smooth", block: "center"});
    piezas[pidx].classList.add("hilited");
    setTimeout(() => piezas[pidx].classList.remove("hilited"), 1800);
  }
}

async function reextraerCon(imagen) {
  const msg = (imagen === IMAGEN_NOTA)
    ? `Volver a extraer medidas con la imagen actual? Sobrescribe las correcciones.`
    : `Extraer medidas usando "${imagen}" como nota? Sobrescribe las correcciones actuales.`;
  if (!confirm(msg)) return;
  setStatus("Extrayendo con Claude... (10-20s)");
  const res = await fetch(`/reextraer/${NUMERO}`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({imagen: imagen}),
  });
  const j = await res.json();
  if (j.ok) {
    setStatus(`✓ ${j.piezas} piezas extraídas · tokens ${j.tokens_in}→${j.tokens_out}`, true);
    setTimeout(() => location.reload(), 1500);
  } else {
    setStatus("✗ " + j.error, false);
    console.error(j.trace);
  }
}

async function generarPdf() {
  if (!confirmarIncompletas("PDF")) return;
  setStatus("Generando PDF acotado... (5-30s)");
  const res = await fetch(`/pdf/${NUMERO}`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(datos),
  });
  const j = await res.json();
  if (j.ok) {
    // Abrir el PDF en una pestaña nueva automáticamente
    const url = `/ver/${NUMERO}/${j.pdf}`;
    window.open(url, "_blank");
    setStatus(`✓ PDF generado · `, true);
    const verLink = el("a", {href: url, target: "_blank", style:"margin-right:10px"}, "abrir");
    const dlLink  = el("a", {href: `/descargar/${NUMERO}/${j.pdf}`, style:"margin-right:10px"}, "descargar");
    const path    = el("code", {style:"font-size:11px;color:#999"}, `revisiones/${NUMERO}/${j.pdf}`);
    $("#status").appendChild(verLink);
    $("#status").appendChild(dlLink);
    $("#status").appendChild(path);
  } else {
    setStatus("✗ " + (j.error || "error"), false);
    console.error(j);
  }
}

function setStatus(msg, ok=null) {
  const s = $("#status");
  s.textContent = msg;
  s.className = "status " + (ok === true ? "ok" : ok === false ? "err" : "");
}

renderThumbs();
render();
setupDrawing();
// Posicionar badges cuando la imagen termine de cargar (layout correcto)
const _notaImg = $("#nota");
if (_notaImg) {
  if (_notaImg.complete) renderBadges();
  else _notaImg.addEventListener("load", renderBadges);
}
// Cerrar modal con Escape
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && $("#modal-bg").classList.contains("open")) cerrarModal();
});
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"UI en http://127.0.0.1:5000  (datos en {DATA_DIR})")
    # use_reloader=False: el subprocess del dimensioner toca __pycache__ y el
    # watcher interpretaba eso como "cambio" reiniciando Flask a mitad del request.
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)
