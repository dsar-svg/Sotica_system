# Detiene el Postgres local del proyecto de forma ordenada.
$raiz = Split-Path $PSScriptRoot -Parent
& "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" -D "$raiz\.pgdata" stop -m fast
