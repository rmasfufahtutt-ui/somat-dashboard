# Cek pohon rilis SOMAT (Windows PowerShell). Jalankan dari folder repo:  powershell -ExecutionPolicy Bypass -File tools\check_release_tree.ps1
# Hanya MEMBACA dan melaporkan; tidak menghapus apa pun.
$root = (Get-Location).Path
Write-Host "Folder repo: $root"
$nested = Get-ChildItem -Directory -Recurse -Depth 3 -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -eq "somat-dashboard" -or (Test-Path (Join-Path $_.FullName "app.py")) -and $_.FullName -ne $root }
if (-not $nested) { Write-Host "OK  - tidak ada salinan pohon aplikasi di dalam repo." }
foreach ($d in $nested) {
  Write-Host "ADA SALINAN: $($d.FullName)"
  $diff = @()
  Get-ChildItem -File -Recurse $d.FullName -Include *.py | ForEach-Object {
    $rel = $_.FullName.Substring($d.FullName.Length).TrimStart('\')
    $main = Join-Path $root $rel
    if (-not (Test-Path $main)) { $diff += "HANYA DI SALINAN : $rel" }
    elseif ((Get-FileHash $_.FullName).Hash -ne (Get-FileHash $main).Hash) { $diff += "BEDA ISI        : $rel" }
  }
  if ($diff) { $diff | ForEach-Object { Write-Host "  $_" } } else { Write-Host "  (semua .py identik dengan pohon utama)" }
}
Write-Host ""
Write-Host "Entry point Streamlit Cloud harus: app.py (di akar repo)."
if (Test-Path (Join-Path $root "app.py")) { Write-Host "OK  - app.py ada di akar." } else { Write-Host "SALAH - app.py tidak ada di akar." }
Get-ChildItem -File -Include *.rar,*.zip -Recurse -Depth 1 | ForEach-Object { Write-Host "ARSIP di repo (sebaiknya jangan di-commit): $($_.FullName)" }
