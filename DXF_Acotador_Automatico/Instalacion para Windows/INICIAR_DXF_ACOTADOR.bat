@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
set "SD=%~dp0"
if "%SD:~-1%"=="\" set "SD=%SD:~0,-1%"
set "SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$lines=[IO.File]::ReadAllLines($env:SELF,[Text.Encoding]::UTF8);$in=$false;$ps=@();foreach($l in $lines){if($l -eq '::#PSEND'){$in=$false};if($in){$ps+=$l};if($l -eq '::#PSSTART'){$in=$true}};iex($ps -join \"`n\")"
exit /b %ERRORLEVEL%

::#PSSTART
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$SCRIPT_DIR = $env:SD

# ── Funciones de deteccion ───────────────────────────────────

function Get-PythonInfo {
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $out = & $cmd --version 2>&1
            if ("$out" -match "Python (\d+)\.(\d+)\.(\d+)") {
                if ([int]$Matches[1] -ge 3 -and [int]$Matches[2] -ge 6) {
                    return @{ Found = $true; Cmd = $cmd; Version = "$($Matches[1]).$($Matches[2]).$($Matches[3])" }
                }
            }
        } catch {}
    }
    return @{ Found = $false; Cmd = $null; Version = $null }
}

function Get-PkgVersion($cmd, $pkg) {
    try {
        $r = & $cmd -c "import $pkg; v=getattr($pkg,'__version__','ok'); print(v)" 2>&1
        if ($LASTEXITCODE -eq 0 -and $r) { return "$r".Trim() }
    } catch {}
    return $null
}

function Get-AllPkgs($pyInfo) {
    $pkgs = @{}
    foreach ($p in @("numpy", "matplotlib", "networkx", "watchdog")) {
        $pkgs[$p] = if ($pyInfo.Found) { Get-PkgVersion $pyInfo.Cmd $p } else { $null }
    }
    return $pkgs
}

function Start-Watcher($pyInfo) {
    $script = Join-Path $SCRIPT_DIR "dxf_watcher.py"
    if (Test-Path $script) {
        Start-Process $pyInfo.Cmd -ArgumentList "`"$script`"" -WindowStyle Minimized
        return $true
    }
    return $false
}

# ── Comprobacion inicial ─────────────────────────────────────

$pyInfo = Get-PythonInfo
$pkgs   = Get-AllPkgs $pyInfo
$allOK  = $pyInfo.Found -and ($pkgs.Values | Where-Object { $_ -eq $null }).Count -eq 0

if ($allOK) {
    Start-Watcher $pyInfo
    exit 0
}

# ── Construccion de la ventana ───────────────────────────────

$form = New-Object System.Windows.Forms.Form
$form.Text            = "DXF Acotador Automatico"
$form.ClientSize      = New-Object System.Drawing.Size(500, 504)
$form.StartPosition   = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox     = $false
$form.MinimizeBox     = $false
$form.BackColor       = [System.Drawing.Color]::White
$form.Font            = New-Object System.Drawing.Font("Segoe UI", 9)

# Cabecera azul
$hdr = New-Object System.Windows.Forms.Panel
$hdr.Dock      = "Top"
$hdr.Height    = 72
$hdr.BackColor = [System.Drawing.Color]::FromArgb(17, 85, 204)
$form.Controls.Add($hdr)

$t1 = New-Object System.Windows.Forms.Label
$t1.Text      = "DXF Acotador Automatico"
$t1.ForeColor = [System.Drawing.Color]::White
$t1.Font      = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$t1.AutoSize  = $true
$t1.Location  = New-Object System.Drawing.Point(18, 10)
$hdr.Controls.Add($t1)

$t2 = New-Object System.Windows.Forms.Label
$t2.Text      = "Faltan componentes necesarios - instalalos con un clic"
$t2.ForeColor = [System.Drawing.Color]::FromArgb(190, 215, 255)
$t2.Font      = New-Object System.Drawing.Font("Segoe UI", 9)
$t2.AutoSize  = $true
$t2.Location  = New-Object System.Drawing.Point(20, 46)
$hdr.Controls.Add($t2)

# Descripcion
$desc = New-Object System.Windows.Forms.Label
$desc.Text      = "El programa necesita estos componentes para funcionar correctamente:"
$desc.Location  = New-Object System.Drawing.Point(18, 86)
$desc.Size      = New-Object System.Drawing.Size(464, 20)
$desc.ForeColor = [System.Drawing.Color]::FromArgb(50, 50, 50)
$form.Controls.Add($desc)

# ── Filas de estado ──────────────────────────────────────────

$iconMap  = @{}
$panelMap = @{}

$rowDefs = @(
    @{ Key = "python";     Label = "Python 3.6+";  Desc = "Motor principal del programa";         Found = $pyInfo.Found;               Version = $pyInfo.Version          },
    @{ Key = "numpy";      Label = "numpy";         Desc = "Calculos numericos y geometria";       Found = $pkgs["numpy"]      -ne $null; Version = $pkgs["numpy"]          },
    @{ Key = "matplotlib"; Label = "matplotlib";    Desc = "Generacion de PDFs acotados";          Found = $pkgs["matplotlib"] -ne $null; Version = $pkgs["matplotlib"]      },
    @{ Key = "networkx";   Label = "networkx";      Desc = "Deteccion de contornos y formas";      Found = $pkgs["networkx"]   -ne $null; Version = $pkgs["networkx"]        },
    @{ Key = "watchdog";   Label = "watchdog";      Desc = "Vigilancia de carpetas en tiempo real"; Found = $pkgs["watchdog"]   -ne $null; Version = $pkgs["watchdog"]        }
)

$y = 114
foreach ($rd in $rowDefs) {
    $bgColor = if ($rd.Found) { [System.Drawing.Color]::FromArgb(244, 255, 244) } else { [System.Drawing.Color]::FromArgb(255, 244, 244) }

    $pnl = New-Object System.Windows.Forms.Panel
    $pnl.Location    = New-Object System.Drawing.Point(18, $y)
    $pnl.Size        = New-Object System.Drawing.Size(464, 48)
    $pnl.BackColor   = $bgColor
    $pnl.BorderStyle = "FixedSingle"
    $form.Controls.Add($pnl)
    $panelMap[$rd.Key] = $pnl

    $ico = New-Object System.Windows.Forms.Label
    $ico.Text      = if ($rd.Found) { [char]0x2713 } else { [char]0x2717 }
    $ico.ForeColor = if ($rd.Found) { [System.Drawing.Color]::FromArgb(0, 130, 0) } else { [System.Drawing.Color]::FromArgb(180, 0, 0) }
    $ico.Font      = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
    $ico.Location  = New-Object System.Drawing.Point(10, 9)
    $ico.Size      = New-Object System.Drawing.Size(30, 30)
    $pnl.Controls.Add($ico)
    $iconMap[$rd.Key] = $ico

    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text     = $rd.Label
    $lbl.Font     = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
    $lbl.Location = New-Object System.Drawing.Point(48, 6)
    $lbl.Size     = New-Object System.Drawing.Size(230, 18)
    $pnl.Controls.Add($lbl)

    $dlbl = New-Object System.Windows.Forms.Label
    $dlbl.Text      = $rd.Desc
    $dlbl.ForeColor = [System.Drawing.Color]::FromArgb(110, 110, 110)
    $dlbl.Font      = New-Object System.Drawing.Font("Segoe UI", 8)
    $dlbl.Location  = New-Object System.Drawing.Point(50, 26)
    $dlbl.Size      = New-Object System.Drawing.Size(230, 16)
    $pnl.Controls.Add($dlbl)

    $vlbl = New-Object System.Windows.Forms.Label
    $vlbl.Text      = if ($rd.Found) { "v" + $rd.Version } else { "No instalado" }
    $vlbl.ForeColor = if ($rd.Found) { [System.Drawing.Color]::FromArgb(100, 100, 100) } else { [System.Drawing.Color]::FromArgb(180, 0, 0) }
    $vlbl.Font      = New-Object System.Drawing.Font("Segoe UI", 9)
    $vlbl.Location  = New-Object System.Drawing.Point(295, 15)
    $vlbl.Size      = New-Object System.Drawing.Size(160, 20)
    $vlbl.TextAlign = "MiddleRight"
    $pnl.Controls.Add($vlbl)

    $y += 54
}

# Separador
$sep = New-Object System.Windows.Forms.Label
$sep.BorderStyle = "Fixed3D"
$sep.Location    = New-Object System.Drawing.Point(18, 386)
$sep.Size        = New-Object System.Drawing.Size(464, 2)
$form.Controls.Add($sep)

# Barra de progreso (oculta al inicio)
$prog = New-Object System.Windows.Forms.ProgressBar
$prog.Location               = New-Object System.Drawing.Point(18, 400)
$prog.Size                   = New-Object System.Drawing.Size(464, 18)
$prog.Style                  = "Marquee"
$prog.MarqueeAnimationSpeed  = 25
$prog.Visible                = $false
$form.Controls.Add($prog)

# Etiqueta de estado
$sLbl = New-Object System.Windows.Forms.Label
$sLbl.Location  = New-Object System.Drawing.Point(18, 398)
$sLbl.Size      = New-Object System.Drawing.Size(464, 22)
$sLbl.Text      = "Pulsa 'Instalar' para descargar e instalar todo automaticamente."
$sLbl.ForeColor = [System.Drawing.Color]::FromArgb(80, 80, 80)
$form.Controls.Add($sLbl)

# Boton instalar
$btnInst = New-Object System.Windows.Forms.Button
$btnInst.Text                        = "Instalar automaticamente"
$btnInst.Location                    = New-Object System.Drawing.Point(18, 436)
$btnInst.Size                        = New-Object System.Drawing.Size(240, 46)
$btnInst.BackColor                   = [System.Drawing.Color]::FromArgb(17, 85, 204)
$btnInst.ForeColor                   = [System.Drawing.Color]::White
$btnInst.FlatStyle                   = "Flat"
$btnInst.FlatAppearance.BorderSize   = 0
$btnInst.Font                        = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
$btnInst.Cursor                      = [System.Windows.Forms.Cursors]::Hand
$form.Controls.Add($btnInst)

# Boton cancelar
$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Text     = "Cancelar"
$btnClose.Location = New-Object System.Drawing.Point(272, 436)
$btnClose.Size     = New-Object System.Drawing.Size(120, 46)
$btnClose.FlatStyle = "Flat"
$btnClose.Font     = New-Object System.Drawing.Font("Segoe UI", 10)
$btnClose.Cursor   = [System.Windows.Forms.Cursors]::Hand
$form.Controls.Add($btnClose)
$btnClose.Add_Click({ $form.Close() })

# ── Logica del boton Instalar ────────────────────────────────

$btnInst.Add_Click({
    $btnInst.Enabled  = $false
    $btnClose.Enabled = $false
    $sLbl.Visible     = $false
    $prog.Visible     = $true
    $form.Refresh()

    $curPy     = Get-PythonInfo
    $installOK = $true

    # 1. Instalar Python si no esta presente
    if (-not $curPy.Found) {
        $sLbl.Text      = "Descargando Python 3.11 desde python.org..."
        $sLbl.ForeColor = [System.Drawing.Color]::FromArgb(17, 85, 204)
        $sLbl.Visible   = $true
        $form.Refresh()

        $pyUrl  = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
        $pyInst = Join-Path $env:TEMP "python_setup_dxf.exe"

        try {
            $wc = New-Object System.Net.WebClient
            $wc.DownloadFile($pyUrl, $pyInst)

            $sLbl.Text = "Instalando Python 3.11... (puede tardar 2-3 minutos)"
            $form.Refresh()

            $p = Start-Process $pyInst -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0 CompileAll=0" -Wait -PassThru
            Remove-Item $pyInst -ErrorAction SilentlyContinue

            # Refrescar PATH para encontrar el Python recien instalado
            $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","User") + ";" +
                        [System.Environment]::GetEnvironmentVariable("PATH","Machine")
            $curPy = Get-PythonInfo

            if ($curPy.Found) {
                $iconMap["python"].Text       = [char]0x2713
                $iconMap["python"].ForeColor  = [System.Drawing.Color]::FromArgb(0, 130, 0)
                $panelMap["python"].BackColor = [System.Drawing.Color]::FromArgb(244, 255, 244)
                $form.Refresh()
            } else {
                $installOK = $false
            }
        } catch {
            $installOK = $false
            [System.Windows.Forms.MessageBox]::Show(
                "No se pudo descargar Python automaticamente.`nComprueba la conexion a internet.`n`nDescarga manual: https://www.python.org/downloads/`n(Marca 'Add Python to PATH' durante la instalacion)",
                "Error de descarga", "OK", "Warning")
        }
    }

    # 2. Instalar paquetes pip que falten
    if ($curPy.Found) {
        $missing = @()
        foreach ($p in @("numpy", "matplotlib", "networkx", "watchdog")) {
            if ((Get-PkgVersion $curPy.Cmd $p) -eq $null) { $missing += $p }
        }

        if ($missing.Count -gt 0) {
            $sLbl.Text      = "Instalando: $($missing -join ', ')..."
            $sLbl.ForeColor = [System.Drawing.Color]::FromArgb(17, 85, 204)
            $sLbl.Visible   = $true
            $form.Refresh()

            $argList = @("-m", "pip", "install", "--upgrade", "--quiet") + $missing
            Start-Process $curPy.Cmd -ArgumentList $argList -Wait -WindowStyle Hidden
        }

        # Reverificar paquetes
        $newPkgs = Get-AllPkgs $curPy
        foreach ($p in @("numpy", "matplotlib", "networkx", "watchdog")) {
            if ($newPkgs[$p] -ne $null) {
                $iconMap[$p].Text       = [char]0x2713
                $iconMap[$p].ForeColor  = [System.Drawing.Color]::FromArgb(0, 130, 0)
                $panelMap[$p].BackColor = [System.Drawing.Color]::FromArgb(244, 255, 244)
            } else {
                $installOK = $false
            }
        }
        $form.Refresh()
    }

    $prog.Visible = $false

    if ($installOK -and $curPy.Found) {
        # Exito
        $sLbl.Text      = "Todo instalado correctamente. El programa esta listo para usar."
        $sLbl.ForeColor = [System.Drawing.Color]::FromArgb(0, 130, 0)
        $sLbl.Visible   = $true

        $btnInst.Visible = $false

        $btnStart = New-Object System.Windows.Forms.Button
        $btnStart.Text                      = "Iniciar DXF Watcher"
        $btnStart.Location                  = New-Object System.Drawing.Point(18, 436)
        $btnStart.Size                      = New-Object System.Drawing.Size(230, 46)
        $btnStart.BackColor                 = [System.Drawing.Color]::FromArgb(0, 140, 50)
        $btnStart.ForeColor                 = [System.Drawing.Color]::White
        $btnStart.FlatStyle                 = "Flat"
        $btnStart.FlatAppearance.BorderSize = 0
        $btnStart.Font                      = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
        $btnStart.Cursor                    = [System.Windows.Forms.Cursors]::Hand
        $form.Controls.Add($btnStart)
        $btnStart.BringToFront()
        $btnStart.Add_Click({
            Start-Watcher $curPy | Out-Null
            $form.Close()
        })

        $btnClose.Text     = "Cerrar"
        $btnClose.Location = New-Object System.Drawing.Point(262, 436)
        $btnClose.Enabled  = $true
    } else {
        # Error parcial
        $sLbl.Text      = "Algunos componentes no se pudieron instalar. Comprueba la conexion."
        $sLbl.ForeColor = [System.Drawing.Color]::FromArgb(180, 0, 0)
        $sLbl.Visible   = $true
        $btnInst.Enabled  = $true
        $btnClose.Enabled = $true
    }

    $form.Refresh()
})

[void]$form.ShowDialog()
::#PSEND
