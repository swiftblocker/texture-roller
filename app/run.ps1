# Starts the pottery roller generator on 127.0.0.1:8790 (local only).
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Split-Path -Parent $here)
python -m uvicorn server:app --app-dir app --host 127.0.0.1 --port 8790
