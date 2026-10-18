# afconvert 로 만든 16kHz 모노 16bit WAV 를 다루는 작은 도구 (맥 기본 python3 만 사용)
#   python3 wavtool.py cut   입력.wav 출력.wav 시작비율(0~1) 길이(초)
#   python3 wavtool.py level 입력.wav 출력.wav
# afconvert 는 확장형(EXTENSIBLE) 헤더를 써서 wave 모듈이 못 읽으므로 직접 파싱한다.
import audioop
import struct
import sys

RATE, WIDTH = 16000, 2


def read_pcm(path):
    with open(path, "rb") as f:
        if f.read(12)[8:] != b"WAVE":
            sys.exit("not a WAV file")
        while True:
            head = f.read(8)
            if len(head) < 8:
                sys.exit("no data chunk")
            cid, size = struct.unpack("<4sI", head)
            if cid == b"data":
                return f.read(size)
            f.seek(size + (size & 1), 1)


def write_pcm(path, data):
    with open(path, "wb") as o:
        o.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE")
        o.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * WIDTH, WIDTH, 16))
        o.write(b"data" + struct.pack("<I", len(data)) + data)


def cut(src, dst, frac, secs):
    data = read_pcm(src)
    n = len(data) // WIDTH
    length = min(int(float(secs) * RATE), n)
    first = max(0, min(int(n * float(frac)), n - length))
    write_pcm(dst, data[first * WIDTH:(first + length) * WIDTH])


def level(src, dst):
    """작게 녹음된 파일(최대 음량 -10 dBFS 미만)을 최대 -1 dBFS 까지 키움 (최대 +40 dB).
    VAD 가 작은 목소리를 침묵으로 판단해 버리는 것을 막기 위함."""
    data = read_pcm(src)
    peak = audioop.max(data, WIDTH) or 1
    gain = min(32767 * 10 ** (-1 / 20) / peak, 100.0)
    if peak < 32767 * 10 ** (-10 / 20):
        data = audioop.mul(data, WIDTH, gain)
        print(f"level: +{20 * __import__('math').log10(gain):.1f} dB")
    write_pcm(dst, data)


if __name__ == "__main__":
    {"cut": cut, "level": level}[sys.argv[1]](*sys.argv[2:])
