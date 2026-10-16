# 제거: 폴더 감시 중지 + 시작 프로그램에서 해제 (모델과 변환 결과는 남겨둠)
param([switch]$Quiet)
Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" |
  Where-Object { $_.CommandLine -like '*transcribe.ps1*-Watch*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'Lecture Transcriber.lnk') -ErrorAction SilentlyContinue
if (-not $Quiet) {
  $Base = Join-Path $env:LOCALAPPDATA 'lecture-transcriber'
  if ($Base -match '[^\x00-\x7F]') { $Base = Join-Path $env:PUBLIC 'lecture-transcriber' }
  Write-Host "Folder watcher removed. Delete $Base to free disk space."
}
