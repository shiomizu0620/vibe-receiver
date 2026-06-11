# ISSUES — receiver（番号順に1つずつ消化する）

> 各issueは「単独で完了判定できる」粒度。上から順にやれば依存が壊れない。
> R1〜R3はマイク不要（今日から可能）。R4以降で実音に触る。E系は拡張(stretch)。

---

### R1: プロジェクト起動確認
- venv作成、依存インストール（sounddevice, numpy, scipy, supabase, rich, matplotlib, pytest）
- `pytest` で既存5本（test_decode）が通ることを確認
- ✅ 完了条件: `pytest` 全パス
- 依存: なし

### R2: dsp.py — 共通DSP部品（純粋関数）
- `bandpass(signal, fs, lo, hi)` / `envelope(signal, fs)` / `to_pulses(envelope, fs, threshold)` を実装
- `to_pulses` は PulseEvent 相当の `[(start_ms, duration_ms), ...]` を返す
- `tests/test_dsp.py`: **合成波形**（正弦波バーストをnumpyで生成）でON/OFF検出をテスト。録音不要
- ✅ 完了条件: 合成した「150ms/450ms/700msバースト列」から正しいパルス列が出るテストが通る
- 依存: R1

### R3: channels/base.py — Channel抽象
- `Channel` 基底クラス: `start(on_pulse: Callable)` / `stop()`、PulseEventをコールバックで流す
- ダミーチャンネル `ReplayChannel`（パルス列を時間通り再生）も作る → 以降のUI/結合テストがセンサーなしで可能になる
- ✅ 完了条件: ReplayChannel → decode → id が通るテスト
- 依存: R2

### R4: channels/mic.py — マイクチャンネル（本線）
- sounddevice でストリーム録音 → dsp.bandpass → envelope → to_pulses → コールバック
- 帯域・閾値はコンストラクタ引数（仮値でよい。確定はR8で）
- ✅ 完了条件: 手叩き or 適当なスマホ振動で、PulseEventがリアルタイムに流れてくる
- 依存: R3

### R5: debug_view.py — 可視化
- 直近の波形・包絡線・閾値線・検出パルス・短/長判定を1画面にプロット
- ✅ 完了条件: 1回の受信について「なぜその判定になったか」が目で追える
- 依存: R4（R2の合成波形でも先行開発可）

### R6: main.py — パイプライン結合（仮想で通し）
- `--channel replay|mic` 選択 → decode → （lookupはまだスタブ: id表示のみ）
- **受信ループ型にする**: 1回受けたら終了ではなく、連続して何メッセージでも待ち受ける（デモで連続受信できる・将来の対戦モードの土台）
- ✅ 完了条件: ReplayChannelでid=42がend-to-endで表示され、続けて次のメッセージも受けられる
- 依存: R3（micはR4）

### R7: display.py — ターミナル演出
- 受信中: ビットが1つずつ並ぶ（●━…）→ id確定 → URLをタイプ風に1文字ずつ → webbrowserで開く
- rich使用。URL部分はlookupスタブ（固定辞書）でよい
- ✅ 完了条件: 演出付きでURLが開く（DBなしで）
- 依存: R6

### R8: 実音チューニング（送信実機の録音で）
- Vibes側F8の録音をFFT/スペクトログラムで解析 → モーターのピーク周波数を特定 → バンドパス帯域・閾値を確定
- ✅ 完了条件: 実機の自動演奏の録音ファイルから decode で正しいidが出る
- 依存: R4, R5, Vibes側F8

### R9: lookup.py — Supabase逆引き
- supabase-py で id→url。接続情報は .env（コミットしない）
- **`--offline` フラグでローカル固定辞書にフォールバック**できるようにする（会場Wi-Fi死亡時のデモ保険）
- ✅ 完了条件: 登録済みidを与えると実URLが返る／--offline でもURLが開く
- 依存: 共同S1（Supabaseプロジェクト）

### R10: リアルタイム通し（受信側単体の完成）
- mic → decode → lookup → display を実機スマホ直置きで通す（自動演奏）
- ✅ 完了条件: スマホの自動演奏でブラウザにURLが開く
- 依存: R7, R8, R9 → 以降はチームの J1（手動演奏含む結合）へ

---

## E系: 拡張（本線R10完了後のみ・どれも独立）

### E1: channels/piezo.py — ピエゾチャンネル
- ピエゾ素子をPCのマイク/ライン入力に接続。mic.pyとDSP共有、デバイス指定と閾値が違うだけ
- 効果: 空気音を拾わない＝会場ノイズ耐性、「機械振動を直接測ってる」と言える
- ✅ 完了条件: --channel piezo で直置き受信が通る

### E2: 机越し受信
- スマホとPC（またはピエゾ）を同じ机に置き、机を伝う振動で受信
- 主に感度（閾値を下げる・ゲインを上げる）との戦い。E1のピエゾを机に貼るのが有望
- ✅ 完了条件: 接触なし・同一机・30cm以上離して1つのidが通る

### E3: channels/imu_serial.py — IMUチャンネル
- Arduino/ESP32 + MPU6050 → pyserial。加速度の大きさを envelope 相当として to_pulses に流す
- ✅ 完了条件: --channel imu で直置き受信が通る

### E4: マルチチャンネルAND判定
- mic + piezo の両方が同時にONのときだけパルスと認める → 誤検出激減
- ✅ 完了条件: 騒音環境（音楽再生中など）で成功率が単独チャンネルより向上

### E5: 直接符号化モードの復調（= 全体ISSUESのX2）
- モードマーカー=1 の可変長ペイロード対応。PROTOCOL.md追記とセットで
