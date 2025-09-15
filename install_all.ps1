# Install and launch the BlockCorp portal on Windows
# This script creates a virtual environment, installs dependencies and runs the Flask app.

param(
    [string]$Port = "8000"
)

Write-Host "Iniciando instalación del Portal BlockCorp..."

# Ruta al directorio del script (raíz del proyecto)
$ProjPath = Split-Path -Parent $MyInvocation.MyCommand.Definition

Write-Host "Directorio del proyecto: $ProjPath"

# Comprobar que Python está instalado
try {
    $python = & python --version 2>$null
    Write-Host "Python detectado: $python"
} catch {
    Write-Error "Python no está instalado o no está en el PATH. Por favor instala Python 3 antes de continuar.";
    exit 1
}

# Crear entorno virtual
$venvPath = Join-Path $ProjPath '.venv'
if (-Not (Test-Path $venvPath)) {
    Write-Host "Creando entorno virtual en $venvPath..."
    & python -m venv $venvPath
} else {
    Write-Host "Entorno virtual ya existe."
}

# Instalar dependencias
Write-Host "Instalando dependencias..."
& "$venvPath\Scripts\pip.exe" install --upgrade pip | Out-Null
& "$venvPath\Scripts\pip.exe" install -r "$ProjPath\backend\requirements.txt" | Out-Null

Write-Host "Dependencias instaladas."

# Ejecutar la aplicación (servidor HTTP personalizado)
Write-Host "Iniciando la aplicación del portal..."
& "$venvPath\Scripts\python.exe" "$ProjPath\backend\app.py"
