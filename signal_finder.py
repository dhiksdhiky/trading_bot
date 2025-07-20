# signal_finder.py
# Mesin pemindai sinyal hibrida (Sinyal Kualitas Tinggi + Peringatan Dini)
import os
import requests
import ccxt
import pandas as pd
import ta
import telegram
import json

# --- KONFIGURASI ---
RAILWAY_URL = os.environ.get("RAILWAY_URL")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
CRYPTOCOMPARE_API_KEY = os.environ.get('CRYPTOCOMPARE_API_KEY') 

# --- DATABASE PENGATURAN INDIKATOR ---
OPTIMAL_SETTINGS = {
    "BTC":  {"ema_fast": 20, "ema_slow": 50, "rsi_period": 14, "rsi_ob": 80, "rsi_os": 20, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
    "ETH":  {"ema_fast": 20, "ema_slow": 50, "rsi_period": 14, "rsi_ob": 80, "rsi_os": 20, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
    "SOL":  {"ema_fast": 9,  "ema_slow": 21, "rsi_period": 14, "rsi_ob": 80, "rsi_os": 20, "macd_fast": 5,  "macd_slow": 35, "macd_signal": 5},
    "DEFAULT": {"ema_fast": 20, "ema_slow": 50, "rsi_period": 14, "rsi_ob": 70, "rsi_os": 30, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9}
}
SENSITIVE_SETTINGS = {
    "BTC":  {"rsi_ob": 65, "rsi_os": 35, "macd_fast": 9, "macd_slow": 21, "macd_signal": 7},
    "ETH":  {"rsi_ob": 65, "rsi_os": 35, "macd_fast": 9, "macd_slow": 21, "macd_signal": 7},
    "SOL":  {"rsi_ob": 65, "rsi_os": 35, "macd_fast": 9, "macd_slow": 21, "macd_signal": 7},
    "DEFAULT": {"rsi_ob": 65, "rsi_os": 35, "macd_fast": 9, "macd_slow": 21, "macd_signal": 7}
}

# --- FUNGSI INTERAKSI DENGAN AI & API ---
def get_gemini_analysis(prompt: str):
    if not GEMINI_API_KEY: return None
    try:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(api_url, json=payload, timeout=45)
        response.raise_for_status()
        return response.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"Error saat berkomunikasi dengan Gemini: {e}")
        return None

def get_news_headlines(symbol: str):
    url = f"https://min-api.cryptocompare.com/data/v2/news/?lang=EN&categories={symbol.upper()}&api_key={CRYPTOCOMPARE_API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return [news['title'] for news in response.json()['Data'][:5]]
    except Exception as e:
        print(f"Gagal mengambil berita untuk AI: {e}")
        return []

def get_api_data():
    try:
        base_url = RAILWAY_URL
        if not base_url.startswith(('http://', 'https://')): base_url = 'https://' + base_url
        url = f"{base_url}/api/data?secret={API_SECRET_KEY}"
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Gagal mengambil data dari Railway: {e}")
        return None

def calculate_indicators(df, settings, sensitive=False):
    if sensitive:
        df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        macd = ta.trend.MACD(df['close'], window_fast=settings['macd_fast'], window_slow=settings['macd_slow'], window_sign=settings['macd_signal'])
    else:
        df['ema_fast'] = ta.trend.ema_indicator(df['close'], window=settings['ema_fast'])
        df['ema_slow'] = ta.trend.ema_indicator(df['close'], window=settings['ema_slow'])
        df['rsi'] = ta.momentum.rsi(df['close'], window=settings['rsi_period'])
        macd = ta.trend.MACD(df['close'], window_fast=settings['macd_fast'], window_slow=settings['macd_slow'], window_sign=settings['macd_signal'])
    
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df.dropna(inplace=True)
    return df

# --- FUNGSI STRATEGI ---
def check_signal(symbol: str, timeframe: str = '4h'):
    try:
        settings = OPTIMAL_SETTINGS.get(symbol, OPTIMAL_SETTINGS["DEFAULT"])
        exchange = ccxt.kucoin()
        ohlcv = exchange.fetch_ohlcv(f"{symbol}/USDT", timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = calculate_indicators(df, settings)
        if len(df) < 3: return None, None

        last, prev = df.iloc[-1], df.iloc[-2]

        is_uptrend = last['close'] > last['ema_slow'] and last['ema_fast'] > last['ema_slow']
        rsi_pullback = prev['rsi'] < settings['rsi_os'] and last['rsi'] > settings['rsi_os']
        macd_buy_confirm = prev['macd'] < prev['macd_signal'] and last['macd'] > last['macd_signal']

        if is_uptrend and rsi_pullback and macd_buy_confirm:
            return "BUY", df

        is_downtrend = last['close'] < last['ema_slow'] and last['ema_fast'] < last['ema_slow']
        rsi_rally_fail = prev['rsi'] > settings['rsi_ob'] and last['rsi'] < settings['rsi_ob']
        macd_sell_confirm = prev['macd'] > prev['macd_signal'] and last['macd'] < last['macd_signal']

        if is_downtrend and rsi_rally_fail and macd_sell_confirm:
            return "SELL", df

        return None, None
    except Exception as e:
        print(f"Error saat mengecek Sinyal untuk {symbol}: {e}")
        return None, None

def check_alert(symbol: str, timeframe: str = '4h'):
    try:
        settings = SENSITIVE_SETTINGS.get(symbol, SENSITIVE_SETTINGS["DEFAULT"])
        exchange = ccxt.kucoin()
        ohlcv = exchange.fetch_ohlcv(f"{symbol}/USDT", timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = calculate_indicators(df, settings, sensitive=True)
        if len(df) < 3: return None

        last, prev = df.iloc[-1], df.iloc[-2]

        rsi_buy_alert = last['rsi'] < settings['rsi_os']
        macd_buy_alert = prev['macd'] < prev['macd_signal'] and last['macd'] > last['macd_signal']
        if rsi_buy_alert and macd_buy_alert:
            return "BUY_ALERT"

        rsi_sell_alert = last['rsi'] > settings['rsi_ob']
        macd_sell_alert = prev['macd'] > prev['macd_signal'] and last['macd'] < last['macd_signal']
        if rsi_sell_alert and macd_sell_alert:
            return "SELL_ALERT"
            
        return None
    except Exception as e:
        print(f"Error saat mengecek Peringatan untuk {symbol}: {e}")
        return None

# --- FUNGSI MAIN ---
def main():
    print("Memulai pemindai sinyal hibrida...")
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    api_data = get_api_data()
    
    if not api_data:
        print("Gagal memuat data. Keluar.")
        return

    user_data = api_data.get("users", {})
    core_watchlist = api_data.get("core_watchlist", [])

    # Gabungkan semua watchlist menjadi satu set unik untuk dipindai
    coins_to_scan = set(core_watchlist)
    for user_id, data in user_data.items():
        for coin in data.get("watchlist", []):
            coins_to_scan.add(coin)

    if not coins_to_scan:
        print("Tidak ada koin untuk dipindai. Selesai.")
        return
    
    print(f"Memindai koin: {list(coins_to_scan)}")

    for coin in coins_to_scan:
        # 1. Cek Sinyal Kualitas Tinggi
        signal_type, df = check_signal(coin)
        if signal_type:
            news_headlines = get_news_headlines(coin)
            news_context = "Tidak ada berita signifikan."
            if news_headlines: news_context = "Berita terbaru:\n- " + "\n- ".join(news_headlines)
            
            prompt_sentiment = f"Saya menemukan sinyal teknikal {signal_type} untuk {coin}. {news_context}. Berdasarkan berita ini, apakah sentimen pasar mendukung sinyal ini? Jawab 'YA' atau 'TIDAK'."
            validation = get_gemini_analysis(prompt_sentiment)

            if validation and "TIDAK" in validation.upper():
                print(f"AI membatalkan sinyal {signal_type} untuk {coin} karena sentimen berita.")
                continue

            harga_saat_ini = df['close'].iloc[-1]
            message_header = f"🎯 **SINYAL DITEMUKAN: Potensi {signal_type}**\n\n📈 **Aset**: `{coin}` (Timeframe: 4h)\n💰 **Harga**: `${harga_saat_ini:,.2f}`"
            
            for user_id, data in user_data.items():
                is_in_watchlist = coin in data.get("watchlist", []) or coin in core_watchlist
                strategy_name = "pullback_buy" if signal_type == "BUY" else "breakdown_sell"
                if is_in_watchlist and data.get("strategies", {}).get(strategy_name, {}).get("signal_on", False):
                    try:
                        bot.send_message(chat_id=int(user_id), text=message_header, parse_mode='Markdown')
                        print(f">>> Sinyal {signal_type} terkirim ke {user_id} untuk {coin}!")
                    except Exception as e:
                        print(f"Gagal mengirim sinyal ke {user_id}: {e}")

        # 2. Cek Peringatan Dini
        alert_type = check_alert(coin)
        if alert_type:
            direction = "BULLISH" if "BUY" in alert_type else "BEARISH"
            message_alert = f"🔔 **PERINGATAN DINI: Potensi Pergerakan {direction}**\n\n**Aset**: `{coin}` (Timeframe: 4h)\n\n_Parameter sensitif mendeteksi momentum awal. Harap pantau lebih lanjut._"
            
            for user_id, data in user_data.items():
                is_in_watchlist = coin in data.get("watchlist", []) or coin in core_watchlist
                strategy_name = "pullback_buy" if "BUY" in alert_type else "breakdown_sell"
                if is_in_watchlist and data.get("strategies", {}).get(strategy_name, {}).get("alert_on", False):
                    try:
                        bot.send_message(chat_id=int(user_id), text=message_alert, parse_mode='Markdown')
                        print(f">>> Peringatan {direction} terkirim ke {user_id} untuk {coin}!")
                    except Exception as e:
                        print(f"Gagal mengirim peringatan ke {user_id}: {e}")

    print("Pemindai sinyal selesai.")

if __name__ == "__main__":
    main()
