# 사용법: python3 cut.py 입력.wav 출력.wav 시작비율(0~1) 길이(초)
# 입력은 afconvert 로 만든 16kHz 모노 16bit WAV (확장형 헤더라 wave 모듈 대신 직접 파싱)
import struct, sys

RATE, BYTES = 16000, 2
src, dst, frac, secs = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])

with open(src, "rb") as f:
    if f.read(12)[8:] != b"WAVE":
        sys.exit("not a WAV file")
    while True:
        head = f.read(8)
        if len(head) < 8:
            sys.exit("no data chunk")
        cid, size = struct.unpack("<4sI", head)
        if cid == b"data":
            break
        f.seek(size + (size & 1), 1)
    start_pos = f.tell()
    n = size // BYTES
    length = min(int(secs * RATE), n)
    first = max(0, min(int(n * frac), n - length))
    f.seek(start_pos + first * BYTES)
    data = f.read(length * BYTES)

with open(dst, "wb") as o:
    o.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE")
    o.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * BYTES, BYTES, 16))
    o.write(b"data" + struct.pack("<I", len(data)) + data)
