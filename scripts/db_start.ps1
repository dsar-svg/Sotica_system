# Levanta el Postgres local del proyecto (carpeta .pgdata, puerto 5433).
# Uso, desde la raíz del repo:  .\scripts\db_start.ps1
$pg = "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe"
$raiz = Split-Path $PSScriptRoot -Parent
& $pg -D "$raiz\.pgdata" status *> $null
if ($LASTEXITCODE -eq 0) { Write-Host "Postgres del proyecto ya estaba corriendo (puerto 5433)."; exit 0 }
# El log va FUERA de .pgdata: dentro, Postgres lo encuentra bloqueado al recuperarse.
Start-Process -FilePath $pg -ArgumentList '-D', "`"$raiz\.pgdata`"", '-o', '"-p 5433"', '-l', "`"$raiz\.pgdata.log`"", '-w', 'start' -WindowStyle Hidden -Wait
& $pg -D "$raiz\.pgdata" status | Select-Object -First 1
