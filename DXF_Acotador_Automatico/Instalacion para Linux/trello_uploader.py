#!/usr/bin/env python3
"""
trello_uploader.py — Integración con Trello para DXF Watcher
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cuando el watcher genera un PDF, este módulo:
  1. Extrae el "número de medida" del nombre del DXF (ej: V0275, T6312, F166).
  2. Busca en el tablero de Trello la tarjeta que mejor coincide.
  3. Adjunta el PDF a esa tarjeta, sustituyendo un adjunto anterior si lo hubiera.

Dependencias: solo librería estándar de Python (urllib, http.client).
Sin instalar nada adicional.
"""

import os
import re
import json
import time
import uuid
import logging
import unicodedata
import http.client
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Optional, Tuple, List, Dict

log = logging.getLogger("dxf_watcher.trello")

TRELLO_HOST = "api.trello.com"


# ══════════════════════════════════════════════════════════════════════════════
#  HTTP helpers  (solo stdlib, sin requests)
# ══════════════════════════════════════════════════════════════════════════════

def _get(endpoint: str, api_key: str, token: str, params: dict = None) -> any:
    """GET a la API de Trello → JSON."""
    query = {"key": api_key, "token": token}
    if params:
        query.update(params)
    url = f"https://{TRELLO_HOST}/1{endpoint}?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _delete(endpoint: str, api_key: str, token: str) -> int:
    """DELETE a la API de Trello → status code."""
    url = f"https://{TRELLO_HOST}/1{endpoint}?key={api_key}&token={token}"
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def _post_file(endpoint: str, api_key: str, token: str,
               file_path: str, file_name: str) -> dict:
    """
    POST multipart/form-data con un fichero a la API de Trello.
    Implementado con http.client para evitar dependencias externas.
    """
    boundary = uuid.uuid4().hex

    with open(file_path, "rb") as fh:
        file_data = fh.read()

    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = header + file_data + footer

    path = f"/1{endpoint}?key={api_key}&token={token}"
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }

    conn = http.client.HTTPSConnection(TRELLO_HOST, timeout=60)
    try:
        conn.request("POST", path, body, headers)
        resp = conn.getresponse()
        raw = resp.read()
        if resp.status in (200, 201):
            return json.loads(raw.decode("utf-8"))
        raise RuntimeError(
            f"HTTP {resp.status}: {raw.decode('utf-8', errors='replace')[:300]}"
        )
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  Normalización y extracción de número de medida
# ══════════════════════════════════════════════════════════════════════════════

def _normalize(text: str) -> str:
    """Minúsculas, sin tildes, sin puntuación — solo letras, dígitos y espacios."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _extract_numero(text: str) -> Optional[str]:
    """
    Extrae el "Número de Medida" de un nombre de archivo o tarjeta.

    Busca el patrón:  1-2 letras  +  guión_bajo_opcional  +  3 o más dígitos
    Puede estar al inicio o en cualquier posición (p. ej.: "A Horta_T6312_...").

    Ejemplos:
        V0275_Manuel ...  →  V0275
        V_0098_Maika ...  →  V0098
        J0335_Isabel ...  →  J0335
        F166_Maica ...    →  F166
        T5952_Gosan ...   →  T5952
        A Horta_T6312_... →  T6312
        Casiña_T6312_...  →  T6312
    """
    stem = Path(text).stem  # quitar extensión si la tiene
    # No busca si la letra va precedida por otra letra (evita falsos positivos)
    m = re.search(r"(?<![A-Za-z])([A-Za-z]{1,2})_?(\d{3,})(?=\b|_|$)", stem)
    if m:
        return (m.group(1) + m.group(2)).upper()
    return None


def _jaccard(a: str, b: str) -> float:
    """Similitud de Jaccard sobre conjuntos de tokens (sin importar el orden)."""
    ta, tb = set(a.split()), set(b.split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ══════════════════════════════════════════════════════════════════════════════
#  Clase principal
# ══════════════════════════════════════════════════════════════════════════════

class TrelloUploader:
    """Gestiona la conexión con Trello y la subida de PDFs a tarjetas."""

    def __init__(self, api_key: str, token: str, board_name: str,
                 min_score: float = 0.3, cache_minutes: int = 30):
        self.api_key      = api_key
        self.token        = token
        self.board_name   = board_name
        self.min_score    = min_score
        self.cache_ttl    = cache_minutes * 60

        self._board_id:    Optional[str] = None
        self._cards_cache: List[Dict]    = []
        self._cache_time:  float         = 0.0

    # ── Conexión inicial ──────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Verifica credenciales y localiza el tablero. Devuelve True si OK."""
        try:
            boards = _get("/members/me/boards", self.api_key, self.token,
                          {"fields": "id,name"})
        except urllib.error.HTTPError as e:
            if e.code == 401:
                log.error("Trello: credenciales incorrectas (API key o token inválido).")
            else:
                log.error(f"Trello: error HTTP {e.code} al conectar.")
            return False
        except Exception as e:
            log.error(f"Trello: no se pudo conectar: {e}")
            return False

        for b in boards:
            if b["name"].strip().lower() == self.board_name.strip().lower():
                self._board_id = b["id"]
                log.info(f"Trello: tablero '{self.board_name}' encontrado.")
                return True

        names = [b["name"] for b in boards]
        log.error(f"Trello: tablero '{self.board_name}' no encontrado.")
        log.error(f"  Tableros disponibles: {', '.join(names)}")
        return False

    # ── Caché de tarjetas ─────────────────────────────────────────────────────

    def _get_cards(self) -> List[Dict]:
        """Devuelve todas las tarjetas del tablero, con caché por TTL."""
        if not self._board_id:
            return []
        now = time.time()
        if self._cards_cache and (now - self._cache_time) < self.cache_ttl:
            return self._cards_cache
        try:
            cards = _get(
                f"/boards/{self._board_id}/cards",
                self.api_key, self.token,
                {"fields": "id,name,idList", "limit": "1000"}
            )
            self._cards_cache = cards
            self._cache_time  = now
            log.debug(f"Trello: caché actualizada — {len(cards)} tarjetas.")
            return cards
        except Exception as e:
            log.warning(f"Trello: no se pudo actualizar caché de tarjetas: {e}")
            return self._cards_cache

    def invalidate_cache(self):
        """Fuerza recarga de tarjetas en la próxima llamada."""
        self._cache_time = 0.0

    # ── Búsqueda de tarjeta ───────────────────────────────────────────────────

    def find_card(self, dxf_filename: str) -> Tuple[Optional[Dict], float]:
        """
        Busca la tarjeta de Trello que mejor encaja con el nombre del DXF.

        Estrategia:
          1. Extrae el número de medida del nombre del DXF.
          2. Filtra tarjetas que contengan ese mismo número.
          3. Si hay una sola → la usa directamente.
          4. Si hay varias → elige la de mayor similitud Jaccard (tokens).

        Devuelve (tarjeta, score) o (None, 0.0).
        """
        numero = _extract_numero(dxf_filename)
        if not numero:
            log.debug(f"Trello: sin número de medida en '{dxf_filename}'")
            return None, 0.0

        dxf_norm = _normalize(Path(dxf_filename).stem)
        candidates: List[Tuple[float, Dict]] = []

        for card in self._get_cards():
            card_numero = _extract_numero(card["name"])
            if not card_numero or card_numero.upper() != numero.upper():
                continue
            score = _jaccard(dxf_norm, _normalize(card["name"]))
            candidates.append((score, card))

        if not candidates:
            log.debug(f"Trello: sin tarjeta con número '{numero}' para '{dxf_filename}'")
            return None, 0.0

        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_card = candidates[0]

        # Con un único candidato lo aceptamos sin umbral mínimo
        # (el número de medida ya es identificador suficiente)
        if len(candidates) == 1:
            log.debug(
                f"Trello: candidato único '{best_card['name'][:60]}' "
                f"(score={best_score:.2f})"
            )
            return best_card, best_score

        # Con varios candidatos exigimos score mínimo
        if best_score < self.min_score:
            log.warning(
                f"Trello: coincidencia ambigua para '{Path(dxf_filename).name}' "
                f"(score={best_score:.2f} < mínimo {self.min_score}). "
                f"Mejor candidato: '{best_card['name'][:60]}'"
            )
            return None, best_score

        return best_card, best_score

    # ── Adjuntar PDF ──────────────────────────────────────────────────────────

    def _attach_pdf(self, card_id: str, pdf_path: str) -> bool:
        """
        Sube el PDF a la tarjeta.
        Si ya existía un adjunto con el mismo nombre, lo elimina antes de subir.
        """
        pdf_name = Path(pdf_path).name

        # Eliminar adjunto anterior con el mismo nombre (si existe)
        try:
            attachments = _get(
                f"/cards/{card_id}/attachments",
                self.api_key, self.token,
                {"fields": "id,name"}
            )
            for att in attachments:
                if att.get("name", "") == pdf_name:
                    log.debug(f"Trello: eliminando adjunto anterior '{pdf_name}'")
                    _delete(
                        f"/cards/{card_id}/attachments/{att['id']}",
                        self.api_key, self.token
                    )
        except Exception as e:
            log.debug(f"Trello: aviso al comprobar adjuntos existentes: {e}")

        # Subir nuevo PDF
        result = _post_file(
            f"/cards/{card_id}/attachments",
            self.api_key, self.token,
            pdf_path, pdf_name
        )
        return bool(result.get("id"))

    # ── Punto de entrada público ──────────────────────────────────────────────

    def upload(self, dxf_path: str, pdf_path: str):
        """
        Busca la tarjeta correspondiente al DXF y adjunta el PDF.
        Los errores se registran pero no interrumpen el watcher.
        """
        if not self._board_id:
            return

        dxf_name = Path(dxf_path).name
        pdf_name = Path(pdf_path).name

        if not Path(pdf_path).exists():
            log.debug(f"Trello: PDF no encontrado, omitiendo: {pdf_path}")
            return

        try:
            card, score = self.find_card(dxf_name)
            if card is None:
                return

            log.info(
                f"  → Trello: adjuntando en '{card['name'][:55]}' "
                f"(coincidencia={score:.0%})"
            )
            ok = self._attach_pdf(card["id"], pdf_path)
            if ok:
                log.info(f"  ✓ Trello: PDF adjuntado correctamente")
            else:
                log.warning(f"  ✗ Trello: la subida no devolvió confirmación")
        except Exception as e:
            log.error(f"  ✗ Trello: error al adjuntar '{pdf_name}': {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Factory function  (usada desde dxf_watcher.py)
# ══════════════════════════════════════════════════════════════════════════════

def create_from_config(config: dict) -> Optional[TrelloUploader]:
    """
    Crea un TrelloUploader a partir de la sección 'trello' del config.
    Devuelve None si Trello está desactivado o hay error de credenciales.
    """
    trello_cfg = config.get("trello", {})
    if not trello_cfg.get("enabled", False):
        return None

    api_key = trello_cfg.get("api_key", "").strip()
    token   = trello_cfg.get("token",   "").strip()

    if not api_key or not token:
        log.warning(
            "Trello: 'enabled' es true pero faltan 'api_key' o 'token'. "
            "Edita watcher_config.json para configurarlos."
        )
        return None

    uploader = TrelloUploader(
        api_key       = api_key,
        token         = token,
        board_name    = trello_cfg.get("board_name",      "Planificador de Trabajo"),
        min_score     = trello_cfg.get("min_match_score", 0.3),
        cache_minutes = trello_cfg.get("cache_minutes",   30),
    )

    if uploader.connect():
        return uploader
    return None
