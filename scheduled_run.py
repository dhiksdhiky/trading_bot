# scheduled_run.py
# VERSI MANDIRI DENGAN SEMUA INDIKATOR TERBARU
import os
import requests
import ccxt
import pandas as pd
import mplfinance as mpf
import ta
import pytz
from datetime import datetime
import telegram
from telegram import ParseMode, Bot

# --- KONFIGURASI ---
PAIR_TO_ANALYZE = 'BTC/USDT'
TIMEFRAME_TO_ANALYZE = '4h'

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CRYPTOCOMPARE_API_KEY = os.environ.get('CRYPTOCOMPARE_API_KEY') 

# --- FUNGSI HELPER (Disalin dari main.py) ---
def get_fear_and_greed_index():
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()['data'][0]
        value = int(data['value'])
        classification = data['value_classification']
        sentiment_score = 0
        emoji = "😐"
        if "Extreme Fear" in classification or "Fear" in classification:
            sentiment_score = 1
            emoji = "😨"
        elif "Extreme Greed" in classification or "Greed" in classification:
            sentiment_score = -1
            emoji = "🤑"
        sentiment_text = f"{emoji} {classification} ({value})"
        return {"status": "ok", "score": sentiment_score, "text": sentiment_text}
    except Exception as e:
        print(f"Error di get_fear_and_greed_index: {e}")
        return {"status": "error", "message": "Gagal memuat F&G Index."}

def analyze_indicators(df: pd.DataFrame):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    analysis = {}
    if last['close'] > last['ma9'] and last['ma9'] > last['ma26']: analysis['ma'] = "🟢 Bullish"
    elif last['close'] < last['ma9'] and last['ma9'] < last['ma26']: analysis['ma'] = "🔴 Bearish"
    else: analysis['ma'] = "⚪ Netral"
    if last['rsi'] > 70: analysis['rsi'] = f"🔴 Overbought ({last['rsi']:.2f})"
    elif last['rsi'] < 30: analysis['rsi'] = f"🟢 Oversold ({last['rsi']:.2f})"
    else: analysis['rsi'] = f"⚪ Netral ({last['rsi']:.2f})"
    if prev['macd'] < prev['macd_signal'] and last['macd'] > last['macd_signal']: analysis['macd'] = "🟢 Golden Cross"
    elif prev['macd'] > prev['macd_signal'] and last['macd'] < last['macd_signal']: analysis['macd'] = "🔴 Death Cross"
    else: analysis['macd'] = "⚪ Netral"
    analysis['bb_score'] = 0
    if last['close'] < last['bb_low']:
        analysis['bb'] = "🟢 Harga di bawah Lower Band"
        analysis['bb_score'] = 1
    elif last['close'] > last['bb_high']:
        analysis['bb'] = "🔴 Harga di atas Upper Band"
        analysis['bb_score'] = -1
    else:
        analysis['bb'] = "⚪ Harga di dalam Bands"
    avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
    if last['volume'] > avg_volume * 1.75:
        analysis['volume'] = "🔥 Tinggi (Konfirmasi Tren)"
    else:
        analysis['volume'] = "⚪ Normal"
    return analysis

def determine_final_signal(analysis: dict, sentiment: dict):
    score = 0
    if "Bullish" in analysis['ma']: score += 1
    if "Bearish" in analysis['ma']: score -= 1
    if "Golden Cross" in analysis['macd']: score += 2
    if "Death Cross" in analysis['macd']: score -= 2
    if "Oversold" in analysis['rsi']: score += 1
    if "Overbought" in analysis['rsi']: score -= 1
    score += analysis.get('bb_score', 0)
    if sentiment.get('status') == 'ok':
        score += sentiment.get('score', 0)
    if score >= 2: return "🚨 SINYAL AKSI: BELI (BUY) 🚨"
    elif score <= -2: return "🚨 SINYAL AKSI: JUAL (SELL) 🚨"
    else: return "⚠️ SINYAL AKSI: TAHAN (HOLD) ⚠️"

def generate_chart_and_caption(pair: str, timeframe: str):
    exchange = ccxt.kucoin()
    ohlcv = exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['ma9'] = ta.trend.sma_indicator(df['close'], window=9)
    df['ma26'] = ta.trend.sma_indicator(df['close'], window=26)
    df['rsi'] = ta.momentum.rsi(df['close'], window=14)
    macd = ta.trend.MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_hist'] = macd.macd_diff()
    bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
    df['bb_high'] = bb.bollinger_hband()
    df['bb_low'] = bb.bollinger_lband()
    df.dropna(inplace=True)
    
    if len(df) < 2:
        return None, "Gagal menganalisis, data tidak cukup setelah diproses.", None

    indicator_analysis = analyze_indicators(df)
    symbol = pair.split('/')[0]
    sentiment_analysis = get_fear_and_greed_index()
    final_signal = determine_final_signal(indicator_analysis, sentiment_analysis)
    
    df_for_plot = df.tail(30)
    
    first_price = df_for_plot['close'].iloc[0]
    last_price = df_for_plot['close'].iloc[-1]
    change_pct = ((last_price - first_price) / first_price) * 100
    change_emoji = "📈" if change_pct >= 0 else "📉"
    change_str = f"{change_emoji} {change_pct:+.2f}%"
    
    mc = mpf.make_marketcolors(up='#41a35a', down='#d74a43', wick={'up':'#41a35a','down':'#d74a43'}, volume={'up':'#41a35a','down':'#d74a43'})
    s = mpf.make_mpf_style(marketcolors=mc, base_mpf_style='nightclouds', gridstyle='-')
    addplots = [
        mpf.make_addplot(df_for_plot[['bb_high', 'bb_low']], color='gray', alpha=0.3),
        mpf.make_addplot(df_for_plot['rsi'], panel=1, color='purple', ylabel='RSI'),
        mpf.make_addplot(df_for_plot['macd'], panel=2, color='blue', ylabel='MACD'),
        mpf.make_addplot(df_for_plot['macd_signal'], panel=2, color='orange'),
        mpf.make_addplot(df_for_plot['macd_hist'].where(df_for_plot['macd_hist'] >= 0, 0), type='bar', panel=2, color='#41a35a'),
        mpf.make_addplot(df_for_plot['macd_hist'].where(df_for_plot['macd_hist'] < 0, 0), type='bar', panel=2, color='#d74a43')
    ]
    
    harga_terkini = df['close'].iloc[-1]
    waktu_sekarang = datetime.now(pytz.timezone('Asia/Jakarta')).strftime('%d %b %Y, %H:%M WIB')
    filename = f'analysis_{pair.replace("/", "")}_{timeframe}.png'
    mpf.plot(df_for_plot, type='candle', style=s, title=f'Analisis {pair} - Timeframe {timeframe}', ylabel='Harga (USDT)', volume=True, mav=(9, 26), addplot=addplots, panel_ratios=(8, 3, 3), figscale=1.5, savefig=filename)
    
    caption = (
        f"📊 **Analisis Terjadwal: {pair} | {timeframe} ({change_str})**\n"
        f"*(Harga: `${harga_terkini:,.2f}` pada {waktu_sekarang})*\n\n"
        f"**Indikator Teknikal:**\n"
        f"1. **Moving Average**: {indicator_analysis['ma']}\n"
        f"2. **RSI**: {indicator_analysis['rsi']}\n"
        f"3. **MACD**: {indicator_analysis['macd']}\n"
        f"4. **Bollinger Bands**: {indicator_analysis['bb']}\n"
        f"5. **Volume**: {indicator_analysis['volume']}\n\n"
        f"**Sentimen Pasar**: {sentiment_analysis['text']}\n"
        f"------------------------------------\n"
        f"**{final_signal}**"
    )
    return filename, caption, symbol

# --- FUNGSI UTAMA ---
def run_scheduled_job():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Variabel lingkungan tidak diset.")
        return

    print(f"Memulai analisis terjadwal untuk {PAIR_TO_ANALYZE}...")
    bot = Bot(token=TELEGRAM_TOKEN)
    
    try:
        filename, caption, symbol = generate_chart_and_caption(
            pair=PAIR_TO_ANALYZE,
            timeframe=TIMEFRAME_TO_ANALYZE
        )
        
        if not filename:
            print(f"Gagal menghasilkan chart: {caption}")
            return

        with open(filename, 'rb') as photo:
            bot.send_photo(
                chat_id=int(TELEGRAM_CHAT_ID),
                photo=photo,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        os.remove(filename)
        print("Analisis terjadwal berhasil dikirim.")

    except Exception as e:
        print(f"Terjadi kesalahan saat menjalankan tugas terjadwal: {e}")
        error_message = f"Gagal menjalankan analisis terjadwal untuk {PAIR_TO_ANALYZE}.\nError: `{e}`"
        bot.send_message(chat_id=int(TELEGRAM_CHAT_ID), text=error_message, parse_mode=ParseMode.MARKDOWN)

if __name__ == "__main__":
    run_scheduled_job()
