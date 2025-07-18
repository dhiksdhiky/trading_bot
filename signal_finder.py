# signal_finder.py
# Mesin pemindai sinyal proaktif dengan validasi Gemini AI
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

# --- DATABASE PENGATURAN OPTIMAL (Tidak berubah) ---
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

# --- FUNGSI INTERAKSI DENGAN GEMINI AI ---
def get_gemini_analysis(prompt: str):
    """Mengirim prompt ke Gemini dan mengembalikan respons teks."""
    if not GEMINI_API_KEY:
        print("Warning: GEMINI_API_KEY tidak diset. Melewatkan analisis AI.")
        return None
    try:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(api_url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"Error saat berkomunikasi dengan Gemini: {e}")
        return None

# --- FUNGSI LAINNYA ---
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

# --- FUNGSI STRATEGI (Diperbarui dengan integrasi AI) ---
def check_pullback_buy_strategy(symbol: str, timeframe: str = '4h'):
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
            print(f"Sinyal teknikal Beli ditemukan untuk {symbol}. Memvalidasi dengan AI...")
            
            # 1. Validasi Kontekstual dengan AI
            prompt_sentiment = f"Saya menemukan sinyal beli teknikal untuk {symbol}. Berdasarkan berita dan sentimen pasar terkini, apakah ada alasan fundamental yang kuat untuk TIDAK mengambil posisi beli ini? Jawab 'YA' jika ada sentimen negatif kuat, atau 'TIDAK' jika netral/positif."
            sentiment_validation = get_gemini_analysis(prompt_sentiment)
            
            if sentiment_validation and "YA" in sentiment_validation.upper():
                print(f"AI mendeteksi sentimen negatif untuk {symbol}. Sinyal dibatalkan.")
                return None
            
            print(f"Validasi sentimen AI untuk {symbol} berhasil.")
            
            # 2. Minta Saran Manajemen Risiko dari AI
            harga_saat_ini = last['close']
            swing_low = df['low'].tail(14).min()
            swing_high = df['high'].tail(14).max()

            prompt_risk = f"""
            Sinyal beli untuk {symbol} ditemukan di harga ${harga_saat_ini:,.2f}. Swing low terdekat adalah ${swing_low:,.2f} dan swing high terdekat adalah ${swing_high:,.2f}.
            Berdasarkan data ini, sarankan level Stop-Loss dan Take-Profit (Target 1) yang logis.
            Jawab HANYA dalam format JSON seperti ini: {{"stop_loss": "harga", "take_profit_1": "harga"}}
            """
            risk_suggestion_str = get_gemini_analysis(prompt_risk)
            risk_suggestion = {}
            if risk_suggestion_str:
                try:
                    # Membersihkan output JSON dari markdown
                    clean_json_str = risk_suggestion_str.replace('```json', '').replace('```', '').strip()
                    risk_suggestion = json.loads(clean_json_str)
                except json.JSONDecodeError:
                    print("Gagal mem-parsing saran risiko dari AI.")

            sl = risk_suggestion.get('stop_loss', 'N/A')
            tp1 = risk_suggestion.get('take_profit_1', 'N/A')

            message = (
                f"🎯 **SINYAL DIVALIDASI AI: Potensi Beli**\n\n"
                f"📈 **Aset**: `{symbol}` (Timeframe: {timeframe})\n"
                f"💰 **Harga Saat Ini**: `${harga_saat_ini:,.2f}`\n\n"
                f"**Analisis Teknikal:**\n"
                f"1. **Tren Utama**: Bullish\n"
                f"2. **Pullback**: RSI keluar dari area oversold\n"
                f"3. **Konfirmasi**: MACD Golden Cross\n\n"
                f"**🧠 Saran Manajemen Risiko dari AI:**\n"
                f"🔴 **Stop-Loss**: `${sl}`\n"
                f"🟢 **Take-Profit 1**: `${tp1}`\n\n"
                f"_(Selalu lakukan riset Anda sendiri)_"
            )
            return message
        return None
    except Exception as e:
        print(f"Error saat mengecek strategi beli untuk {symbol}: {e}")
        return None

# --- FUNGSI MAIN ---
def main():
    print("Memulai pemindai sinyal (AI Enhanced)...")
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
    
    print("Pemindai sinyal selesai.")

if __name__ == "__main__":
    main()
