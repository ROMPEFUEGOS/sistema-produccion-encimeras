#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║              DXF WATCHER  v1.0                           ║
║  Monitoriza carpetas y genera PDFs automáticamente       ║
║  cuando se añade o modifica un archivo .dxf              ║
╚══════════════════════════════════════════════════════════╝

Uso:
    python dxf_watcher.py                   # usa watcher_config.json
    python dxf_watcher.py --config mi.json  # config personalizada
    python dxf_watcher.py --scan-now        # escanea primero los DXF sin PDF

Requisito:
    pip install watchdog
"""

import os
import sys
import json
import time
import signal
import logging
import argparse
import platform
import threading
import subprocess
from pathlib import Path
from datetime import datetime

# ── Intentar importar watchdog ─────────────────────────────────────────────────
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
except ImportError:
    print("ERROR: La librería 'watchdog' no está instalada.")
    print("       Instálala con:  pip install watchdog")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN POR DEFECTO
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    # Carpeta a vigilar (se puede poner ruta de red: \\servidor\TRABAJOS_DXF)
    "watch_folder": "",

    # Script del acotador DXF (ruta absoluta o relativa a este archivo)
    "dimensioner_script": "dxf_auto_dim_v1.3.py",

    # Carpetas/nombres a ignorar (se comprueba en cada componente de la ruta)
    # La comparación es sin distinción de mayúsculas/minúsculas
    "blacklist": [
        "Archivo",
        "ARCHIVO",
        "archivo",
        "archive",
        "OLD",
        "old",
        "BORRADOR",
        "borrador"
    ],

    # Segundos a esperar tras el último evento antes de procesar
    # (evita procesar mientras el archivo se está guardando)
    "debounce_seconds": 5,

    # Escanear al arrancar y procesar DXF que no tienen PDF (o PDF más antiguo)
    "scan_on_start": True,

    # Archivo de log (vacío = solo consola)
    "log_file": "dxf_watcher.log",

    # Nivel de log: DEBUG, INFO, WARNING, ERROR
    "log_level": "INFO",

    # Python a usar (vacío = el mismo python que ejecuta este script)
    "python_executable": ""
}

CONFIG_FILE = "watcher_config.json"


# ══════════════════════════════════════════════════════════════════════════════
#  UTILIDADES DE LOG
# ══════════════════════════════════════════════════════════════════════════════

def setup_logging(config: dict):
    level = getattr(logging, config.get("log_level", "INFO").upper(), logging.INFO)
    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = config.get("log_file", "")
    if log_file:
        log_path = Path(log_file)
        if not log_path.is_absolute():
            log_path = Path(__file__).parent / log_path
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers
    )

log = logging.getLogger("dxf_watcher")


# ══════════════════════════════════════════════════════════════════════════════
#  CARGA DE CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════

def load_config(config_path: str) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = Path(config_path)
    if not path.is_absolute():
        path = Path(__file__).parent / path

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                user_cfg = json.load(f)
            cfg.update(user_cfg)
            log.info(f"Configuración cargada: {path}")
        except Exception as e:
            log.warning(f"No se pudo leer {path}: {e}. Usando valores por defecto.")
    else:
        log.info(f"No se encontró {path}. Creando configuración por defecto...")
        save_config(cfg, path)

    return cfg


def save_config(cfg: dict, path: Path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        log.info(f"Configuración guardada en: {path}")
    except Exception as e:
        log.warning(f"No se pudo guardar config: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  LÓGICA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def is_blacklisted(filepath: str, blacklist: list) -> bool:
    """Comprueba si algún componente de la ruta está en la lista negra."""
    parts = Path(filepath).parts
    bl_lower = [b.lower() for b in blacklist]
    for part in parts:
        if part.lower() in bl_lower:
            return True
    return False


def get_python():
    """Devuelve la ruta al ejecutable Python actual."""
    return sys.executable


def pdf_is_current(dxf_path: str) -> bool:
    """True si el PDF existe y es más nuevo que el DXF."""
    pdf_path = Path(dxf_path).with_suffix(".pdf")
    if not pdf_path.exists():
        return False
    return pdf_path.stat().st_mtime >= Path(dxf_path).stat().st_mtime


def process_dxf(dxf_path: str, config: dict):
    """Genera el PDF para el archivo DXF dado."""
    dxf_path = str(Path(dxf_path).resolve())

    if is_blacklisted(dxf_path, config.get("blacklist", [])):
        log.debug(f"IGNORADO (blacklist): {dxf_path}")
        return

    # Resolver script del acotador
    script = config.get("dimensioner_script", "dxf_auto_dim_v1.3.py")
    script_path = Path(script)
    if not script_path.is_absolute():
        script_path = Path(__file__).parent / script_path
    if not script_path.exists():
        log.error(f"No se encuentra el script: {script_path}")
        return

    python = config.get("python_executable") or get_python()

    log.info(f"▶ Procesando: {Path(dxf_path).name}")
    t0 = time.time()
    try:
        result = subprocess.run(
            [python, str(script_path), dxf_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutos máximo
            encoding="utf-8",
            errors="replace"
        )
        elapsed = time.time() - t0
        if result.returncode == 0:
            log.info(f"  ✓ PDF generado en {elapsed:.1f}s: {Path(dxf_path).with_suffix('.pdf').name}")
        else:
            # Extraer mensaje de error relevante
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            msg = stderr or stdout
            # Buscar líneas con ✗ o Error
            for line in (stdout + "\n" + stderr).splitlines():
                if "✗" in line or "Error" in line or "error" in line:
                    msg = line.strip()
                    break
            log.warning(f"  ✗ Fallo en {elapsed:.1f}s: {msg}")
    except subprocess.TimeoutExpired:
        log.error(f"  ✗ Timeout (>5min): {Path(dxf_path).name}")
    except Exception as e:
        log.error(f"  ✗ Excepción: {e}")


def scan_folder(watch_folder: str, config: dict):
    """Escanea la carpeta y procesa DXF sin PDF o con PDF desactualizado."""
    log.info("── Escaneando carpeta en busca de DXF sin PDF actualizado...")
    count = 0
    for dxf_path in Path(watch_folder).rglob("*.dxf"):
        if dxf_path.name.startswith(("#", "~")):
            continue
        if dxf_path.name.endswith(("~", ".bak")):
            continue
        if is_blacklisted(str(dxf_path), config.get("blacklist", [])):
            continue
        if not pdf_is_current(str(dxf_path)):
            process_dxf(str(dxf_path), config)
            count += 1
    if count == 0:
        log.info("── Todos los DXF tienen PDF actualizado.")
    else:
        log.info(f"── Escaneo completado: {count} archivo(s) procesado(s).")


# ══════════════════════════════════════════════════════════════════════════════
#  HANDLER DE EVENTOS DE ARCHIVO
# ══════════════════════════════════════════════════════════════════════════════

class DxfEventHandler(FileSystemEventHandler):
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.debounce = config.get("debounce_seconds", 5)
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _schedule(self, path: str):
        """Programa el procesamiento con debounce (cancela el anterior si existe)."""
        # Filtros rápidos
        p = Path(path)
        if p.suffix.lower() != ".dxf":
            return
        if p.name.startswith(("#", "~")) or p.name.endswith(("~", ".bak")):
            return
        if is_blacklisted(path, self.config.get("blacklist", [])):
            log.debug(f"IGNORADO (blacklist): {p.name}")
            return

        with self._lock:
            # Cancelar timer anterior para este archivo
            if path in self._timers:
                self._timers[path].cancel()

            log.debug(f"  Evento en: {p.name} — esperando {self.debounce}s...")
            timer = threading.Timer(self.debounce, self._fire, args=[path])
            timer.daemon = True
            self._timers[path] = timer
            timer.start()

    def _fire(self, path: str):
        """Ejecutado tras el debounce."""
        with self._lock:
            self._timers.pop(path, None)
        # Verificar que el archivo sigue existiendo
        if not Path(path).exists():
            log.debug(f"Archivo ya no existe: {path}")
            return
        process_dxf(path, self.config)

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_moved(self, event):
        # Un "Guardar como" puede aparecer como move
        if not event.is_directory:
            self._schedule(event.dest_path)


# ══════════════════════════════════════════════════════════════════════════════
#  PUNTO DE ENTRADA
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="DXF Watcher — Generador automático de PDFs")
    parser.add_argument("--config", default=CONFIG_FILE, help="Ruta al archivo de configuración JSON")
    parser.add_argument("--scan-now", action="store_true", help="Escanear carpeta ahora y procesar DXFs sin PDF")
    parser.add_argument("--folder", help="Carpeta a vigilar (sobreescribe config)")
    args = parser.parse_args()

    # Logging básico antes de cargar config
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    config = load_config(args.config)
    setup_logging(config)

    # Override de carpeta desde argumento
    if args.folder:
        config["watch_folder"] = args.folder

    watch_folder = config.get("watch_folder", "").strip()

    # Si no hay carpeta configurada, preguntar
    if not watch_folder:
        print()
        print("No se ha configurado ninguna carpeta a vigilar.")
        print(f"Edita '{args.config}' y pon la ruta en 'watch_folder'.")
        print()
        watch_folder = input("O escribe la ruta ahora: ").strip().strip('"')
        if not watch_folder:
            print("Sin carpeta. Saliendo.")
            sys.exit(1)
        config["watch_folder"] = watch_folder
        save_config(config, Path(__file__).parent / args.config)

    watch_path = Path(watch_folder)
    if not watch_path.exists():
        log.error(f"La carpeta no existe o no está accesible: {watch_folder}")
        log.error("Comprueba la ruta en watcher_config.json y que la unidad de red esté montada.")
        sys.exit(1)

    log.info("══════════════════════════════════════════════════════════")
    log.info("  DXF WATCHER  v1.0")
    log.info(f"  Vigilando : {watch_folder}")
    bl = config.get('blacklist', [])
    log.info(f"  Blacklist  : {', '.join(bl) if bl else '(ninguna)'}")
    log.info(f"  Debounce   : {config.get('debounce_seconds', 5)}s")
    log.info(f"  Python     : {config.get('python_executable') or get_python()}")
    log.info("  Ctrl+C para detener")
    log.info("══════════════════════════════════════════════════════════")

    # Escaneo inicial
    if args.scan_now or config.get("scan_on_start", True):
        scan_folder(watch_folder, config)

    # Iniciar observador
    handler = DxfEventHandler(config)
    observer = Observer()
    observer.schedule(handler, watch_folder, recursive=True)
    observer.start()
    log.info("▶ Observador activo. Esperando cambios...")

    # Manejo de señales para apagado limpio
    def shutdown(sig=None, frame=None):
        log.info("Deteniendo observador...")
        observer.stop()
        observer.join()
        log.info("DXF Watcher detenido.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while observer.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
