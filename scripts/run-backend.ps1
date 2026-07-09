$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location (Join-Path $Root "backend")
uvicorn main:app --reload --host 0.0.0.0 --port 8005
