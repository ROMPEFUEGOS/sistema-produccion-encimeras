# DXF Acotador Automático

Sistema de acotación automática de piezas industriales en formato DXF.
Genera un PDF completo con todas las dimensiones cada vez que se añade
o modifica un `.dxf` en la carpeta de trabajos.

---

## ¿Qué hace?

1. **Vigila** una carpeta (local o de red) de forma continua y silenciosa.
2. Cuando detecta un `.dxf` nuevo o modificado, genera automáticamente
   un **PDF acotado** con:
   - Cadenas de cotas horizontales y verticales
   - Cotas de aristas diagonales (longitud + ángulo)
   - Radios de arcos y esquinas redondeadas
   - Marcas de ángulo en esquinas
   - Dimensiones de posición de huecos (fregaderos, enchufes, etc.)
   - Indicador de descuadro cuando la pieza no es perfectamente ortogonal
3. **Ignora** las carpetas que pongas en la lista negra (ej: "Archivo").
4. Al arrancar, escanea y procesa cualquier DXF que no tenga PDF o
   que tenga el PDF más antiguo que el DXF.

---

## Estructura de carpetas

```
DXF_Acotador_Automatico/
│
├── Instalacion para Windows/
│   ├── README.md                      <- Instrucciones para Windows
│   ├── dxf_auto_dim_v1.3.py           <- Motor de acotación
│   ├── dxf_watcher.py                 <- Vigilante de carpetas
│   ├── watcher_config.json            <- Configuración
│   ├── iniciar_watcher.bat            <- Arranque manual
│   └── instalar_inicio_automatico.bat <- Arranque con Windows
│
└── Instalacion para Linux/
    ├── README.md                      <- Instrucciones para Linux
    ├── dxf_auto_dim_v1.3.py           <- Motor de acotación
    ├── dxf_watcher.py                 <- Vigilante de carpetas
    ├── watcher_config.json            <- Configuración
    └── instalar_watcher_linux.sh      <- Instalador de servicio systemd
```

---

## Inicio rápido

### Windows
1. Copia la carpeta **`Instalacion para Windows`** al ordenador.
2. Edita `watcher_config.json` → cambia `watch_folder` por tu ruta.
3. Doble clic en `iniciar_watcher.bat` para probar.
4. Doble clic en `instalar_inicio_automatico.bat` para que arranque solo.

### Linux
1. Copia la carpeta **`Instalacion para Linux`** al ordenador.
2. Edita `watcher_config.json` → cambia `watch_folder` por tu ruta.
3. `python3 dxf_watcher.py` para probar.
4. `./instalar_watcher_linux.sh` para instalar como servicio.

---

## Configuración en 30 segundos

Abre `watcher_config.json` y cambia **únicamente** `watch_folder`:

```json
{
  "watch_folder": "Z:\\TRABAJOS_DXF",
  "blacklist": ["Archivo", "OLD", "BORRADOR"],
  "debounce_seconds": 5
}
```

Ver el README de tu sistema operativo para instrucciones completas.

---

## Compatibilidad de archivos DXF

| Tipo de entidad | Soportado |
|---|---|
| LINE | Sí |
| ARC | Sí |
| CIRCLE | Sí |
| LWPOLYLINE | Sí |
| POLYLINE / VERTEX | Sí |
| SPLINE | Sí (B-spline deg. 2 y 3) |
| INSERT / BLOCK | Sí (expansión con transformación) |
| Versiones DXF | AC1009 – AC1021 (AutoCAD R12 – 2007+) |

Tasa de éxito en archivos de producción real: **~98.7%**
Los fallos restantes corresponden a archivos vacíos, rutas abiertas
o geometría genuinamente incompleta.
