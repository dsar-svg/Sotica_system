# Levanta el Postgres local del proyecto (carpeta .pgdata, puerto 5433).
# Uso, desde la raíz del repo:  .\scripts\db_start.ps1
# pg_ctl del PATH (scoop, o instalador que lo agregó); si no, la ruta por defecto del instalador.
$pg = (Get-Command pg_ctl -ErrorAction SilentlyContinue).Source
if (-not $pg) { $pg = "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" }
$raiz = Split-Path $PSScriptRoot -Parent
& $pg -D "$raiz\.pgdata" status *> $null
if ($LASTEXITCODE -eq 0) { Write-Host "Postgres del proyecto ya estaba corriendo (puerto 5433)."; exit 0 }
# El log va FUERA de .pgdata: dentro, Postgres lo encuentra bloqueado al recuperarse.
# Sin -Wait: Start-Process -Wait espera también al proceso postgres hijo y no vuelve nunca.
# WaitForExit espera solo a pg_ctl, que con -w termina cuando la base acepta conexiones.
$p = Start-Process -FilePath $pg -ArgumentList '-D', "`"$raiz\.pgdata`"", '-o', '"-p 5433"', '-l', "`"$raiz\.pgdata.log`"", '-w', 'start' -WindowStyle Hidden -PassThru
$p.WaitForExit()
& $pg -D "$raiz\.pgdata" status | Select-Object -First 1
