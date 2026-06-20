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

# ─────────────────────────────────────────────────────────────────────────
# X1: URL直接符号化モード ★実験的・未確定仕様（PROTOCOL.md 未反映）
#   PROTOCOL.md v1.0 はモードマーカー=1 を「直接符号化モード（stretch）」と予約し、
#   そのペイロードは「stretch着手時に追記」と未定義のまま残している。以下はその stretch 実装が
#   先行して使う**提案中の v1.1 ペイロード定義**であり、まだ公式仕様ではない（official は PROTOCOL.md v1.0）。
#   仕様確定時はここを起点に PROTOCOL.md へ反映する（単独変更はしない＝3人合意 → 両リポジトリ同時更新）。
# フレーム（MSB first）: [プリアンブル×2] [marker=1] [scheme 1] [length 6] [chars length×6] [checksum 8]
#   marker=1 … URL直接モード（marker=0=従来idモードは無変更・v1.0 確定部分）
#   scheme  … 0=https / 1=http
#   length  … 文字数（最大 X1_MAX_LENGTH。X1 は短URL専用）
#   chars   … 1文字=6bit。X1_CHAR_TABLE のインデックス
#   checksum… 本体(chars)に対する CRC-8（poly 0x07・検出のみ。詳細は src/x1.py）
# ─────────────────────────────────────────────────────────────────────────
X1_SCHEME_BITS = 1       # scheme フィールド幅
X1_LENGTH_BITS = 6       # length フィールド幅（→ 最大 63 文字）
X1_CHAR_BITS = 6         # 1文字あたりのビット数（64種テーブル）
X1_CHECKSUM_BITS = 8     # CRC-8
X1_MAX_LENGTH = (1 << X1_LENGTH_BITS) - 1  # length の最大（63）
X1_SCHEMES = {0: "https", 1: "http"}       # scheme ビット → URL スキーム
X1_CRC_POLY = 0x07       # CRC-8 多項式（init=0x00, 反転なし, 最終XORなし）

# 6bit 文字テーブル（送受信で完全一致させる）。リスト添字＝送るシンボル値（インデックス）。
#   idx 0–25  = a–z
#   idx 26–35 = 0–9
#   idx 36–58 = 記号23種（この順）
#   idx 59–63 = 予約（None）
X1_CHAR_TABLE = (
    [chr(ord("a") + i) for i in range(26)]            # 0–25: a–z
    + [chr(ord("0") + i) for i in range(10)]          # 26–35: 0–9
    + list(".-_~:/?#[]@!$&'()*+,;=%")                  # 36–58: 記号23種
    + [None] * 5                                       # 59–63: 予約
)

# X1 フレームの最大 ON パルス数（length 最大時）。下のバッファ上限算出に使う。
X1_MAX_FRAME_PULSES = (
    PREAMBLE_REPEAT + 1 + X1_SCHEME_BITS + X1_LENGTH_BITS
    + X1_CHAR_BITS * X1_MAX_LENGTH + X1_CHECKSUM_BITS
)

# 受信バッファ上限（ONパルス数）。フレーム未完が続いてもノイズで無限に伸びないよう末尾だけ残すための閾値。
# X1（可変長・最大63文字）は id フレームよりずっと長いので、最長 X1 フレームを収容できる値にする
# （短すぎると長い X1 を形成中にプリアンブルごと末尾トリムで捨ててしまい復号できない）。
MAX_BUFFER_PULSES = MAX_BUFFER_FRAMES * X1_MAX_FRAME_PULSES

# checksum NG（人間演奏のミス等）時に開く「運命のサイト🎲」既定リスト。
# 安全・無害な定番サイトのみ。チームで自由に差し替え可（本番デモ前に各自で開いて確認すること）。
FUN_SITES = [
    "https://ja.wikipedia.org/wiki/Special:Random",  # ランダムなウィキ記事
    "https://hacker-typer.com/",                      # それっぽいハッカー画面
    "https://pointerpointer.com/",                    # 指差し職人
    "https://theuselessweb.com/",                     # 無意味サイトへ転送
    "https://cat-bounce.com/",                        # 跳ねる猫
    "https://www.windows93.net/",                     # ネタOS風デスクトップ
]

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

# クライアント→サーバー方向の唯一のコマンド（演出HTMLの「終了」ボタン）。
# これだけは Python→ブラウザ配信ではなく、ブラウザ→Python の制御メッセージ。
# 受け取ると受信ループを正常終了させる（ターミナルへ戻って Ctrl+C する手間を省く）。
WS_COMMAND_QUIT = "quit"          # ブラウザから受信終了を要求する

# ブラウザ（演出HTML）の WS 接続が全部切れてからこの秒数だけ待ち、まだ誰も繋ぎ直さなければ
# 「ブラウザが閉じられた」とみなして受信ループを終了する。ページ更新は一瞬の再接続なので、
# この猶予内に繋ぎ直るぶんには終了しない（更新での誤終了を防ぐ）。
WS_DISCONNECT_GRACE_S = 3.0

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
