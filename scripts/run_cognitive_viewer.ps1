param()

Set-Location -Path "$PSScriptRoot\.."
$server = Start-Process -FilePath python -ArgumentList "-m", "http.server", "8000" -WorkingDirectory "knowledge_db" -PassThru
Start-Sleep -Seconds 1
Start-Process "http://localhost:8000/cognitive_graph_viewer.html"
Write-Host "Premi Ctrl+C qui per fermare il server." -ForegroundColor Yellow
try {
    Wait-Process -Id $server.Id
} finally {
    if (!$server.HasExited) { $server | Stop-Process }
}
