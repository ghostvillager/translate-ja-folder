#!/usr/bin/env python3
"""カレントディレクトリの txt を日本語へ訳し、翻訳調を軽く整える。

yomiyasu と japanese-humanizer は翻訳器ではなく、AI日本語を自然にする
Agent Skill である。このスクリプトは次の2段にする。

1. 機械翻訳、または OpenAI 互換 API で日本語にする
2. 二つのスキルが共通して置いている制約（意味を変えない、足さない、
   翻訳調と比喩動詞をほどく）で後編集する

使い方:
  python translate_ja.py
  python translate_ja.py --dir . --backend google
  python translate_ja.py --backend openai --style ですます
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    "ja_out",
    ".venv",
    "venv",
}
SKIP_NAME_SUFFIXES = (".ja.txt",)

# 表層だけで安全に寄せられる翻訳調。文脈依存の比喩は LLM 側に任せる。
SURFACE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"することが可能です"), "できます"),
    (re.compile(r"することが可能である"), "できる"),
    (re.compile(r"することができます"), "できます"),
    (re.compile(r"することができる"), "できる"),
    (re.compile(r"を行うこと"), "すること"),
    (re.compile(r"検討を行う"), "検討する"),
    (re.compile(r"実施を行う"), "実施する"),
    (re.compile(r"確認を行う"), "確認する"),
    (re.compile(r"活用することによって"), "使えば"),
    (re.compile(r"([ぁ-んァ-ン一-鿿])\s+([A-Za-z])"), r"\1\2"),
    (re.compile(r"([A-Za-z0-9])\s+([ぁ-んァ-ン一-鿿])"), r"\1\2"),
]

FENCE = re.compile(r"(```.*?```|`[^`\n]+`)", re.DOTALL)
URL = re.compile(r"https?://\S+")


def japanese_ratio(text: str) -> float:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 1.0
    jp = sum(1 for c in chars if "\u3040" <= c <= "\u30ff" or "\u4e00" <= c <= "\u9fff")
    return jp / len(chars)


def protect(text: str) -> tuple[str, dict[str, str]]:
    slots: dict[str, str] = {}

    def stash(match: re.Match[str]) -> str:
        key = f"__KEEP{len(slots)}__"
        slots[key] = match.group(0)
        return key

    guarded = FENCE.sub(stash, text)
    guarded = URL.sub(stash, guarded)
    return guarded, slots


def restore(text: str, slots: dict[str, str]) -> str:
    for key, value in slots.items():
        text = text.replace(key, value)
    return text


def surface_humanize(text: str) -> str:
    guarded, slots = protect(text)
    for pattern, repl in SURFACE_RULES:
        guarded = pattern.sub(repl, guarded)
    guarded = re.sub(r"[ \t]+\n", "\n", guarded)
    guarded = re.sub(r"\n{3,}", "\n\n", guarded)
    return restore(guarded, slots).strip() + "\n"


def chunk_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    blocks = re.split(r"(\n\s*\n)", text)
    for block in blocks:
        if size + len(block) > limit and buf:
            parts.append("".join(buf))
            buf = [block]
            size = len(block)
        else:
            buf.append(block)
            size += len(block)
    if buf:
        parts.append("".join(buf))
    fixed: list[str] = []
    for part in parts:
        if len(part) <= limit:
            fixed.append(part)
            continue
        sentence = re.split(r"(?<=[。！？.!?])\s*", part)
        cur = ""
        for sent in sentence:
            if cur and len(cur) + len(sent) > limit:
                fixed.append(cur)
                cur = sent
            else:
                cur += sent
        if cur:
            fixed.append(cur)
    return fixed


def translate_google(text: str, source: str) -> str:
    from deep_translator import GoogleTranslator

    translator = GoogleTranslator(source=source, target="ja")
    chunks = chunk_text(text, 4500)
    out = []
    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            out.append(chunk)
            continue
        out.append(translator.translate(chunk))
        if i + 1 < len(chunks):
            time.sleep(0.4)
    return "".join(out)


def translate_mymemory(text: str, source: str) -> str:
    from deep_translator import MyMemoryTranslator

    src = "en-GB" if source in {"auto", "en"} else source
    translator = MyMemoryTranslator(source=src, target="ja-JP")
    chunks = chunk_text(text, 450)
    out = []
    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            out.append(chunk)
            continue
        out.append(translator.translate(chunk))
        if i + 1 < len(chunks):
            time.sleep(0.3)
    return "".join(out)


def openai_chat(messages: list[dict[str, str]], timeout: int) -> str:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("XAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY または XAI_API_KEY が必要です。")
    base = os.environ.get("OPENAI_BASE_URL") or os.environ.get("XAI_BASE_URL") or "https://api.openai.com/v1"
    model = os.environ.get("OPENAI_MODEL") or os.environ.get("XAI_MODEL") or "gpt-4.1-mini"
    url = base.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {"model": model, "temperature": 0.2, "messages": messages},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"API error {exc.code}: {detail[:500]}") from exc
    return payload["choices"][0]["message"]["content"].strip()


def load_postedit() -> str:
    path = Path(__file__).with_name("prompts") / "postedit.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "意味を変えず、翻訳調だけを自然な日本語にする。"


def translate_openai(text: str, style: str, timeout: int) -> str:
    guide = load_postedit()
    chunks = chunk_text(text, 6000)
    out = []
    for chunk in chunks:
        if not chunk.strip():
            out.append(chunk)
            continue
        messages = [
            {
                "role": "system",
                "content": (
                    "あなたは英日などの翻訳者であり、訳した後にだけ推敲する。"
                    "yomiyasu と japanese-humanizer の方針に従う。"
                    "検出回避はしない。原文にない情報は足さない。\n\n" + guide
                ),
            },
            {
                "role": "user",
                "content": (
                    f"文体: {style}\n"
                    "次の本文を日本語に訳し、翻訳調とAI特有の比喩だけを整えて返す。"
                    "前置き、解説、箇条書きの追加はしない。本文だけ返す。\n\n"
                    + chunk
                ),
            },
        ]
        out.append(openai_chat(messages, timeout))
    return "\n\n".join(part.strip() for part in out if part.strip())


def humanize_openai(text: str, style: str, timeout: int) -> str:
    guide = load_postedit()
    chunks = chunk_text(text, 6000)
    out = []
    for chunk in chunks:
        if not chunk.strip():
            out.append(chunk)
            continue
        messages = [
            {
                "role": "system",
                "content": "日本語の後編集者。意味、数値、固有名詞、否定、条件を保つ。\n\n" + guide,
            },
            {
                "role": "user",
                "content": (
                    f"文体: {style}\n"
                    "次の日本語を、意味を変えずに自然な日本語へ整える。本文だけ返す。\n\n" + chunk
                ),
            },
        ]
        out.append(openai_chat(messages, timeout))
    return "\n\n".join(part.strip() for part in out if part.strip())


def iter_txt(root: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.txt" if recursive else "*.txt"
    files = []
    for path in sorted(root.glob(pattern)):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.name.endswith(SKIP_NAME_SUFFIXES):
            continue
        if path.name.endswith(".raw.ja.txt"):
            continue
        files.append(path)
    return files


def translate_file(path: Path, backend: str, source: str, style: str, timeout: int, humanize: str) -> str:
    raw = path.read_text(encoding="utf-8")
    if japanese_ratio(raw) >= 0.6:
        translated = raw
    elif backend == "google":
        translated = translate_google(raw, source)
    elif backend == "mymemory":
        translated = translate_mymemory(raw, source)
    elif backend == "openai":
        translated = translate_openai(raw, style, timeout)
    else:
        raise SystemExit(f"unknown backend: {backend}")

    if humanize == "rules":
        return surface_humanize(translated)
    if humanize == "openai":
        return surface_humanize(humanize_openai(translated, style, timeout))
    if humanize == "off":
        return translated if translated.endswith("\n") else translated + "\n"
    raise SystemExit(f"unknown humanize mode: {humanize}")


def main() -> int:
    parser = argparse.ArgumentParser(description="フォルダ内の txt を日本語へ訳す")
    parser.add_argument("--dir", default=".", help="対象フォルダ。既定はカレント")
    parser.add_argument("--backend", choices=["google", "mymemory", "openai"], default="google")
    parser.add_argument("--source", default="auto", help="翻訳元言語。google は auto 可")
    parser.add_argument("--style", default="ですます", help="ですます / である / 原文に合わせる")
    parser.add_argument("--humanize", choices=["rules", "openai", "off"], default="rules")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--out-dir", default="", help="出力先。空なら各ファイルの隣に .ja.txt")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.dir).resolve()
    if not root.is_dir():
        print(f"フォルダがありません: {root}", file=sys.stderr)
        return 2
    files = iter_txt(root, args.recursive)
    if not files:
        print(f"txt がありません: {root}")
        return 1
    out_dir = Path(args.out_dir).resolve() if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    print(f"対象 {len(files)} 件 / backend={args.backend} / humanize={args.humanize}")
    for path in files:
        rel = path.relative_to(root)
        dest = (out_dir / rel).with_suffix(".ja.txt") if out_dir else path.with_name(path.stem + ".ja.txt")
        print(f"- {rel} -> {dest.name}")
        if args.dry_run:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = translate_file(path, args.backend, args.source, args.style, args.timeout, args.humanize)
        dest.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
