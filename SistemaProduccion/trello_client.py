"""
trello_client.py — Acceso a Trello para buscar tarjetas por número de medida
y descargar adjuntos (imágenes de medidas manuscritas + PDFs de presupuesto).
"""

import re
import json
import time
import unicodedata
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Optional


# ── Configuración ─────────────────────────────────────────────────────────────

TRELLO_HOST  = "api.trello.com"
BOARD_ID     = "62a382a99f14ff1369e0da58"   # Planificador de Trabajo

# Listas donde buscar diseños cobrados
LIST_IDS_COBRADO = [
    "6977380f8f1d26ad1a0991c1",   # COBRADO
    "64f1a0ddb03d8de414440a7c",   # COBRADO 2025
]


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _get(endpoint: str, api_key: str, token: str, params: dict = None) -> any:
    q = {"key": api_key, "token": token}
    if params:
        q.update(params)
    url = f"https://{TRELLO_HOST}/1{endpoint}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _download(url: str, api_key: str, token: str, dest: Path) -> int:
    """Descarga un adjunto de Trello. Devuelve tamaño en bytes."""
    full = f"{url}?key={api_key}&token={token}"
    req = urllib.request.Request(
        full,
        headers={"Authorization": f'OAuth oauth_consumer_key="{api_key}", oauth_token="{token}"'}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    dest.write_bytes(data)
    return len(data)


# ── Normalización / extracción de número de medida ────────────────────────────

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def extraer_numero(texto: str) -> Optional[str]:
    """
    Extrae el número de medida de un nombre de tarjeta o archivo.
    Ejemplos: V0275, T6312, J0335, F166, P182, T8750
    """
    stem = Path(texto).stem
    m = re.search(r"(?<![A-Za-z])([A-Za-z]{1,2})_?(\d{3,})(?=\b|_|$)", stem)
    if m:
        return (m.group(1) + m.group(2)).upper()
    return None


# ── Cliente principal ──────────────────────────────────────────────────────────

class TrelloClient:
    def __init__(self, api_key: str, token: str):
        self.api_key = api_key
        self.token   = token
        self._cache: list = []
        self._cache_ts: float = 0
        self._cache_ttl: float = 600  # 10 min

    # ── Caché de tarjetas ──────────────────────────────────────────────────────

    def _get_cards(self) -> list:
        """Todas las tarjetas de COBRADO + COBRADO 2025, con caché."""
        if self._cache and time.time() - self._cache_ts < self._cache_ttl:
            return self._cache
        cards = []
        for list_id in LIST_IDS_COBRADO:
            batch = _get(
                f"/lists/{list_id}/cards",
                self.api_key, self.token,
                {"fields": "id,name,idList", "limit": "1000"}
            )
            cards.extend(batch)
        self._cache    = cards
        self._cache_ts = time.time()
        return cards

    def invalidar_cache(self):
        self._cache_ts = 0

    # ── Búsqueda de tarjeta ────────────────────────────────────────────────────

    def buscar_tarjeta(self, numero: str) -> Optional[dict]:
        """
        Busca la tarjeta cuyo nombre contiene el número de medida indicado.
        Devuelve None si no se encuentra.
        """
        num = numero.upper().replace("_", "")
        for card in self._get_cards():
            cn = extraer_numero(card["name"])
            if cn and cn.upper() == num:
                return card
        return None

    # ── Adjuntos ───────────────────────────────────────────────────────────────

    def obtener_adjuntos(self, card_id: str) -> list:
        """Lista de adjuntos de la tarjeta."""
        return _get(
            f"/cards/{card_id}/attachments",
            self.api_key, self.token,
            {"fields": "id,name,url,mimeType,bytes,date"}
        )

    def descargar_adjuntos(self, card_id: str, carpeta: Path,
                           solo_imagenes: bool = False) -> list[Path]:
        """
        Descarga adjuntos de la tarjeta a `carpeta`.
        Si solo_imagenes=True, salta los PDFs.
        Devuelve lista de rutas descargadas.
        """
        carpeta.mkdir(parents=True, exist_ok=True)
        adjuntos = self.obtener_adjuntos(card_id)
        descargados = []

        for att in adjuntos:
            mime = att.get("mimeType", "")
            if solo_imagenes and "image" not in mime:
                continue
            nombre = att.get("name") or att.get("fileName") or f"{att['id']}.bin"
            dest = carpeta / nombre
            if dest.exists():
                descargados.append(dest)
                continue
            try:
                size = _download(att["url"], self.api_key, self.token, dest)
                print(f"  ↓ {nombre} ({size//1024}KB)")
                descargados.append(dest)
            except Exception as e:
                print(f"  ✗ Error descargando {nombre}: {e}")

        return descargados

    # ── Clasificación rápida de adjuntos ──────────────────────────────────────

    @staticmethod
    def clasificar_adjuntos(adjuntos: list) -> dict:
        """
        Clasifica los adjuntos sin llamar a ninguna API:
          - imagenes_medida: JPG/PNG que probablemente son notas manuscritas
          - pdfs_presupuesto: PDFs (presupuestos MGR, etc.)
          - otros: resto

        Heurística:
          • PDFs → presupuesto
          • Imágenes grandes (>500KB) → candidatas a nota de medida
          • Imágenes pequeñas → posiblemente foto de aparato o referencia
        """
        imagenes  = []
        pdfs      = []
        otros     = []

        for att in adjuntos:
            mime  = att.get("mimeType", "")
            size  = att.get("bytes", 0) or 0
            nombre = (att.get("name") or "").lower()

            if "pdf" in mime or nombre.endswith(".pdf"):
                pdfs.append(att)
            elif "image" in mime:
                imagenes.append((size, att))
            else:
                otros.append(att)

        # Ordenar imágenes por tamaño descendente:
        # las notas manuscritas suelen ser fotos grandes (cámara)
        imagenes.sort(key=lambda x: x[0], reverse=True)
        imagenes_att = [att for _, att in imagenes]

        return {
            "imagenes": imagenes_att,      # todas las imágenes, ordenadas por tamaño
            "pdfs": pdfs,
            "otros": otros,
        }


# ── Función de conveniencia ────────────────────────────────────────────────────

def cargar_config(config_path: Optional[Path] = None) -> "TrelloClient":
    """Carga credenciales del watcher_config.json y devuelve un TrelloClient."""
    if config_path is None:
        base = Path(__file__).parent.parent
        config_path = base / "DXF_Acotador_Automatico" / "Instalacion para Windows" / "watcher_config.json"

    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    trello = cfg.get("trello", {})
    return TrelloClient(
        api_key=trello["api_key"],
        token=trello["token"],
    )


# ── Test rápido ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    numero = sys.argv[1] if len(sys.argv) > 1 else "T7060"
    client = cargar_config()

    print(f"Buscando: {numero}")
    card = client.buscar_tarjeta(numero)
    if not card:
        print("No encontrada.")
    else:
        print(f"✓ {card['name']}")
        adjs = client.obtener_adjuntos(card["id"])
        info = client.clasificar_adjuntos(adjs)
        print(f"  Imágenes: {len(info['imagenes'])} | PDFs: {len(info['pdfs'])}")
        for att in info["imagenes"]:
            print(f"    IMG {att.get('name','?')} {att.get('bytes',0)//1024}KB")
        for att in info["pdfs"]:
            print(f"    PDF {att.get('name','?')} {att.get('bytes',0)//1024}KB")
