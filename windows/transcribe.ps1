# 사용법: transcribe.ps1 -Inbox <감시 폴더> [-Watch]
# 감시 폴더에 들어온 영상/음성 파일을 텍스트(.txt)로 변환한다 (Windows 버전).
# - 같은 이름의 .txt 가 이미 있으면 건너뜀
# - 한국어/영어 자동 판별 (영상 25/50/75% 지점 다수결)
# - 엔진: whisper.cpp + Silero VAD, 오디오 추출은 ffmpeg (설정 근거: benchmark/RESULTS.md)
# - -Watch: 10초마다 폴더를 확인하며 계속 실행 (시작 프로그램에서 이 모드로 실행됨)
param(
  [Parameter(Mandatory = $true)][string]$Inbox,
  [switch]$Watch
)
$ErrorActionPreference = 'Continue'
# whisper/ffmpeg 출력(UTF-8)을 깨지지 않게 읽기 위함
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

# install.ps1 과 같은 규칙으로 데이터 폴더 결정 (whisper.cpp 가 한글 경로를 못 열 수 있어 ASCII 경로만 사용)
$Base = Join-Path $env:LOCALAPPDATA 'lecture-transcriber'
if ($Base -match '[^\x00-\x7F]') { $Base = Join-Path $env:PUBLIC 'lecture-transcriber' }
$Config  = Get-Content (Join-Path $Base 'config.json') -Raw | ConvertFrom-Json
$Whisper = $Config.whisper
$Ffmpeg  = $Config.ffmpeg
$ModelKo = [IO.Path]::Combine($Base, 'models', 'ggml-large-v3-turbo.bin')
$ModelEn = [IO.Path]::Combine($Base, 'models', $Config.englishModel)
$Vad     = [IO.Path]::Combine($Base, 'models', 'ggml-silero-v5.1.2.bin')
# VAD 민감도 0.35 / 앞뒤 여유 200ms / 최소 침묵 300ms — 기본값(0.5/30ms/100ms)은 말소리 일부를 잘라냄
$VadArgs = @('--vad', '-vm', $Vad, '-vt', '0.35', '-vp', '200', '-vsd', '300')
$LogFile = Join-Path $Base 'transcribe.log'
$Work    = Join-Path $Base 'work'
$Threads = [string][Environment]::ProcessorCount
New-Item -ItemType Directory -Force -Path $Work | Out-Null

function Log([string]$msg) {
  Add-Content -Path $LogFile -Encoding UTF8 -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
}

function Notify([string]$msg) {
  try {
    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $t = $xml.GetElementsByTagName('text')
    [void]$t.Item(0).AppendChild($xml.CreateTextNode('Lecture Transcriber'))
    [void]$t.Item(1).AppendChild($xml.CreateTextNode($msg))
    $app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
  } catch { }
}

# 외부 프로그램 실행. 출력은 $script:out 과 로그에 남기고, 성공 여부만 반환
function Run([string]$exe, [string[]]$argv) {
  $script:out = @(& $exe @argv 2>&1 | ForEach-Object { "$_" })
  Add-Content -Path $LogFile -Encoding UTF8 -Value $script:out
  return ($LASTEXITCODE -eq 0)
}

# 복사/다운로드가 끝날 때까지(파일 크기가 변하지 않을 때까지) 대기
function Wait-Stable([string]$path) {
  $prev = -1
  while ($true) {
    $item = Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
    if (-not $item) { return $false }
    if ($item.Length -eq $prev -and $item.Length -gt 0) { return $true }
    $prev = $item.Length
    Start-Sleep -Seconds 3
  }
}

# 영상 25/50/75% 지점에서 30초씩 잘라 언어 판별 → 2곳 이상 영어면 en, 아니면 ko
function Detect-Lang([string]$wav, [double]$dur) {
  $clip = Join-Path $Work 'clip.wav'
  $en = 0
  foreach ($fr in 0.25, 0.5, 0.75) {
    $ss = [math]::Max(0, [math]::Min([math]::Floor($dur * $fr), $dur - 30))
    Remove-Item -LiteralPath $clip -ErrorAction SilentlyContinue
    if (-not (Run $Ffmpeg @('-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                           '-ss', "$ss", '-t', '30', '-i', $wav, $clip))) { continue }
    [void](Run $Whisper (@('-m', $ModelKo, '-l', 'auto', '-dl', '-t', $Threads, '-f', $clip) + $VadArgs))
    $m = $script:out | Select-String 'auto-detected language: ([a-z]+)' | Select-Object -First 1
    $lang = if ($m) { $m.Matches[0].Groups[1].Value } else { '?' }
    Log "  언어 판별 ${fr}: $lang"
    if ($lang -eq 'en') { $en++ }
  }
  Remove-Item -LiteralPath $clip -ErrorAction SilentlyContinue
  if ($en -ge 2) { 'en' } else { 'ko' }
}

function Transcribe([string]$src) {
  $name = [IO.Path]::GetFileName($src)
  $txt = [IO.Path]::ChangeExtension($src, '.txt')
  $wav = Join-Path $Work 'audio.wav'
  $outBase = Join-Path $Work 'out'
  Log "시작: $name"
  $start = Get-Date

  # 1) 오디오 추출 (16kHz 모노 — Whisper 입력 형식)
  Remove-Item -LiteralPath $wav -ErrorAction SilentlyContinue
  if (-not (Run $Ffmpeg @('-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', $src,
                         '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', $wav)) -or
      -not (Test-Path -LiteralPath $wav)) {
    Log "실패(오디오 추출 — 소리 트랙이 없거나 손상): $name"
    Notify "실패: $name — 소리 트랙을 읽을 수 없음"
    return $false
  }

  # 2) 작게 녹음된 파일(최대 음량 -10 dB 미만)은 -1 dB 까지 키움 (최대 +40 dB)
  #    VAD 가 작은 목소리를 침묵으로 판단해 버리는 것을 막기 위함
  [void](Run $Ffmpeg @('-nostdin', '-hide_banner', '-nostats', '-i', $wav, '-af', 'volumedetect', '-f', 'null', '-'))
  $m = $script:out | Select-String 'max_volume: (-?[\d.]+) dB' | Select-Object -First 1
  if ($m) {
    $peak = [double]$m.Matches[0].Groups[1].Value
    if ($peak -lt -10) {
      $gain = [math]::Min(-1 - $peak, 40)
      $lev = Join-Path $Work 'level.wav'
      if (Run $Ffmpeg @('-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', $wav,
                        '-af', "volume=${gain}dB", '-c:a', 'pcm_s16le', $lev)) {
        Move-Item -LiteralPath $lev -Destination $wav -Force
        Log ("  음량 보정: +{0:N1} dB" -f $gain)
      }
    }
  }

  # 3) 언어 판별 후 모델 선택
  $dur = ((Get-Item -LiteralPath $wav).Length - 44) / 32000
  $lang = Detect-Lang $wav $dur
  if ($lang -eq 'en') { $model = $ModelEn; $label = '영어' } else { $model = $ModelKo; $label = '한국어' }
  Log "  언어: $label / 모델: $([IO.Path]::GetFileName($model))"
  Notify "변환 시작 ($label): $name"

  # 4) 음성 인식 (-mc 0: 앞 문장 문맥을 안 넘겨서 같은 문장 반복 환각 방지)
  Remove-Item -LiteralPath "$outBase.txt" -ErrorAction SilentlyContinue
  if (-not (Run $Whisper (@('-m', $model, '-l', $lang, '-t', $Threads, '-mc', '0', '-sns',
                           '-otxt', '-of', $outBase, '-f', $wav, '-np') + $VadArgs))) {
    Log "실패(음성 인식): $name"
    Notify "실패: $name"
    return $false
  }

  # 5) 앞뒤 공백 정리 후 저장 (메모장 호환을 위해 UTF-8 BOM)
  $lines = @(Get-Content -LiteralPath "$outBase.txt" -Encoding UTF8 | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  [IO.File]::WriteAllLines($txt, [string[]]$lines, (New-Object Text.UTF8Encoding($true)))
  Remove-Item -LiteralPath $wav, "$outBase.txt" -ErrorAction SilentlyContinue

  $secs = [int]((Get-Date) - $start).TotalSeconds
  Log "완료: $([IO.Path]::GetFileName($txt)) (${secs}초)"
  Notify ("완료 ({0}): {1} ({2}분 {3}초)" -f $label, [IO.Path]::GetFileName($txt), [math]::Floor($secs / 60), ($secs % 60))
  # 완료되면 텍스트 파일을 바로 열어줌
  Start-Process notepad.exe -ArgumentList "`"$txt`"" -ErrorAction SilentlyContinue
  return $true
}

# 동시에 여러 개 실행되지 않도록 잠금
$mutex = New-Object Threading.Mutex($false, 'Local\lecture-transcriber')
if (-not $mutex.WaitOne(0)) { exit }

do {
  Get-ChildItem -LiteralPath $Inbox -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in '.mp4', '.m4a', '.mov' } |
    ForEach-Object {
      $f = $_.FullName
      if (Test-Path -LiteralPath ([IO.Path]::ChangeExtension($f, '.txt'))) { return }
      if (Test-Path -LiteralPath "$f.failed") { return }
      if (-not (Wait-Stable $f)) { return }
      if (-not (Transcribe $f)) { [IO.File]::WriteAllText("$f.failed", '') }
    }
  if ($Watch) { Start-Sleep -Seconds 10 }
} while ($Watch)
