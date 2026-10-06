# Detiene el Postgres local del proyecto de forma ordenada.
$raiz = Split-Path $PSScriptRoot -Parent
$pg = (Get-Command pg_ctl -ErrorAction SilentlyContinue).Source
if (-not $pg) { $pg = "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" }
& $pg -D "$raiz\.pgdata" stop -m fast
