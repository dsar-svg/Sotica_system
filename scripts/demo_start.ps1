# Arranca todo lo necesario para la demo: base de datos y panel en http://localhost:8000
# Uso, desde la raíz del repo:  .\scripts\demo_start.ps1      (Ctrl+C para detener el panel)
$raiz = Split-Path $PSScriptRoot -Parent
Set-Location $raiz
& "$PSScriptRoot\db_start.ps1"
Write-Host "Panel en http://localhost:8000"
& "$raiz\.venv\Scripts\python.exe" -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
