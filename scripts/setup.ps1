$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Installing Python dependencies..."
pip install -r requirements.txt

Write-Host "Bootstrapping database and vector indexes..."
python backend/bootstrap.py

Write-Host "Installing frontend dependencies..."
Set-Location frontend
npm install

Write-Host "Setup complete. Run scripts/run-backend.ps1 and scripts/run-frontend.ps1 to start."
