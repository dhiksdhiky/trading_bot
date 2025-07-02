# main.py
import ccxt
import pandas as pd
import mplfinance as mpf
import ta
import telegram
import os
import pytz
from datetime import datetime

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
bot = telegram.Bot(token=TELEGRAM_TOKEN)

# --- FUNGSI ANALISIS (Sama seperti sebelumnya) ---
def analyze_indicators(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    analysis = {}
    if last['close'] > last['ma9'] and last['ma9'] > last['ma26']:
        analysis['ma'] = "🟢 Bullish: Harga di atas MA, tren naik."
    elif last['close'] < last['ma9'] and last['ma9'] < last['ma26']:
        analysis['ma'] = "🔴 Bearish: Harga di bawah MA, tren turun."
    else:
        analysis['ma'] = "⚪ Netral: Harga bergerak di antara MA."
    if last['rsi'] > 70:
        analysis['rsi'] = f"🔴 Overbought ({last['rsi']:.2f})."
    elif last['rsi'] < 30:
        analysis['rsi'] = f"🟢 Oversold ({last['rsi']:.2f})."
    else:
        analysis['rsi'] = f"⚪ Netral ({last['rsi']:.2f})."
    if prev['macd'] < prev['macd_signal'] and last['macd'] > last['macd_signal']:
        analysis['macd'] = "🟢 Golden Cross: Sinyal beli kuat."
    elif prev['macd'] > prev['macd_signal'] and last['macd'] < last['macd_signal']:
        analysis['macd'] = "🔴 Death Cross: Sinyal jual kuat."
    else:
        analysis['macd'] = "⚪ Netral: Tidak ada persilangan."
    avg_volume = df['volume'].rolling(window=10).mean().iloc[-1]
    if last['volume'] > avg_volume * 1.5:
        analysis['volume'] = "🔥 Tinggi: Konfirmasi tren kuat."
    else:
        analysis['volume'] = "⚪ Normal."
    return analysis

def determine_final_signal(analysis):
    score = 0
    if "Bullish" in analysis['ma']: score += 1
    if "Bearish" in analysis['ma']: score -= 1
    if "Golden Cross" in analysis['macd']: score += 2
    if "Death Cross" in analysis['macd']: score -= 2
    if "Oversold" in analysis['rsi']: score += 1
    if "Overbought" in analysis['rsi']: score -= 1
    if score >= 2:
        return "🚨 SINYAL AKSI: BELI (BUY) 🚨"
    elif score <= -2:
        return "🚨 SINYAL AKSI: JUAL (SELL) 🚨"
    else:
        return "⚠️ SINYAL AKSI: TAHAN (HOLD) ⚠️"

# --- FUNGSI UTAMA ---
def run_analysis():
    PAIR = 'BTC/USDT'
    TIMEFRAME = '4h' # <-- DIUBAH SESUAI PERMINTAAN
    exchange = ccxt.kucoin()
    ohlcv = exchange.fetch_ohlcv(PAIR, timeframe=TIMEFRAME, limit=200)
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

    indicator_analysis = analyze_indicators(df)
    final_signal = determine_final_signal(indicator_analysis)
    df_for_plot = df.tail(24)

    # --- PENINGKATAN VISUAL ALA TRADINGVIEW ---
    mc = mpf.make_marketcolors(up='green', down='red', 
                               wick={'up':'green','down':'red'},
                               volume={'up':'green','down':'red'})
    s = mpf.make_mpf_style(marketcolors=mc, base_mpf_style='nightclouds')

    macd_hist_positive = df_for_plot['macd_hist'].where(df_for_plot['macd_hist'] >= 0, 0)
    macd_hist_negative = df_for_plot['macd_hist'].where(df_for_plot['macd_hist'] < 0, 0)

    macd_plots = [
        mpf.make_addplot(df_for_plot['macd'], panel=2, color='blue', ylabel='MACD'),
        mpf.make_addplot(df_for_plot['macd_signal'], panel=2, color='orange'),
        mpf.make_addplot(macd_hist_positive, type='bar', panel=2, color='green', alpha=0.7),
        mpf.make_addplot(macd_hist_negative, type='bar', panel=2, color='red', alpha=0.7)
    ]
    rsi_plot = mpf.make_addplot(df_for_plot['rsi'], panel=1, color='purple', ylabel='RSI')
    extra_plots = [rsi_plot] + macd_plots

    harga_terkini = df['close'].iloc[-1]
    waktu_sekarang = datetime.now(pytz.timezone('Asia/Jakarta')).strftime('%d %b %Y, %H:%M WIB')

    mpf.plot(
        df_for_plot, type='candle', style=s,
        title=f'Analisis Detail {PAIR} - {TIMEFRAME}',
        ylabel='Harga (USDT)', volume=True, mav=(9, 26), addplot=extra_plots,
        panel_ratios=(8, 3, 3), figscale=2.0,
        hlines=dict(hlines=[harga_terkini], colors=['w'], linestyle='-.', alpha=0.5),
        savefig='btc_analysis_ultimate.png'
    )

    # --- PENINGKATAN CAPTION ---
    caption = (
        f"📊 **Analisis Teknikal Ultimate: {PAIR} | {TIMEFRAME}**\n"
        f"*(Harga: ${harga_terkini:,.2f} pada {waktu_sekarang})*\n\n"
        f"**Keterangan Indikator:**\n"
        f"1. **Moving Average**: {indicator_analysis['ma']}\n"
        f"2. **RSI**: {indicator_analysis['rsi']}\n"
        f"3. **MACD**: {indicator_analysis['macd']}\n"
        f"4. **Volume**: {indicator_analysis['volume']}\n\n"
        f"------------------------------------\n"
        f"**{final_signal}**\n"
        f"------------------------------------\n\n"
        f"*(Disclaimer: Selalu lakukan riset Anda sendiri.)*"
    )

    bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=open('btc_analysis_ultimate.png', 'rb'), caption=caption, parse_mode='Markdown')
    print("Analisis berhasil dikirim.")

if __name__ == "__main__":
    run_analysis()
