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
MSB_FIRST = True
MODE_ID = 0             # モードマーカー 0 = idモード（本線）
MODE_DIRECT = 1         # 1 = 直接符号化（stretch）

# 受信側の派生/運用定数（PROTOCOL.md には無い。受信ループの実装都合。定数は config.py に集約する）
FRAME_PULSES = PREAMBLE_REPEAT + 1 + ID_BITS  # 1フレームのONパルス数: プリアンブル + モードマーカー + ペイロード
MAX_BUFFER_FRAMES = 2        # バッファ上限をフレーム何個分まで許すか（ノイズで無限に伸びるのを防ぐ）
FRAME_GAP_MULTIPLIER = 3     # 連続受信時のフレーム境界ギャップを GAP_MS の何倍空けるか

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
