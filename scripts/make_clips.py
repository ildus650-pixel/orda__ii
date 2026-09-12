#!/usr/bin/env python3
"""Нарезка длинного видео на вертикальные клипы 9:16 с вожжёнными субтитрами.

Путь: faster-whisper (слова с таймкодами) -> выбор моментов -> ffmpeg (кроп 9:16 + burn-in SRT).

Пример:
    python scripts/make_clips.py --src work/source.mp4 --out clips --count 3 --title clip
"""
import argparse
import json
import os
import subprocess
import sys


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def srt_ts(t):
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def transcribe(src, model_size, lang):
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        src, language=lang, word_timestamps=True, vad_filter=True,
        beam_size=1, condition_on_previous_text=False,
    )
    out = []
    for seg in segments:
        words = [
            {"s": w.start, "e": w.end, "w": (w.word or "").strip()}
            for w in (seg.words or []) if w.start is not None
        ]
        out.append({"s": seg.start, "e": seg.end, "text": (seg.text or "").strip(), "words": words})
    return out, getattr(info, "language", lang)


def pick_segments(segs, count, min_len=12.0, max_len=60.0, target=30.0):
    """Грубая эвристика: склеиваем соседние сегменты до target секунд,
    сортируем по плотности слов (речь «на единицу времени») и берём лучшие."""
    blocks, cur = [], None
    for s in segs:
        if cur is None:
            cur = {"s": s["s"], "e": s["e"], "words": list(s["words"]), "text": s["text"]}
        elif s["e"] - cur["s"] <= max_len and s["s"] - cur["e"] < 1.5:
            cur["e"] = s["e"]
            cur["words"] += s["words"]
            cur["text"] = (cur["text"] + " " + s["text"]).strip()
        else:
            blocks.append(cur)
            cur = {"s": s["s"], "e": s["e"], "words": list(s["words"]), "text": s["text"]}
    if cur:
        blocks.append(cur)

    scored = []
    for b in blocks:
        dur = max(0.1, b["e"] - b["s"])
        if dur < min_len:
            continue
        wps = len(b["words"]) / dur
        scored.append((wps, b))
    scored.sort(key=lambda x: -x[0])

    chosen, used = [], []
    for _, b in scored:
        if len(chosen) >= count:
            break
        if any(not (b["e"] < u[0] - 5 or b["s"] > u[1] + 5) for u in used):
            continue
        if b["e"] - b["s"] > target:
            b = dict(b)
            b["e"] = b["s"] + target
            b["words"] = [w for w in b["words"] if w["s"] <= b["e"]]
        chosen.append(b)
        used.append((b["s"], b["e"]))
    chosen.sort(key=lambda b: b["s"])
    return chosen


def write_srt(path, words, start, end, group=4):
    cues, cur = [], []
    for w in words:
        if w["s"] is None or w["s"] < start - 0.5 or w["e"] > end + 0.5:
            continue
        cur.append(w)
        if len(cur) >= group or w["w"].endswith((".", "!", "?", ",")):
            if cur:
                cues.append(cur)
                cur = []
    if cur:
        cues.append(cur)

    with open(path, "w", encoding="utf-8") as f:
        for i, cue in enumerate(cues, 1):
            a = max(0.0, cue[0]["s"] - start)
            b = max(a + 0.4, cue[-1]["e"] - start)
            text = " ".join(x["w"] for x in cue).strip()
            f.write(f"{i}\n{srt_ts(a)} --> {srt_ts(b)}\n{text}\n\n")
    return len(cues)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default="clips")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--title", default="clip")
    ap.add_argument("--lang", default=None, help="ru/en/... (по умолчанию — авто)")
    ap.add_argument("--model", default="small", help="tiny|base|small|medium")
    ap.add_argument("--subtitle-font", type=int, default=16)
    ap.add_argument("--no-subtitles", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.src):
        sys.exit("нет файла " + args.src)
    os.makedirs(args.out, exist_ok=True)
    os.makedirs("work", exist_ok=True)

    print("== транскрипция (faster-whisper %s) ==" % args.model, flush=True)
    segs, lang = transcribe(args.src, args.model, args.lang)
    print("сегментов:", len(segs), "| язык:", lang, flush=True)

    blocks = pick_segments(segs, args.count)
    if not blocks:
        sys.exit("не нашёл подходящих моментов (слишком короткий транскрипт?)")
    print("выбрано моментов:", len(blocks), flush=True)

    made = []
    for i, b in enumerate(blocks, 1):
        srt = os.path.join("work", "clip_%02d.srt" % i)
        n_cues = write_srt(srt, b["words"], b["s"], b["e"]) if not args.no_subtitles else 0
        out = os.path.join(args.out, "%s_%02d.mp4" % (args.title, i))
        vf = ("scale=1080:1920:force_original_aspect_ratio=increase,"
              "crop=1080:1920,setsar=1")
        if n_cues:
            style = "FontSize=%d,Alignment=2,MarginV=90,Bold=1,BorderStyle=1,Outline=2" % args.subtitle_font
            vf += ",subtitles=%s:force_style='%s'" % (srt.replace(":", "\\:"), style)
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", "%.3f" % b["s"], "-to", "%.3f" % b["e"], "-i", args.src,
             "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
             "-movflags", "+faststart", out])
        made.append({"file": out, "start": round(b["s"], 2), "end": round(b["e"], 2),
                     "cues": n_cues, "size": os.path.getsize(out)})
        print("готово:", out, flush=True)

    print(json.dumps({"lang": lang, "clips": made}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
