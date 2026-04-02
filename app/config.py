from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "cb_arbitrage.db"

# 套利参数
DISCOUNT_THRESHOLD = -1.0   # 折价率阈值（%），负值
TARGET_LOT_SIZE = 10        # 每次买入张数

# akshare缓存时间（秒）
DATA_CACHE_TTL = 60
