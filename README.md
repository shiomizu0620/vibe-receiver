# vibe-receiver — VibeCode 受信側（PC / Python）

スマホの振動からid(8bit)を復調し、SupabaseでURLに逆引きしてブラウザで開く。
ラップトップにスマホを直置きし、マイクで振動を拾う。

- プロトコル: `PROTOCOL.md`（v1.0確定・送信側リポジトリ Vibes と同一内容を配置）
- 設計方針: `CLAUDE.md`（チャンネル・プラグイン構造）
- タスク: **`docs/ISSUES_receiver.md` を番号順（R1→R10）に1つずつ消化する**。拡張はE系

## セットアップ
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install sounddevice numpy scipy supabase rich matplotlib
```

## 実行
```bash
python -m src.main              # 受信待機 → 復調 → URLオープン
pytest                          # 復号ロジックのテスト（マイク不要）
```

## 開発の進め方
`docs/ISSUES_receiver.md` の **R1から番号順に1つずつ**。decode（旧P4相当）は実装・テスト済みなのでR1のpytest確認から始める。
R1〜R3はマイク不要、R4で実音、R8で実機チューニング、R10で受信側単体完成 → チーム結合(J1)へ。
拡張（ピエゾ/机越し/IMU/AND判定）はE系として独立issue化済み。
