# main.py
# KODE UNTUK BOT INTERAKTIF (HOSTING 24/7 DI REPLIT) - PERBAIKAN FINAL SENTIMEN & ZOOM
import os
import requests
import ccxt
import pandas as pd
import mplfinance as mpf
import ta
import pytz
from datetime import datetime
from telegram import Update, ParseMode, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext

# --- Bagian untuk Web Server (Agar Replit Tetap Aktif) ---
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot sedang aktif."

def run():
  app.run(host='0.0.0.0',port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
# ---------------------------------------------------------


# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CRYPTOCOMPARE_API_KEY = os.environ.get('CRYPTOCOMPARE_API_KEY') 

# --- FUNGSI ANALISIS SENTIMEN (PERBAIKAN FINAL - MENGGUNAKAN VOLUME) ---
def get_market_sentiment(symbol: str):
    print(f"--- Memulai Analisis Sentimen untuk: {symbol} (Metode Volume) ---")
    if not CRYPTOCOMPARE_API_KEY:
        print("DEBUG: CryptoCompare API Key tidak ditemukan.")
        return {"status": "error", "message": "CryptoCompare API Key tidak dikonfigurasi."}
    
    try:
        # Menggunakan endpoint yang lebih andal: data volume 24 jam
        url = f'https://min-api.cryptocompare.com/data/pricemultifull?fsyms={symbol.upper()}&tsyms=USDT&api_key={CRYPTOCOMPARE_API_KEY}'
        print(f"DEBUG: Menghubungi URL: {url}")
        
        response = requests.get(url)
        response.raise_for_status()
        
        data = response.json()
        print(f"DEBUG: Respon mentah dari API: {data}")

        raw_data = data.get('RAW', {}).get(symbol.upper(), {}).get('USDT', {})
        
        if not raw_data:
            print(f"DEBUG: Tidak ada data volume untuk {symbol}.")
            return {"status": "neutral", "message": f"Sentimen untuk {symbol} tidak ditemukan."}

        volume_24h = raw_data.get('VOLUME24HOURTO', 0)
        print(f"DEBUG: Volume 24 Jam (USDT) terdeteksi: {volume_24h}")

        sentiment_score = 0
        sentiment_text = f"⚪ Netral (Volume: ${volume_24h:,.0f})"
        
        # Logika skor sentimen berdasarkan volume (angka ini bisa disesuaikan)
        if volume_24h > 500_000_000: # Di atas 500 juta USDT
            sentiment_score = 1
            sentiment_text = f"🟢 Tinggi (Volume: ${volume_24h:,.0f})"
        
        print("--- Analisis Sentimen Selesai ---")
        return {"status": "ok", "score": sentiment_score, "text": sentiment_text}

    except requests.exceptions.HTTPError as http_err:
        print(f"ERROR: HTTP error saat mengambil data sentimen: {http_err} - Response: {http_err.response.text}")
        return {"status": "error", "message": "Gagal terhubung ke API sentimen (HTTP Error)."}
    except Exception as e:
        print(f"ERROR: Error tak terduga di get_market_sentiment: {e}")
        return {"status": "neutral", "message": f"Sentimen untuk {symbol} tidak dapat diproses."}

# --- FUNGSI ANALISIS TEKNIKAL ---
def analyze_indicators(df: pd.DataFrame):
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

def determine_final_signal(analysis: dict, sentiment: dict):
    score = 0
    if "Bullish" in analysis['ma']: score += 1
    if "Bearish" in analysis['ma']: score -= 1
    if "Golden Cross" in analysis['macd']: score += 2
    if "Death Cross" in analysis['macd']: score -= 2
    if "Oversold" in analysis['rsi']: score += 1
    if "Overbought" in analysis['rsi']: score -= 1
    if sentiment.get('status') == 'ok':
        score += sentiment.get('score', 0)
    if score >= 2:
        return "🚨 SINYAL AKSI: BELI (BUY) 🚨"
    elif score <= -2:
        return "🚨 SINYAL AKSI: JUAL (SELL) 🚨"
    else:
        return "⚠️ SINYAL AKSI: TAHAN (HOLD) ⚠️"

# --- FUNGSI GENERATE & KIRIM ---
def generate_analysis_and_send(chat_id: int, pair: str, timeframe: str, context: CallbackContext):
    bot = context.bot
    try:
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
        if df.empty:
            bot.send_message(chat_id, text=f"Gagal menghasilkan analisis untuk {pair}, tidak cukup data.")
            return

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
        mpf.plot(
            df_for_plot, type='candle', style=s, title=f'Analisis {pair} - Timeframe {timeframe}',
            ylabel='Harga (USDT)', volume=True, mav=(9, 26), addplot=addplots,
            panel_ratios=(8, 3, 3), figscale=1.5, savefig=filename
        )
        
        sentiment_text = sentiment_analysis.get('text', 'Gagal dimuat.')
        caption = (
            f"📊 **Analisis: {pair} | {timeframe}**\n"
            f"*(Harga: `${harga_terkini:,.2f}` pada {waktu_sekarang})*\n\n"
            f"**Indikator Teknikal:**\n"
            f"1. **Moving Average**: {indicator_analysis['ma']}\n"
            f"2. **RSI**: {indicator_analysis['rsi']}\n"
            f"3. **MACD**: {indicator_analysis['macd']}\n\n"
            f"**Minat Pasar (Vol. 24 Jam)**: {sentiment_text}\n"
            f"------------------------------------\n"
            f"**{final_signal}**\n"
            f"------------------------------------\n\n"
            f"Gunakan `/chart btc 1h` untuk analisis lain."
        )
        with open(filename, 'rb') as photo:
            bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, parse_mode=ParseMode.MARKDOWN)
        os.remove(filename)
    except ccxt.BadSymbol:
        bot.send_message(chat_id, text=f"❌ Gagal: Pair `{pair}` tidak ditemukan. Coba `BTC/USDT`.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        print(f"Error di generate_analysis_and_send: {e}")
        bot.send_message(chat_id, text=f"Terjadi kesalahan internal saat memproses `{pair}`.", parse_mode=ParseMode.MARKDOWN)

# --- HANDLER PERINTAH TELEGRAM ---
def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    update.message.reply_text(
        f"👋 Halo, {user.first_name}!\n\n"
        "Gunakan perintah `/chart <pair> <timeframe>`.\n"
        "Contoh: `/chart btc 4h` atau `/chart eth/usdt 1d`"
    )

def chart_command(update: Update, context: CallbackContext):
    if len(context.args) != 2:
        update.message.reply_text("Format salah. Gunakan: `/chart <pair> <timeframe>`")
        return
    pair_input = context.args[0].upper()
    timeframe = context.args[1].lower()
    pair = f"{pair_input}/USDT" if '/' not in pair_input else pair_input
    wait_message = update.message.reply_text(f"⏳ Memproses `{pair}` timeframe `{timeframe}`...", parse_mode=ParseMode.MARKDOWN)
    try:
        generate_analysis_and_send(update.message.chat_id, pair, timeframe, context)
    finally:
        context.bot.delete_message(chat_id=update.message.chat_id, message_id=wait_message.message_id)

# --- FUNGSI UTAMA BOT ---
def main():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN tidak diset.")
        return
    
    keep_alive()
    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(CommandHandler("help", start_command))
    dispatcher.add_handler(CommandHandler("chart", chart_command))
    updater.start_polling()
    print("Bot interaktif berhasil dijalankan...")
    updater.idle()

if __name__ == "__main__":
    main()
