# Run on your Windows PC (Docker running) from the repository root:
#   powershell -ExecutionPolicy Bypass -File deploy\export-knowledge-base.ps1
# Creates a Qdrant snapshot of the knowledge base and saves it to deploy\snapshots\.
# The snapshot contains the stored embeddings, so restoring it on the server
# costs no Gemini credits. deploy\snapshots\ is git-ignored.
$ErrorActionPreference = "Stop"
$base = "http://localhost:16333"
$collection = "fjara_knowledge_v1"
$outDir = Join-Path $PSScriptRoot "snapshots"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$created = Invoke-RestMethod -Method Post -Uri "$base/collections/$collection/snapshots?wait=true"
$name = $created.result.name
$target = Join-Path $outDir $name
Invoke-WebRequest -Uri "$base/collections/$collection/snapshots/$name" -OutFile $target
$info = Invoke-RestMethod -Uri "$base/collections/$collection"
Write-Output ("Saved {0} ({1:N1} MB) with {2} chunks" -f $target, ((Get-Item $target).Length / 1MB), $info.result.points_count)
