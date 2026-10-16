# Backs up PostgreSQL (pg_dump) and MongoDB (mongodump) from the running stack into ./backups/<timestamp>/
# Usage: ./scripts/backup.ps1 [-ComposeFile docker-compose.prod.yml] [-EnvFile .env.prod]
param([string]$ComposeFile = "docker-compose.yml", [string]$EnvFile = "")
$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dir = Join-Path "backups" $stamp
New-Item -ItemType Directory -Force $dir | Out-Null
$compose = @("compose", "-f", $ComposeFile)
if ($EnvFile) { $compose += @("--env-file", $EnvFile) }

$user = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "foodrescue" }
$db = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "foodrescue" }

docker @compose exec -T postgres pg_dump -U $user -d $db --format=custom | Set-Content -Path (Join-Path $dir "postgres.dump") -AsByteStream
docker @compose exec -T mongo mongodump --db foodrescue --archive --gzip | Set-Content -Path (Join-Path $dir "mongo.archive.gz") -AsByteStream
Write-Host "Backup written to $dir"
Write-Host "Restore: pg_restore -U $user -d $db < postgres.dump ; mongorestore --archive --gzip < mongo.archive.gz"
