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
