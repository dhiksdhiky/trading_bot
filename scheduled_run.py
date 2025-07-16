# scheduled_run.py
# VERSI FINAL MANDIRI - TIDAK LAGI MENGIMPOR DARI MAIN.PY
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
def get_market_sentiment(symbol: str):
    try:
        url = f'https://min-api.cryptocompare.com/data/pricemultifull?fsyms={symbol.upper()}&tsyms=USDT&api_key={CRYPTOCOMPARE_API_KEY}'
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        raw_data = data.get('RAW', {}).get(symbol.upper(), {}).get('USDT', {})
        if not raw_data: return {"status": "neutral", "message": f"Sentimen untuk {symbol} tidak ditemukan."}
        volume_24h = raw_data.get('VOLUME24HOURTO', 0)
        sentiment_score = 1 if volume_24h > 500_000_000 else 0
        sentiment_text = f"🟢 Tinggi (Volume: ${volume_24h:,.0f})" if sentiment_score == 1 else f"⚪ Netral (Volume: ${volume_24h:,.0f})"
        return {"status": "ok", "score": sentiment_score, "text": sentiment_text}
    except Exception as e:
        print(f"Error di get_market_sentiment: {e}")
        return {"status": "error", "message": "Gagal memuat sentimen."}

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
    return analysis

def determine_final_signal(analysis: dict, sentiment: dict):
    score = 0
    if "Bullish" in analysis['ma']: score += 1
    if "Bearish" in analysis['ma']: score -= 1
    if "Golden Cross" in analysis['macd']: score += 2
    if "Death Cross" in analysis['macd']: score -= 2
    if "Oversold" in analysis['rsi']: score += 1
    if "Overbought" in analysis['rsi']: score -= 1
    if sentiment.get('status') == 'ok': score += sentiment.get('score', 0)
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
    df.dropna(inplace=True)
    
    if len(df) < 2:
        return None, "Gagal menganalisis, data tidak cukup setelah diproses.", None

    indicator_analysis = analyze_indicators(df)
    symbol = pair.split('/')[0]
    sentiment_analysis = get_market_sentiment(symbol)
    final_signal = determine_final_signal(indicator_analysis, sentiment_analysis)
    
    df_for_plot = df.tail(30)
    mc = mpf.make_marketcolors(up='#41a35a', down='#d74a43', wick={'up':'#41a35a','down':'#d74a43'}, volume={'up':'#41a35a','down':'#d74a43'})
    s = mpf.make_mpf_style(marketcolors=mc, base_mpf_style='nightclouds', gridstyle='-')
    addplots = [
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
        f"📊 **Analisis Terjadwal: {pair} | {timeframe}**\n"
        f"*(Harga: `${harga_terkini:,.2f}` pada {waktu_sekarang})*\n\n"
        f"**Indikator Teknikal:**\n"
        f"1. **Moving Average**: {indicator_analysis['ma']}\n"
        f"2. **RSI**: {indicator_analysis['rsi']}\n"
        f"3. **MACD**: {indicator_analysis['macd']}\n\n"
        f"**Minat Pasar**: {sentiment_analysis['text']}\n"
        f"------------------------------------\n"
        f"**{final_signal}**"
    )
    return filename, caption, symbol

# --- FUNGSI UTAMA ---
def run_scheduled_job():
    """Fungsi utama untuk menjalankan tugas terjadwal."""
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
