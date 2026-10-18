# Whisper 출력(30초 단위로 끊긴 줄)을 읽기 좋게 정리: 한 줄에 한 문장, 영어는 문장 첫 글자 대문자
#   python3 textfmt.py 입력.txt 출력.txt 언어(ko|en)
import re
import sys

# 마침표가 있어도 문장 끝이 아닌 영어 약어
ABBREV = {"mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "e.g", "i.e", "jr", "sr", "no", "fig", "u.s"}


def sentences(text):
    out, start = [], 0
    for m in re.finditer(r"[.?!]+[\"')\]]*\s+", text):
        word = text[start:m.start()].rsplit(None, 1)[-1].lower() if text[start:m.start()].strip() else ""
        if word.rstrip(".") in ABBREV:
            continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    if text[start:].strip():
        out.append(text[start:].strip())
    return out


def main(src, dst, lang):
    with open(src, encoding="utf-8") as f:
        text = " ".join(line.strip() for line in f if line.strip())
    lines = sentences(re.sub(r"\s+", " ", text))
    if lang == "en":
        lines = [re.sub(r"^([\"'(]*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s) for s in lines]
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:4])
