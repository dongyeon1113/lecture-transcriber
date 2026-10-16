# 설치: ffmpeg + whisper.cpp 설치 → 모델 다운로드 → 시작 프로그램에 폴더 감시 등록
# 사용법: powershell -ExecutionPolicy Bypass -File windows\install.ps1 [-Inbox <감시 폴더>]
#         (기본 감시 폴더: %USERPROFILE%\Lecture Inbox)
param([string]$Inbox = (Join-Path $HOME 'Lecture Inbox'))
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# whisper.cpp 공식 Windows 빌드 (고정 버전 + SHA-256)
$Release = 'b5454'
$Builds = @{
  cuda  = @{ name = 'whisper-bin-win-cuda-12.4.0-x64.zip'; sha = 'afef0b881c500958921c3f5523b50e59ee2ec9b6f5cbd25b324c51ed308a957a' }
  cpu   = @{ name = 'whisper-bin-x64.zip';                 sha = '6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb' }
  arm64 = @{ name = 'whisper-bin-win-cpu-arm64.zip';       sha = '28c37e7b598c3d9bbfef94f3bd67f2ee6f12b7c86f3da5edcf5e4308d615ff6d' }
}
$HF = 'https://huggingface.co'
$Models = @{
  'ggml-large-v3-turbo.bin' = @("$HF/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin", '1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69')
  'ggml-large-v3.bin'       = @("$HF/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin",       '64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2')
  'ggml-silero-v5.1.2.bin'  = @("$HF/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin",    '29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf')
}

# 데이터 폴더 (whisper.cpp 가 한글 경로를 못 열 수 있어 ASCII 경로만 사용)
$Base = Join-Path $env:LOCALAPPDATA 'lecture-transcriber'
if ($Base -match '[^\x00-\x7F]') { $Base = Join-Path $env:PUBLIC 'lecture-transcriber' }
New-Item -ItemType Directory -Force -Path "$Base\models", "$Base\bin" | Out-Null

# 끊겨도 이어받기, 받은 뒤 SHA-256 검증 (curl.exe 는 Windows 10 이상에 기본 포함)
function Download([string]$url, [string]$dest, [string]$sha) {
  $file = Split-Path $dest -Leaf
  if (Test-Path $dest) { Write-Host "  ok  $file (already downloaded)"; return }
  Write-Host "  ->  $file"
  $part = "$dest.part"
  for ($i = 0; $i -lt 30; $i++) {
    & curl.exe -L --fail --progress-bar -C - --speed-limit 10000 --speed-time 60 -o $part $url
    if ($LASTEXITCODE -eq 0) { break }
    Write-Host '      retrying...'; Start-Sleep -Seconds 5
  }
  if ((Get-FileHash $part -Algorithm SHA256).Hash.ToLower() -ne $sha) {
    Remove-Item $part -Force
    throw "$file : checksum mismatch. Run install.ps1 again."
  }
  Move-Item $part $dest -Force
}

function Install-Whisper([string]$kind) {
  $b = $Builds[$kind]
  $dir = Join-Path $Base "bin\$kind"
  if (-not (Test-Path $dir)) {
    $zip = Join-Path $Base "bin\$($b.name)"
    Download "https://github.com/ggml-org/whisper.cpp/releases/download/$Release/$($b.name)" $zip $b.sha
    Expand-Archive -Path $zip -DestinationPath $dir -Force
    Remove-Item $zip -Force
  }
  return (Get-ChildItem -Path $dir -Recurse -Filter 'whisper-cli.exe' | Select-Object -First 1).FullName
}

Write-Host '==> ffmpeg'
$ffmpeg = (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue).Source
if (-not $ffmpeg) {
  if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
    throw 'winget not found. Install ffmpeg manually (https://www.gyan.dev/ffmpeg/builds/) and add it to PATH.'
  }
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
  $ffmpeg = (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue).Source
  if (-not $ffmpeg) { $ffmpeg = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\ffmpeg.exe' }
  if (-not (Test-Path $ffmpeg)) { throw 'ffmpeg install failed. Open a new terminal and run install.ps1 again.' }
}
Write-Host "  $ffmpeg"

Write-Host '==> Models'
Download $Models['ggml-large-v3-turbo.bin'][0] "$Base\models\ggml-large-v3-turbo.bin" $Models['ggml-large-v3-turbo.bin'][1]
Download $Models['ggml-silero-v5.1.2.bin'][0]  "$Base\models\ggml-silero-v5.1.2.bin"  $Models['ggml-silero-v5.1.2.bin'][1]

Write-Host '==> whisper.cpp'
$hasNvidia = [bool](Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA' })
if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
  $kind = 'arm64'
} elseif ($hasNvidia) {
  $kind = 'cuda'
} else {
  $kind = 'cpu'
}
$whisper = Install-Whisper $kind

# CUDA 빌드가 실제로 도는지 2초짜리 무음으로 확인, 안 되면 CPU 빌드로 대체
if ($kind -eq 'cuda') {
  $test = Join-Path $Base 'gpu-test.wav'
  & $ffmpeg -nostdin -hide_banner -loglevel error -y -f lavfi -i 'anullsrc=r=16000:cl=mono' -t 2 -c:a pcm_s16le $test
  # whisper 는 로그를 stderr 로 내보내므로, 'Stop' 상태에서는 그게 오류로 처리되지 않게 잠시 완화
  $ErrorActionPreference = 'Continue'
  & $whisper -m "$Base\models\ggml-large-v3-turbo.bin" -f $test -np 2>&1 | Out-Null
  $ok = ($LASTEXITCODE -eq 0)
  $ErrorActionPreference = 'Stop'
  Remove-Item $test -ErrorAction SilentlyContinue
  if (-not $ok) {
    Write-Host '  CUDA build failed to run (update your NVIDIA driver for GPU speed). Using CPU build.'
    $kind = 'cpu'
    $whisper = Install-Whisper $kind
  }
}
Write-Host "  $kind build: $whisper"

# 영어 최고정확도 모델(large-v3)은 GPU 에서만 실용적인 속도라 GPU 일 때만 사용
if ($kind -eq 'cuda') {
  Download $Models['ggml-large-v3.bin'][0] "$Base\models\ggml-large-v3.bin" $Models['ggml-large-v3.bin'][1]
  $englishModel = 'ggml-large-v3.bin'
} else {
  $englishModel = 'ggml-large-v3-turbo.bin'
}

@{ whisper = $whisper; ffmpeg = $ffmpeg; englishModel = $englishModel; build = $kind } |
  ConvertTo-Json | Set-Content -Path "$Base\config.json" -Encoding UTF8

Write-Host '==> Registering folder watcher (runs at logon)'
New-Item -ItemType Directory -Force -Path $Inbox | Out-Null
$Inbox = (Resolve-Path -LiteralPath $Inbox).Path
& "$PSScriptRoot\uninstall.ps1" -Quiet
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$psArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSScriptRoot\transcribe.ps1`" -Inbox `"$Inbox`" -Watch"
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Lecture Transcriber.lnk'))
$lnk.TargetPath = $ps
$lnk.Arguments = $psArgs
$lnk.WindowStyle = 7
$lnk.Save()
Start-Process -FilePath $ps -ArgumentList $psArgs -WindowStyle Hidden

Write-Host ''
Write-Host 'Done. Drop .mp4 / .m4a / .mov files into:'
Write-Host "  $Inbox"
Invoke-Item $Inbox
