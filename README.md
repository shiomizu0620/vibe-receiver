# vibe-receiver — VibeCode 受信側（PC / Python）

スマホの振動から id(8bit) を復調し、Supabase で URL に逆引きしてブラウザで開く。
ラップトップにスマホを直置きし、内蔵マイクで振動を拾うのが本線。

- プロトコル定数の唯一の正: `PROTOCOL.md`（v1.0確定・送信側リポジトリ Vibes と同一内容）
- 設計方針: `CLAUDE.md`（チャンネル・プラグイン構造／decode 以降はチャンネルを知らない）
- タスク: `docs/ISSUES_receiver.md`（本線 R系・拡張 E系）／全体は `docs/ISSUES.md`

## できること

- **id 方式（本線・marker=0）**: 振動 → パルス列 → id 8bit → Supabase 逆引き → URL オープン
- **X1 / URL 直接モード（marker=1・PROTOCOL v1.1 *実験的*）**: URL 文字列を直接符号化して送受信。
  checksum OK ならその URL を開き、**NG なら「運命のサイト🎲」をランダムで開く**（手動演奏のミスがネタになる）。
- **チャンネル切替**: `mic`（本線・内蔵マイク）/ `replay`（マイク無しでパルス列を再生＝デモ・テスト用）
- **受信ループ型**: 1 メッセージで終わらず連続して待ち受ける。復号失敗は落とさずスキップして次へ。
- **ブラウザ演出**: `--serve` で WebSocket 配信し、`web/index.html` のオシロスコープ＆ビット演出をリアルタイム駆動。
- **オフライン保険**: `--offline` で Supabase に繋がずローカル固定辞書で逆引き（会場 Wi-Fi 死亡時のデモ保険）。

## セットアップ

```bash
python -m venv .venv
.venv\Scripts\activate                 # Windows（PowerShell は .venv\Scripts\Activate.ps1）
pip install -r requirements.txt
```

Supabase 逆引きを使う場合は `.env` に接続情報を置く（`.env.example` 参照・コミット禁止）:

```ini
SUPABASE_URL=...
SUPABASE_ANON_KEY=...        # anon key のみ。service_role key は使わない・置かない
```

`.env` が無くても `--offline` ならローカル辞書で動く（mic を使わない限り `sounddevice` も不要）。

## 実行

```bash
# マイク無しで通し確認（既定 replay: id=42,7 を連続受信 → 逆引き → 演出）
python -m src.main --channel replay

# X1（URL 直接モード）のデモ
python -m src.main --channel replay --x1-url github.com
python -m src.main --channel replay --x1-url github.com --x1-corrupt 3   # checksum NG → 運命のサイト🎲

# 内蔵マイクで実機スマホの振動を受信（閾値・デバイス既定は config の R8 確定値）
python -m src.main --channel mic

# ブラウザ演出（オシロ＆ビット表示）を出しながら受信
python -m src.main --channel mic --serve

# Supabase に繋がずローカル辞書で逆引き（デモ保険）
python -m src.main --channel replay --offline

# 復号・DSP・演出などのテスト（マイク不要・58本）
pytest
```

主なオプション: `--ids 42,7`（replay の id 列）/ `--device N`・`--threshold V`（mic）/
`--no-open`（URL を表示するだけで開かない）/ `--serve`・`--ws-port`・`--no-browser`（ブラウザ演出）。
全オプションは `python -m src.main -h`。

## 構成

```text
src/
  config.py        PROTOCOL.md 由来の定数 + 受信側の運用定数（mic 既定値・X1 テーブル・WS 設定・FUN_SITES）
  decode.py        ★パルス列 → プリアンブル → marker で分岐（id 8bit / X1 可変長）。純粋関数
  x1.py            X1 のビット⇔フィールド変換・6bit 文字テーブル・CRC-8。マイク/IO 非依存
  channels/
    base.py        Channel 抽象 + PulseEvent(start_ms, duration_ms)
    mic.py         本線: 内蔵マイク（sounddevice → dsp → ON/OFF → PulseEvent、level 配信も）
    replay.py      パルス列を時間どおり再生するダミー（センサー無しで UI/結合テスト）
  dsp.py           共通 DSP 部品（バンドパス・包絡線・閾値 ON/OFF）。純粋関数
  lookup.py        Supabase 逆引き（id → url、anon key・SELECT のみ）+ --offline 辞書
  display.py       ターミナル演出（rich: ビット形成 → URL タイプ風 → オープン）。WS 配信フックも
  ws_server.py     WebSocket 配信サーバー（受信を一切ブロックしない別スレッド）
  main.py          パイプライン結合・受信ループ（--channel / --serve / --offline）
web/index.html     ブラウザ演出（オシロスコープ＋ビット演出。--serve から WS で駆動）
tests/             decode / dsp / channels / display / lookup / x1 / ws_server / main_replay
```

## 復調規則（PROTOCOL.md より）

1. プリアンブル（700ms 級 ON ×2）検出
2. ON パルス長 <300ms→0 / ≥300ms→1（MSB first）
3. モードマーカー 1bit（0=id モード／1=X1）→ id は 8bit 固定長、X1 は可変長ペイロード

※ **0/1 判定は ON パルス長のみ（境界 300ms）。gap の揺れは判定に使わない**（手動演奏対応の核心）。

## 開発の進め方

`docs/ISSUES_receiver.md` を番号順に 1 つずつ。1 issue = 1 ブランチ = 1 PR、`main` への直 push 禁止。
ブランチ名は `<type>/<issue番号>-<内容>`（例 `feat/R8-mic-threshold`）、PR タイトルは `[R8] 内容`。
拡張（ピエゾ/机越し/IMU/AND 判定）は E 系として独立 issue 化済み。詳細は `CLAUDE.md`。
