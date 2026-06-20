"""PROTOCOL.md v1.0 の定数。唯一の正は PROTOCOL.md。変更は3人合意のみ。"""

# タイミング (ms)
SHORT_MS = 150          # 短い振動 = bit 0
LONG_MS = 450           # 長い振動 = bit 1
GAP_MS = 150            # ビット間 OFF
PREAMBLE_ON_MS = 700    # プリアンブル ON
PREAMBLE_OFF_MS = 200   # プリアンブル OFF
PREAMBLE_REPEAT = 2     # [700on, 200off] x 2

# 判定
SHORT_LONG_BOUNDARY_MS = 300   # ONパルス長 >= 300ms なら 1（gapは判定に使わない）
PREAMBLE_MIN_MS = 550          # これ以上のONはプリアンブル候補（700msとlong 450msの間）

# フレーム
ID_BITS = 8             # id は 8bit 固定 (0..255)
MAX_MESSAGE_ID = (1 << ID_BITS) - 1  # id の最大値 255。範囲外は逆引きしない（lookup で使用）
MSB_FIRST = True
MODE_ID = 0             # モードマーカー 0 = idモード（本線）
MODE_DIRECT = 1         # 1 = 直接符号化（stretch）

# 受信側の派生/運用定数（PROTOCOL.md には無い。受信ループの実装都合。定数は config.py に集約する）
FRAME_PULSES = PREAMBLE_REPEAT + 1 + ID_BITS  # 1フレームのONパルス数: プリアンブル + モードマーカー + ペイロード
MAX_BUFFER_FRAMES = 2        # バッファ上限をフレーム何個分まで許すか（ノイズで無限に伸びるのを防ぐ）
FRAME_GAP_MULTIPLIER = 3     # 連続受信時のフレーム境界ギャップを GAP_MS の何倍空けるか

# WebSocket 配信（段1）。ブラウザ演出HTMLへ進行イベントをリアルタイム配信する既定アドレス。
# 受信処理はブロックしない（専用スレッドのイベントループで配信。詳細は ws_server.py）。
WS_HOST = "localhost"
WS_PORT = 8765

# 配信イベントの type 値。ブラウザ側 handler と一致しないと演出が無音で止まる契約値なので、
# Python 側は文字列直書きを避けてここに集約する（タイプミス・将来追加時のズレ防止）。
WS_EVENT_LISTENING = "listening"  # 待機開始
WS_EVENT_PREAMBLE = "preamble"    # プリアンブル検出
WS_EVENT_BIT = "bit"              # データビット確定（value: 0|1, MSB first）
WS_EVENT_DECODED = "decoded"      # id 確定（id: int）
WS_EVENT_URL = "url"              # 逆引き結果（url: str）
WS_EVENT_OPEN = "open"            # オープン（url: str）
WS_EVENT_LEVEL = "level"          # 受信中の振幅（v: 0.0〜1.0。包絡線をオシロスコープへ・段2）

# level 配信（段2）。受信チャンネルの包絡線を 0..1 に正規化してブラウザの波形を駆動する。
# 連続値なので「毎フレーム送らず」目標レート以下に間引く（送りすぎ防止。30〜60Hzの中庸を採る）。
LEVEL_RATE_HZ = 40.0      # level イベントの目標配信レート（1/この秒数より速くは送らない）
LEVEL_PEAK_DECAY = 0.9    # 自動ゲインの走行ピークの減衰率（1 emit ごと。大きいほど余韻が長い）
LEVEL_DEFAULT_FLOOR = 1e-3  # 走行ピークの下限（無音時に張り付く値。ノイズを 1.0 に誇張しない）

# Supabase 逆引き設定（R9）。テーブル / 列名（id を引いて url を得る逆引き）。
SUPABASE_TABLE = "urls"
SUPABASE_ID_COLUMN = "id"
SUPABASE_URL_COLUMN = "url"

# --offline 用のローカル固定辞書（会場 Wi-Fi 死亡時のデモ保険）。
# 本線は Supabase 逆引きだが、デモで使う代表 id（42, 7）はここでも引けるようにしておく。
OFFLINE_URLS = {
    42: "https://example.com",
    7: "https://www.anthropic.com",
    0: "https://example.com/zero",
    255: "https://example.com/max",
}
