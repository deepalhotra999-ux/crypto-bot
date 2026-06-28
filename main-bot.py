import time, requests, math, logging
from datetime import datetime

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
TOKEN    = "8628489665:AAF2-cmo6fYVA2YfYCWyZqGSSXH9dJoQhsE"
CHAT     = 508265847
CHECK    = 3600          # scan every 1 hour
SL_PCT   = 0.025         # 2.5% stop loss
TP1_PCT  = 0.025         # 2.5%
TP2_PCT  = 0.045         # 4.5%
TP3_PCT  = 0.075         # 7.5%

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)
fired = set()

# ─────────────────────────────────────────
#  COINS (CoinGecko IDs + display pair)
# ─────────────────────────────────────────
COINS = [
    ("bitcoin","BTC/USDT"),("ethereum","ETH/USDT"),("solana","SOL/USDT"),
    ("binancecoin","BNB/USDT"),("ripple","XRP/USDT"),("dogecoin","DOGE/USDT"),
    ("cardano","ADA/USDT"),("avalanche-2","AVAX/USDT"),("chainlink","LINK/USDT"),
    ("polkadot","DOT/USDT"),("near","NEAR/USDT"),("uniswap","UNI/USDT"),
    ("litecoin","LTC/USDT"),("cosmos","ATOM/USDT"),("aptos","APT/USDT"),
    ("sui","SUI/USDT"),("arbitrum","ARB/USDT"),("optimism","OP/USDT"),
    ("injective-protocol","INJ/USDT"),("render-token","RENDER/USDT"),
    ("aave","AAVE/USDT"),("maker","MKR/USDT"),("lido-dao","LDO/USDT"),
    ("pepe","PEPE/USDT"),("shiba-inu","SHIB/USDT"),("tron","TRX/USDT"),
    ("stellar","XLM/USDT"),("filecoin","FIL/USDT"),("algorand","ALGO/USDT"),
    ("hedera","HBAR/USDT"),("fantom","FTM/USDT"),("the-sandbox","SAND/USDT"),
    ("decentraland","MANA/USDT"),("axie-infinity","AXS/USDT"),("stacks","STX/USDT"),
    ("curve-dao-token","CRV/USDT"),("synthetix-network-token","SNX/USDT"),
    ("gala","GALA/USDT"),("ocean-protocol","OCEAN/USDT"),("vechain","VET/USDT"),
    ("internet-computer","ICP/USDT"),("the-graph","GRT/USDT"),
    ("compound-governance-token","COMP/USDT"),("1inch","1INCH/USDT"),
    ("enjincoin","ENJ/USDT"),("theta-token","THETA/USDT"),("tezos","XTZ/USDT"),
    ("zcash","ZEC/USDT"),("monero","XMR/USDT"),("band-protocol","BAND/USDT"),
]

# ─────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────
def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        log.error(f"TG: {e}")

# ─────────────────────────────────────────
#  COINGECKO DATA
# ─────────────────────────────────────────
def get_ohlc(coin_id, days=14):
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc",
            params={"vs_currency": "usd", "days": days},
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            if len(data) >= 40:
                return data
    except Exception as e:
        log.warning(f"OHLC {coin_id}: {e}")
    return None

def get_price_data(coin_id):
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd",
                    "include_24hr_change": "true", "include_24hr_vol": "true"},
            timeout=10
        )
        if r.status_code == 200:
            d = r.json().get(coin_id, {})
            return d.get("usd", 0), d.get("usd_24h_change", 0), d.get("usd_24h_vol", 0)
    except Exception as e:
        log.warning(f"Price {coin_id}: {e}")
    return 0, 0, 0

# ─────────────────────────────────────────
#  INDICATORS
# ─────────────────────────────────────────
def ema(prices, n):
    k = 2 / (n + 1)
    e = [prices[0]]
    for p in prices[1:]:
        e.append(p * k + e[-1] * (1 - k))
    return e

def rsi(prices, n=14):
    gains  = [max(prices[i]-prices[i-1], 0) for i in range(1, len(prices))]
    losses = [max(prices[i-1]-prices[i], 0) for i in range(1, len(prices))]
    if len(gains) < n:
        return 50
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    return 100 if al == 0 else 100 - (100 / (1 + ag/al))

def atr(highs, lows, closes, n=14):
    trs = [max(highs[i]-lows[i],
               abs(highs[i]-closes[i-1]),
               abs(lows[i]-closes[i-1])) for i in range(1, len(closes))]
    return sum(trs[-n:]) / n if len(trs) >= n else 0

def avg_volume(vols, n=10):
    if len(vols) < n:
        return sum(vols) / len(vols)
    return sum(vols[-n:]) / n

# ─────────────────────────────────────────
#  PRICE ACTION HELPERS
# ─────────────────────────────────────────
def candle_body(o, c):
    return abs(c - o)

def upper_wick(o, h, c):
    return h - max(o, c)

def lower_wick(o, l, c):
    return min(o, c) - l

def is_rejection_candle(o, h, l, c):
    """Strong wick rejection — wick at least 2x the body."""
    body = candle_body(o, c)
    if body == 0:
        return False, False
    lw = lower_wick(o, l, c)
    uw = upper_wick(o, h, c)
    bull_rejection = lw >= 2 * body and c > o   # hammer
    bear_rejection = uw >= 2 * body and c < o   # shooting star
    return bull_rejection, bear_rejection

def swing_highs_lows(highs, lows, lookback=10):
    """Find recent swing highs and swing lows (liquidity pools)."""
    recent_h = highs[-lookback:]
    recent_l = lows[-lookback:]
    swing_high = max(recent_h)
    swing_low  = min(recent_l)
    # Find previous swing (older candles)
    prev_h = highs[-lookback*2:-lookback] if len(highs) >= lookback*2 else highs[:lookback]
    prev_l = lows[-lookback*2:-lookback]  if len(lows)  >= lookback*2 else lows[:lookback]
    prev_swing_high = max(prev_h)
    prev_swing_low  = min(prev_l)
    return swing_high, swing_low, prev_swing_high, prev_swing_low

# ─────────────────────────────────────────
#  LIQUIDITY GRAB DETECTION
# ─────────────────────────────────────────
def detect_liquidity_grab(opens, highs, lows, closes, volumes):
    """
    BULLISH Liquidity Grab (Long Setup):
    - Price spikes BELOW a recent swing low (grabs sell-stop liquidity)
    - Then closes BACK ABOVE the swing low (rejection)
    - Confirmation: strong lower wick + bullish close + volume spike

    BEARISH Liquidity Grab (Short Setup):
    - Price spikes ABOVE a recent swing high (grabs buy-stop liquidity)
    - Then closes BACK BELOW the swing high (rejection)
    - Confirmation: strong upper wick + bearish close + volume spike
    """
    if len(closes) < 30:
        return None, [], 0

    # Current candle
    o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
    prev_vol_avg = avg_volume(volumes[:-1], 10)
    curr_vol = volumes[-1]
    vol_spike = curr_vol > prev_vol_avg * 1.3

    # Swing levels (from candles before current)
    sh, sl, psh, psl = swing_highs_lows(highs[:-1], lows[:-1], lookback=12)

    bull_rej, bear_rej = is_rejection_candle(o, h, l, c)

    # EMA trend filter
    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    rsi_val = rsi(closes)
    atr_val = atr(highs, lows, closes)

    score = 0
    tags  = []
    direction = None

    # ── BULLISH LIQUIDITY GRAB ──
    bull_score = 0
    bull_tags  = []

    # Core: wick spiked below swing low then closed above it
    if l < sl and c > sl:
        bull_score += 3
        bull_tags.append(f"Liquidity grab below swing low ({fmt(sl)})")

    # Candle rejection (hammer / pin bar)
    if bull_rej:
        bull_score += 2
        bull_tags.append("Strong bullish rejection wick")

    # Volume confirmation
    if vol_spike:
        bull_score += 1
        bull_tags.append("Volume spike on grab")

    # RSI not overbought
    if rsi_val < 65:
        bull_score += 1
        bull_tags.append(f"RSI clear ({rsi_val:.0f})")

    # EMA trend support (price above EMA21 or bouncing from it)
    if c > e21[-1] or (l < e21[-1] and c > e21[-1] * 0.995):
        bull_score += 1
        bull_tags.append("EMA21 support respected")

    # Previous swing low as double bottom
    if abs(l - psl) / psl < 0.015:
        bull_score += 1
        bull_tags.append("Double bottom liquidity zone")

    # ── BEARISH LIQUIDITY GRAB ──
    bear_score = 0
    bear_tags  = []

    # Core: wick spiked above swing high then closed below it
    if h > sh and c < sh:
        bear_score += 3
        bear_tags.append(f"Liquidity grab above swing high ({fmt(sh)})")

    # Candle rejection (shooting star / pin bar)
    if bear_rej:
        bear_score += 2
        bear_tags.append("Strong bearish rejection wick")

    if vol_spike:
        bear_score += 1
        bear_tags.append("Volume spike on grab")

    if rsi_val > 35:
        bear_score += 1
        bear_tags.append(f"RSI clear ({rsi_val:.0f})")

    if c < e21[-1] or (h > e21[-1] and c < e21[-1] * 1.005):
        bear_score += 1
        bear_tags.append("EMA21 resistance respected")

    if abs(h - psh) / psh < 0.015:
        bear_score += 1
        bear_tags.append("Double top liquidity zone")

    # Decide direction — need at least 4/8 for signal
    if bull_score >= 4 and bull_score > bear_score:
        return "LONG", bull_tags, bull_score, rsi_val, atr_val, sl, sh
    elif bear_score >= 4 and bear_score > bull_score:
        return "SHORT", bear_tags, bear_score, rsi_val, atr_val, sl, sh

    return None, [], 0, rsi_val, atr_val, sl, sh

# ─────────────────────────────────────────
#  FORMAT HELPERS
# ─────────────────────────────────────────
def fmt(v):
    if v >= 1000:    return f"{v:,.2f}"
    elif v >= 1:     return f"{v:.4f}"
    elif v >= 0.01:  return f"{v:.6f}"
    else:            return f"{v:.8f}"

def conf(score):
    return min(round(55 + (score / 8) * 42, 1), 97.5)

# ─────────────────────────────────────────
#  BUILD SIGNAL MESSAGE
# ─────────────────────────────────────────
def build_signal(pair, direction, price, change_24h, tags, score, rsi_val, atr_val, swing_low, swing_high):
    p = price
    c = conf(score)

    if direction == "LONG":
        # SL just below the swing low that was grabbed
        sl  = round(min(p * (1 - SL_PCT), swing_low * 0.995), 8)
        el  = round(p * 0.999, 8)
        eh  = round(p * 1.002, 8)
        tp1 = round(p * (1 + TP1_PCT), 8)
        tp2 = round(p * (1 + TP2_PCT), 8)
        tp3 = round(p * (1 + TP3_PCT), 8)
        arrow = "🟢"
        setup = "Liquidity Sweep + Bullish Reversal"
    else:
        # SL just above the swing high that was grabbed
        sl  = round(max(p * (1 + SL_PCT), swing_high * 1.005), 8)
        el  = round(p * 0.998, 8)
        eh  = round(p * 1.001, 8)
        tp1 = round(p * (1 - TP1_PCT), 8)
        tp2 = round(p * (1 - TP2_PCT), 8)
        tp3 = round(p * (1 - TP3_PCT), 8)
        arrow = "🔴"
        setup = "Liquidity Sweep + Bearish Reversal"

    reason = tags[0] if tags else setup

    msg = (
        f"🚀 <b>AI SIGNAL IS READY</b>\n\n"
        f"📊 <b>Pair:</b> {pair}\n"
        f"{arrow} <b>Direction:</b> {direction}\n"
        f"🎯 <b>Entry Zone:</b> {fmt(el)} – {fmt(eh)}\n"
        f"🛡 <b>Stop Loss:</b> {fmt(sl)}\n\n"
        f"🎯 <b>Take Profits:</b>\n"
        f"1️⃣  {fmt(tp1)}\n"
        f"2️⃣  {fmt(tp2)}\n"
        f"3️⃣  {fmt(tp3)}\n\n"
        f"🧠 <b>Confidence:</b> {c}%\n"
        f"{reason}\n\n"
        f"📈 <b>24h Change:</b> {change_24h:+.2f}%\n"
        f"RSI: {rsi_val:.1f} | ATR: {atr_val:.4f}\n"
        f"Setup: <b>{setup}</b>\n"
        f"Confirmations: {score}/8\n"
        f"⏰ {datetime.now().strftime('%b %d, %Y, %I:%M %p')}"
    )
    return msg, tp1, tp2, tp3, sl

# ─────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────
def main():
    log.info("Bot v3 — Liquidity Grab Strategy — Starting...")
    tg(
        f"🤖 <b>AI CRYPTO BOT — LIQUIDITY GRAB STRATEGY</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Watching: <b>{len(COINS)} coins</b>\n"
        f"⏱ Timeframe: <b>1 Hour</b>\n"
        f"🎯 Strategy: <b>Liquidity Sweep + Price Action + Volume</b>\n"
        f"📡 Data: <b>CoinGecko API</b>\n"
        f"⚠️ <i>PAPER TRADING — no real money</i>"
    )

    scan = 0
    last_ping = time.time()

    while True:
        try:
            scan += 1
            fired_this_scan = 0
            log.info(f"Scan #{scan} — {datetime.now().strftime('%H:%M:%S')}")

            for coin_id, pair in COINS:
                try:
                    data = get_ohlc(coin_id, days=14)
                    if not data or len(data) < 40:
                        time.sleep(2)
                        continue

                    opens  = [c[1] for c in data]
                    highs  = [c[2] for c in data]
                    lows   = [c[3] for c in data]
                    closes = [c[4] for c in data]
                    # Approximate volume from candle range * price (CoinGecko OHLC has no volume)
                    volumes = [(h - l) * c for h, l, c in zip(highs, lows, closes)]

                    result = detect_liquidity_grab(opens, highs, lows, closes, volumes)
                    direction, tags, score, rsi_val, atr_val, swing_low, swing_high = result

                    if direction:
                        price, change_24h, vol = get_price_data(coin_id)
                        if price == 0:
                            time.sleep(1)
                            continue

                        hour_key = datetime.now().strftime('%Y%m%d%H')
                        fire_key = f"{coin_id}_{direction}_{hour_key}"

                        if fire_key not in fired:
                            msg, tp1, tp2, tp3, sl = build_signal(
                                pair, direction, price, change_24h,
                                tags, score, rsi_val, atr_val, swing_low, swing_high
                            )
                            tg(msg)
                            fired.add(fire_key)
                            fired_this_scan += 1
                            log.info(f"Signal: {direction} {pair} score={score} conf={conf(score)}%")
                            time.sleep(4)

                    # CoinGecko rate limit: ~10-15 calls/min on free tier
                    time.sleep(2.5)

                except Exception as e:
                    log.error(f"{pair}: {e}")
                    time.sleep(2)
                    continue

            log.info(f"Scan #{scan} complete — {fired_this_scan} signals")

            if fired_this_scan == 0:
                log.info("No liquidity grabs detected this hour — waiting for next scan")

            # Ping every 6 hours so you know bot is alive
            if time.time() - last_ping > 6 * 3600:
                tg(f"💓 <b>Bot alive</b> — Scan #{scan}\n"
                   f"Total signals sent: {len(fired)}\n"
                   f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                last_ping = time.time()

            # Clean old fired keys
            if len(fired) > 600:
                old = list(fired)[:250]
                for k in old:
                    fired.discard(k)

        except KeyboardInterrupt:
            tg("🛑 <b>Bot stopped.</b>")
            break
        except Exception as e:
            log.error(f"Loop error: {e}")
            tg(f"⚠️ Error: {e}")

        log.info(f"Next scan in {CHECK//60} minutes...")
        time.sleep(CHECK)

if __name__ == "__main__":
    main()
