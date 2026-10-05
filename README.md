# フォルダ内 txt を日本語にする

[yomiyasu](https://github.com/nanaism/yomiyasu) と [japanese-humanizer](https://github.com/geonwoo-jeong/japanese-humanizer) は翻訳器ではない。どちらも、すでに日本語になった文章のAI臭さ、翻訳調、比喩動詞、曖昧な主述を、意味を変えずに整える Agent Skill である。ライセンスはいずれも MIT。

このツールはその役割分担をそのまま使う。

1. カレントフォルダの `*.txt` を日本語へ訳す
2. 二つのスキルが共通して置いている制約で後編集する

後編集の要約は `prompts/postedit.md` にある。スキル本文そのものは同梱していない。

既定の翻訳は無料の Google 翻訳（`deep-translator`）。API キーは不要。

## 使い方

```bash
pip install -r requirements.txt
python translate_ja.py
```

カレントの `note.txt` は `note.ja.txt` になる。すでに日本語が多いファイルは翻訳せず、表層の後編集だけかける。`*.ja.txt` は再翻訳しない。

```bash
python translate_ja.py --dir . --backend google --humanize rules
python translate_ja.py --recursive --out-dir ./ja_out
python translate_ja.py --backend openai --humanize openai --style である
python translate_ja.py --dry-run
```

## バックエンド

| 値 | 中身 | 必要なもの |
| --- | --- | --- |
| `google` | Google 翻訳。無料、キー不要。公開エンドポイントの制限で失敗することがある | ネット |
| `mymemory` | MyMemory。短い文向け。無料枠あり | ネット。`--source en` を想定 |
| `openai` | 翻訳と自然化を同時に行う。有料API | `OPENAI_API_KEY`。任意で `OPENAI_BASE_URL` と `OPENAI_MODEL` |

xAI を使うときは `XAI_API_KEY` と `OPENAI_BASE_URL=https://api.x.ai/v1` を置く。`XAI_API_KEY` だけでも読む。

`--humanize openai` は機械翻訳のあと、同じ API でもう一度だけ整える。意味、数値、固有名詞、否定、条件は変えない、という指示を `prompts/postedit.md` から渡す。

## 二つのスキルをそのまま使う場合

品質を最優先するなら、このスクリプトで粗い訳を作り、Codex や Claude Code でスキルを当てる方がよい。スキル同士は指示がぶつかるので、yomiyasu の注意どおり同時には有効にしない。

```bash
npx skills add nanaism/yomiyasu
npx skills add geonwoo-jeong/japanese-humanizer
```

## 制約

- 表層ルールは「することができる」「検討を行う」、和文と英単語の間の半角空白だけを直す。比喩の言い換えは文脈が必要なので、ルールでは触らない。
- Google 翻訳は公開エンドポイントの制限で失敗することがある。そのときは `--backend mymemory` か `--backend openai` にする。
- 法務、医療、契約は、この後編集だけでは確定稿にしない。
