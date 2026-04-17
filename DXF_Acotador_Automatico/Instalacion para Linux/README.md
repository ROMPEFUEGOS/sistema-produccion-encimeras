# DXF Acotador Automático — Instalación en Linux

Genera automáticamente un PDF con todas las cotas cada vez que se añade
o modifica un archivo `.dxf` en la carpeta que elijas.

---

## Archivos incluidos

| Archivo | Descripción |
|---|---|
| `dxf_auto_dim_v1.3.py` | Motor de acotación (no tocar) |
| `dxf_watcher.py` | Programa vigilante de carpetas |
| `watcher_config.json` | **Configuración — editar antes de usar** |
| `instalar_watcher_linux.sh` | Instala el servicio systemd con arranque automático |

---

## Requisitos previos

**Python 3.9+** y pip. En la mayoría de distribuciones ya viene instalado.
Verificar:
```bash
python3 --version
pip3 --version
```

Instalar librerías necesarias:
```bash
pip3 install watchdog matplotlib numpy networkx
```

En distribuciones basadas en Debian/Ubuntu también puedes usar apt:
```bash
sudo apt install python3-pip python3-matplotlib python3-numpy python3-networkx
pip3 install watchdog
```

---

## Paso 1 — Configurar la carpeta a vigilar

Edita `watcher_config.json` con cualquier editor de texto:
```bash
nano watcher_config.json
```

Cambia `watch_folder` por la ruta de tu carpeta. Ejemplos:

```json
"watch_folder": "/home/usuario/TRABAJOS_DXF"
```
```json
"watch_folder": "/mnt/servidor/TRABAJOS_DXF"
```
```json
"watch_folder": "/media/NAS/Compartido/TRABAJOS_DXF"
```

### Opciones de configuración

```json
{
  "watch_folder":      "/ruta/a/TRABAJOS_DXF",  <- Carpeta a vigilar
  "blacklist":         ["Archivo", "OLD"],       <- Subcarpetas a ignorar
  "debounce_seconds":  5,                        <- Segundos de espera tras guardar
  "scan_on_start":     true,                     <- Procesar DXF sin PDF al arrancar
  "log_file":          "dxf_watcher.log",        <- Archivo de registro
  "log_level":         "INFO"                    <- INFO o DEBUG (más detalle)
}
```

**blacklist**: cualquier carpeta cuyo nombre aparezca aquí será ignorada
completamente (sin distinguir mayúsculas/minúsculas).

---

## Paso 2 — Probar que funciona manualmente

```bash
cd /ruta/donde/copiaste/los/archivos
python3 dxf_watcher.py
```

Verás en consola:
```
2025-01-15 09:00:00  INFO     Vigilando : /ruta/a/TRABAJOS_DXF
2025-01-15 09:00:00  INFO     Observador activo. Esperando cambios...
```

Copia un `.dxf` a la carpeta vigilada. Tras ~5 segundos:
```
2025-01-15 09:00:08  INFO     ▶ Procesando: MiPieza.dxf
2025-01-15 09:00:11  INFO       ✓ PDF generado en 3.2s: MiPieza.pdf
```

El PDF aparece en la misma carpeta que el DXF.

Para detener: `Ctrl+C`.

---

## Paso 3 — Instalación como servicio automático (systemd)

Dar permisos de ejecución al instalador y ejecutarlo:
```bash
chmod +x instalar_watcher_linux.sh
./instalar_watcher_linux.sh
```

Esto crea un servicio de usuario systemd que:
- Arranca automáticamente al iniciar sesión
- Se reinicia solo si falla
- Guarda los logs en `dxf_watcher.log`

### Comandos de gestión del servicio

```bash
# Ver estado
systemctl --user status dxf-watcher

# Parar
systemctl --user stop dxf-watcher

# Arrancar
systemctl --user start dxf-watcher

# Ver logs en tiempo real
journalctl --user -u dxf-watcher -f

# Desinstalar completamente
systemctl --user disable --now dxf-watcher
rm ~/.config/systemd/user/dxf-watcher.service
systemctl --user daemon-reload
```

---

## Carpeta en red (NFS, Samba/CIFS)

Si la carpeta está en un servidor compartido, hay que montarla primero.

**Samba/Windows (CIFS):**
```bash
# Montar manualmente
sudo mount -t cifs //192.168.1.10/TRABAJOS_DXF /mnt/trabajos \
  -o username=TuUsuario,password=TuContraseña,uid=$(id -u),gid=$(id -g)

# Montar automáticamente en /etc/fstab:
//192.168.1.10/TRABAJOS_DXF  /mnt/trabajos  cifs  \
  username=TuUsuario,password=TuContraseña,uid=1000,gid=1000,_netdev,auto  0  0
```

**NFS:**
```bash
# Montar manualmente
sudo mount -t nfs 192.168.1.10:/TRABAJOS_DXF /mnt/trabajos

# Montar en /etc/fstab:
192.168.1.10:/TRABAJOS_DXF  /mnt/trabajos  nfs  defaults,_netdev  0  0
```

> Si usas montaje automático, asegúrate de que el servicio `dxf-watcher`
> arranque **después** de que la red esté disponible.
> Edita el archivo de servicio y añade en `[Unit]`:
> ```
> After=network-online.target remote-fs.target
> Wants=network-online.target
> ```

---

## Solución de problemas

| Problema | Causa probable | Solución |
|---|---|---|
| `ModuleNotFoundError: watchdog` | Librería no instalada | `pip3 install watchdog` |
| `Permission denied` en el script | Sin permisos de ejecución | `chmod +x instalar_watcher_linux.sh` |
| La carpeta de red no existe | No montada | Montar antes de arrancar el watcher |
| El servicio no arranca | Error de ruta | `journalctl --user -u dxf-watcher -n 50` para ver el error |
| PDF no se genera | DXF con geometría abierta | Ver `dxf_watcher.log` para el error concreto |

### Revisar el log

```bash
# Log del archivo (en la carpeta del watcher)
tail -f dxf_watcher.log

# Log del servicio systemd
journalctl --user -u dxf-watcher -f
```

---

## Cambiar la carpeta vigilada en cualquier momento

```bash
nano watcher_config.json   # editar watch_folder
systemctl --user restart dxf-watcher
```
