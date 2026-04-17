# DXF Acotador Automático — Instalación en Windows

Genera automáticamente un PDF con todas las cotas cada vez que se añade
o modifica un archivo `.dxf` en la carpeta que elijas.

---

## Inicio rápido

**Doble clic en `INICIAR_DXF_ACOTADOR.bat`** — detecta automáticamente
si faltan requisitos y los instala con un clic.

---

## Archivos incluidos

| Archivo | Descripción |
|---|---|
| `INICIAR_DXF_ACOTADOR.bat` | **Launcher principal — empieza aquí** |
| `dxf_auto_dim_v1.3.py` | Motor de acotación (no tocar) |
| `dxf_watcher.py` | Programa vigilante de carpetas |
| `watcher_config.json` | **Configuración — editar antes de usar** |
| `iniciar_watcher.bat` | Arranca el watcher (requiere Python ya instalado) |
| `instalar_inicio_automatico.bat` | Instala el arranque automático con Windows |

---

## Requisitos (el launcher los instala automáticamente)

- **Python 3.6+** — si no está instalado, el launcher lo descarga de python.org
- **numpy**, **matplotlib**, **networkx** — se instalan vía pip automáticamente

Si prefieres instalar manualmente:
```
pip install matplotlib numpy networkx
```

---

## Paso 1 — Configurar la carpeta a vigilar

Abre `watcher_config.json` con el Bloc de notas y cambia `watch_folder`
por la ruta de tu carpeta de trabajos. Ejemplos:

```json
"watch_folder": "Z:\\TRABAJOS_DXF"
```
```json
"watch_folder": "\\\\SERVIDOR\\Compartido\\TRABAJOS_DXF"
```
```json
"watch_folder": "C:\\Users\\TuUsuario\\Documentos\\TRABAJOS_DXF"
```

> **Importante:** En Windows las rutas usan `\\` doble como separador dentro
> del JSON, o `/` barra normal (ambas funcionan).

### Opciones de configuración

```json
{
  "watch_folder":      "Z:\\TRABAJOS_DXF",   <- Carpeta a vigilar
  "blacklist":         ["Archivo", "OLD"],    <- Subcarpetas a ignorar
  "debounce_seconds":  5,                    <- Segundos de espera tras guardar
  "scan_on_start":     true,                 <- Procesar DXF sin PDF al arrancar
  "log_file":          "dxf_watcher.log",    <- Archivo de registro (mismo directorio)
  "log_level":         "INFO"                <- INFO o DEBUG (más detalle)
}
```

**blacklist**: cualquier carpeta cuyo nombre aparezca aquí será ignorada
completamente (sin distinguir mayúsculas/minúsculas). Por ejemplo, si pones
`"Archivo"` se ignorarán rutas como `TRABAJOS_DXF\Archivo\...` o
`TRABAJOS_DXF\cualquier\cosa\ARCHIVO\...`.

---

## Paso 2 — Probar que funciona

Haz doble clic en **`iniciar_watcher.bat`**.

Verás una ventana de consola con mensajes como:
```
2025-01-15 09:00:00  INFO     Vigilando : Z:\TRABAJOS_DXF
2025-01-15 09:00:00  INFO     Observador activo. Esperando cambios...
```

Copia un archivo `.dxf` a la carpeta vigilada. Después de ~5 segundos
aparecerá:
```
2025-01-15 09:00:08  INFO     ▶ Procesando: MiPieza.dxf
2025-01-15 09:00:11  INFO       ✓ PDF generado en 3.2s: MiPieza.pdf
```

El PDF aparecerá en la misma carpeta que el DXF.

Para detener: cierra la ventana o pulsa `Ctrl+C`.

---

## Paso 3 — Instalación automática (arranque con Windows)

Para que el watcher arranque solo cada vez que inicias sesión,
**sin ventana visible**, ejecuta como Administrador:

```
instalar_inicio_automatico.bat
```

Esto crea una tarea en el **Programador de Tareas de Windows**.

Para verificar que está activo:
```
schtasks /query /tn DXF_Watcher
```

Para desinstalar el arranque automático:
```
schtasks /delete /tn DXF_Watcher /f
```

---

## Solución de problemas

| Problema | Causa probable | Solución |
|---|---|---|
| `python` no se reconoce | Python no está en el PATH | Reinstalar Python con "Add to PATH" marcado |
| `No se encuentra el script` | Ruta del acotador incorrecta | `dimensioner_script` en config debe apuntar a `dxf_auto_dim_v1.3.py` |
| La carpeta de red no existe | Unidad no montada | Conectar la unidad de red antes de arrancar el watcher |
| PDF no se genera | DXF con geometría abierta | Ver `dxf_watcher.log` para el error concreto |
| Se generan PDFs de la carpeta Archivo | Nombre no en blacklist | Añadir el nombre exacto a `"blacklist"` en la config |

### Revisar el log

El archivo `dxf_watcher.log` (en la misma carpeta) guarda todo el historial:
```
2025-01-15 09:00:08  INFO     ▶ Procesando: MiPieza.dxf
2025-01-15 09:00:11  INFO       ✓ PDF generado en 3.2s: MiPieza.pdf
2025-01-15 09:01:00  WARNING    ✗ Fallo: No se detectaron polígonos
```

---

## Cambiar la carpeta vigilada en cualquier momento

Basta con editar `watcher_config.json` y reiniciar el watcher
(cerrar y volver a abrir, o reiniciar el equipo si está como tarea automática).
