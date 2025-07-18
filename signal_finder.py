# signal_finder.py
# Mesin pemindai sinyal proaktif dengan strategi ganda
import os
import requests
import ccxt
import pandas as pd
import ta
import telegram

# --- KONFIGURASI ---
RAILWAY_URL = os.environ.get("RAILWAY_URL")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# --- DATABASE PENGATURAN OPTIMAL (Berdasarkan Riset Anda) ---
OPTIMAL_SETTINGS = {
    "BTC":  {"ema_fast": 20, "ema_slow": 50, "rsi_period": 14, "rsi_ob": 80, "rsi_os": 20, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
    "ETH":  {"ema_fast": 20, "ema_slow": 50, "rsi_period": 14, "rsi_ob": 80, "rsi_os": 20, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
    "SOL":  {"ema_fast": 9,  "ema_slow": 21, "rsi_period": 14, "rsi_ob": 80, "rsi_os": 20, "macd_fast": 5,  "macd_slow": 35, "macd_signal": 5},
    "BNB":  {"ema_fast": 9,  "ema_slow": 21, "rsi_period": 14, "rsi_ob": 75, "rsi_os": 25, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
    "DOGE": {"ema_fast": 9,  "ema_slow": 21, "rsi_period": 14, "rsi_ob": 80, "rsi_os": 20, "macd_fast": 5,  "macd_slow": 35, "macd_signal": 5},
    "AVAX": {"ema_fast": 9,  "ema_slow": 21, "rsi_period": 14, "rsi_ob": 80, "rsi_os": 20, "macd_fast": 5,  "macd_slow": 35, "macd_signal": 5},
    "XRP":  {"ema_fast": 20, "ema_slow": 50, "rsi_period": 14, "rsi_ob": 70, "rsi_os": 30, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
    "ADA":  {"ema_fast": 20, "ema_slow": 50, "rsi_period": 21, "rsi_ob": 70, "rsi_os": 30, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
    "DOT":  {"ema_fast": 20, "ema_slow": 50, "rsi_period": 14, "rsi_ob": 75, "rsi_os": 25, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
    "LINK": {"ema_fast": 20, "ema_slow": 50, "rsi_period": 14, "rsi_ob": 75, "rsi_os": 25, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
    "DEFAULT": {"ema_fast": 20, "ema_slow": 50, "rsi_period": 14, "rsi_ob": 70, "rsi_os": 30, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9}
}

def get_user_data_from_api():
    """Mengambil data pengguna dari API di Railway."""
    try:
        base_url = RAILWAY_URL
        if not base_url.startswith(('http://', 'https://')):
            base_url = 'https://' + base_url
            
        url = f"{base_url}/api/data?secret={API_SECRET_KEY}"
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Gagal mengambil data dari Railway: {e}")
        return None

def calculate_indicators(df, settings):
    """Menghitung semua indikator yang dibutuhkan."""
    df['ema_fast'] = ta.trend.ema_indicator(df['close'], window=settings['ema_fast'])
    df['ema_slow'] = ta.trend.ema_indicator(df['close'], window=settings['ema_slow'])
    df['rsi'] = ta.momentum.rsi(df['close'], window=settings['rsi_period'])
    macd = ta.trend.MACD(df['close'], window_fast=settings['macd_fast'], window_slow=settings['macd_slow'], window_sign=settings['macd_signal'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df.dropna(inplace=True)
    return df

def check_pullback_buy_strategy(symbol: str, timeframe: str = '4h'):
    """Mengecek sinyal beli."""
    try:
        settings = OPTIMAL_SETTINGS.get(symbol, OPTIMAL_SETTINGS["DEFAULT"])
        exchange = ccxt.kucoin()
        ohlcv = exchange.fetch_ohlcv(f"{symbol}/USDT", timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = calculate_indicators(df, settings)
        
        if len(df) < 3: return None

        last, prev = df.iloc[-1], df.iloc[-2]

        is_uptrend = last['close'] > last['ema_slow'] and last['ema_fast'] > last['ema_slow']
        rsi_pullback = prev['rsi'] < settings['rsi_os'] and last['rsi'] > settings['rsi_os']
        macd_confirmation = prev['macd'] < prev['macd_signal'] and last['macd'] > last['macd_signal']

        if is_uptrend and rsi_pullback and macd_confirmation:
            harga_saat_ini = last['close']
            message = (
                f"🎯 **SINYAL DITEMUKAN: Potensi Beli**\n\n"
                f"📈 **Aset**: `{symbol}` (Timeframe: {timeframe})\n"
                f"💰 **Harga Saat Ini**: `${harga_saat_ini:,.2f}`\n\n"
                f"**Alasan Sinyal (Strategi `pullback_buy`):\n"
                f"1. **Tren Utama**: Bullish (di atas EMA {settings['ema_slow']})\n"
                f"2. **Pullback**: RSI keluar dari area oversold (<{settings['rsi_os']})\n"
                f"3. **Konfirmasi**: MACD Golden Cross\n\n"
                f"_(Selalu lakukan riset Anda sendiri)_"
            )
            return message
        return None
    except Exception as e:
        print(f"Error saat mengecek strategi beli untuk {symbol}: {e}")
        return None

def check_breakdown_sell_strategy(symbol: str, timeframe: str = '4h'):
    """Mengecek sinyal jual."""
    try:
        settings = OPTIMAL_SETTINGS.get(symbol, OPTIMAL_SETTINGS["DEFAULT"])
        exchange = ccxt.kucoin()
        ohlcv = exchange.fetch_ohlcv(f"{symbol}/USDT", timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = calculate_indicators(df, settings)

        if len(df) < 3: return None

        last, prev = df.iloc[-1], df.iloc[-2]

        is_downtrend = last['close'] < last['ema_slow'] and last['ema_fast'] < last['ema_slow']
        rsi_rally_fail = prev['rsi'] > settings['rsi_ob'] and last['rsi'] < settings['rsi_ob']
        macd_confirmation = prev['macd'] > prev['macd_signal'] and last['macd'] < last['macd_signal']

        if is_downtrend and rsi_rally_fail and macd_confirmation:
            harga_saat_ini = last['close']
            message = (
                f"🎯 **SINYAL DITEMUKAN: Potensi Jual (Short)**\n\n"
                f"📉 **Aset**: `{symbol}` (Timeframe: {timeframe})\n"
                f"💰 **Harga Saat Ini**: `${harga_saat_ini:,.2f}`\n\n"
                f"**Alasan Sinyal (Strategi `breakdown_sell`):\n"
                f"1. **Tren Utama**: Bearish (di bawah EMA {settings['ema_slow']})\n"
                f"2. **Reli Gagal**: RSI keluar dari area overbought (>{settings['rsi_ob']})\n"
                f"3. **Konfirmasi**: MACD Death Cross\n\n"
                f"_(Selalu lakukan riset Anda sendiri)_"
            )
            return message
        return None
    except Exception as e:
        print(f"Error saat mengecek strategi jual untuk {symbol}: {e}")
        return None

def main():
    print("Memulai pemindai sinyal...")
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    user_data = get_user_data_from_api()
    
    if not user_data:
        print("Gagal memuat data pengguna. Keluar.")
        return

    for user_id, data in user_data.items():
        strategies = data.get("strategies", {})
        watchlist = data.get("watchlist", [])
        
        if not watchlist: continue
        
        print(f"Memindai untuk pengguna {user_id}...")

        if strategies.get("pullback_buy", {}).get("enabled", False):
            for coin in watchlist:
                signal_message = check_pullback_buy_strategy(coin)
                if signal_message:
                    try:
                        bot.send_message(chat_id=int(user_id), text=signal_message, parse_mode='Markdown')
                        print(f">>> Sinyal BELI terkirim ke {user_id} untuk {coin}!")
                    except Exception as e:
                        print(f"Gagal mengirim pesan ke {user_id}: {e}")
        
        if strategies.get("breakdown_sell", {}).get("enabled", False):
            for coin in watchlist:
                signal_message = check_breakdown_sell_strategy(coin)
                if signal_message:
                    try:
                        bot.send_message(chat_id=int(user_id), text=signal_message, parse_mode='Markdown')
                        print(f">>> Sinyal JUAL terkirim ke {user_id} untuk {coin}!")
                    except Exception as e:
                        print(f"Gagal mengirim pesan ke {user_id}: {e}")
    
    print("Pemindai sinyal selesai.")

if __name__ == "__main__":
    main()
