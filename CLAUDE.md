# CLAUDE.md — VibeCode 受信側（receiver）

> このリポジトリは「バイブコード」の**受信側**。スマホの振動を検知し、idを復調して Supabase で逆引きし、URLを開く。
> プロトコル定数の唯一の正は `PROTOCOL.md`（v1.0確定・送信側リポジトリ Vibes と同一内容）。**勝手に変更しない。**
> タスクは `docs/ISSUES_receiver.md`。**番号順に1つずつ消化する**（各issueが独立して完了判定できる粒度）。

## 全体像
送信側（Flutter/スマホ, リポジトリ: Vibes）が、id(8bit)をプリアンブル付き短/長振動で出す。
**手動演奏が体験の主役**（人間がボタンで打つ。各打の振動長は固定、間隔だけ揺れる）。自動演奏もある（機械精度・チューニング基準）。
受信は**ラップトップ直置き＋内蔵マイク**を本線とし、将来チャンネル（ピエゾ/机越し/IMU）を追加できる構造にする。

## 技術構成
- Python / `sounddevice`（録音）/ `numpy` `scipy`（DSP）/ `supabase`（逆引き）/ `webbrowser`（URLオープン）/ `rich`（ターミナル演出）/ `matplotlib`（デバッグ可視化）

## アーキテクチャ（最重要・拡張性の核）
**チャンネル・プラグイン構造**: センサーごとの差異は「生信号 → パルス列」の変換器（Channel）に閉じ込める。
**decode以降はチャンネルを知らない。** 新しい受信方法（ピエゾ・机越し・IMU）は Channel を1つ足すだけで対応できる。

```
src/
  config.py        PROTOCOL.md の定数（150/450/150ms, [700,200]×2, 8bit, MSB first, 境界300ms）
  channels/
    base.py        Channel 抽象: start()/stop()、PulseEvent(start_ms, duration_ms) をコールバックで流す
    mic.py         本線: 内蔵マイク（sounddevice → バンドパス → 包絡線 → ON/OFF → PulseEvent）
    piezo.py       拡張: ピエゾ/外部マイク入力（mic.py とDSP共有、デバイス指定が違うだけ）
    imu_serial.py  拡張: Arduino+IMU をUSBシリアルで（pyserial）
  dsp.py           チャンネル共通のDSP部品（バンドパス設計・包絡線・閾値ON/OFF）。純粋関数
  decode.py        ★実装済み・純粋関数。パルス列 → プリアンブル → 短/長 → モードマーカー+8bit → id
  lookup.py        Supabase逆引き（id → url）
  display.py       ターミナル演出（ビット形成表示 → URLタイプ表示 → オープン）
  debug_view.py    波形・包絡線・判定の可視化（チューニングの必需品）
  main.py          パイプライン結合: Channel選択(--channel mic 等) → decode → lookup → display
                   **受信ループ型**（連続待ち受け）。--offline でlookupをローカル辞書に切替（デモ保険）
tests/
  test_decode.py   実装済み・5本パス（手打ちパルス列、マイク不要）
  test_dsp.py      合成波形でのON/OFF検出テスト（録音不要）
```

設計ルール:
- **Channel の出力は必ず PulseEvent 列**。decode/display/lookup はどのチャンネルかを知らない。
- DSPの処理本体は `dsp.py` の純粋関数に置き、各チャンネルはそれを呼ぶ（机越し対応は主に閾値/帯域パラメータ差で済むようにする）。
- 定数は `config.py` のみ。チャンネル固有パラメータ（閾値・帯域）は各チャンネルの引数にし、ハードコードしない。
- **0/1判定はONパルス長のみ（境界300ms）。gapの揺れは判定に使わない**（手動演奏対応の核心）。
- 複数チャンネル同時利用（マイク+ピエゾのAND判定等）は将来課題。今は1チャンネル選択式でよい。

## 復調規則（PROTOCOL.md より）
1. プリアンブル（700ms級ON×2）検出 → 2. ONパルス長 <300ms→0 / ≥300ms→1（MSB first）
3. モードマーカー1bit（0=idモード）→ ペイロード8bit で完了（終端なし・固定長）

## ブランチ運用
- **ブランチ名は `<type>/<issue番号>-<内容>` 形式**（type: `feat` / `fix` / `docs` / `chore`）
  例: `feat/R2-dsp`, `fix/R4-mic-threshold`, `chore/ci`
- **1 issue = 1 ブランチ = 1 PR**。複数issueを1ブランチ/1PRにまとめない。
- **PRタイトルは `[R2] dsp実装` の形式**（`[<issue番号>] <内容>`）。
- **`main` への直push禁止**。変更は必ずPR経由でマージする。

## 環境メモ
- Windows。デバイス確認は `python -c "import sounddevice as sd; print(sd.query_devices())"`
- バンドパス帯域は送信実機の録音（Vibes側 F8 の成果物）をFFT/スペクトログラムで見て決める。
- 机越し受信は振動の減衰が大きい。まず直置きで完成させ、机越しはピエゾチャンネル＋閾値調整で挑戦する（stretch）。

## やらないこと（恒久）
- 送信側のコード（Vibesリポジトリの担当）
- PROTOCOL.md の単独変更（3人合意のみ）
