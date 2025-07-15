# main.py
# VERSI POWER-USER DENGAN SEMUA FITUR BARU (PERBAIKAN FINAL)
import os
import requests
import ccxt
import pandas as pd
import mplfinance as mpf
import ta
import pytz
import json
from datetime import datetime
from telegram import Update, ParseMode, Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler
from replit import db # Menggunakan database bawaan Replit

# --- Bagian untuk Web Server & API Watchlist ---
from flask import Flask, request, jsonify
from threading import Thread

app = Flask('')
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")

@app.route('/')
def home():
    return "Bot sedang aktif."

# Endpoint API untuk diakses oleh GitHub Actions
@app.route('/api/watchlist')
def get_watchlist_api():
    provided_key = request.args.get('secret')
    if provided_key != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    watchlist_data = {}
    try:
        for key in db.keys():
            # PERBAIKAN: Konversi ObservedList dari Replit DB ke list biasa
            watchlist_data[key] = list(db[key])
        return jsonify(watchlist_data)
    except Exception as e:
        print(f"Error saat memproses database untuk API: {e}")
        return jsonify({"error": "Internal server error while processing database"}), 500


def run():
  app.run(host='0.0.0.0',port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
# ---------------------------------------------------------

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CRYPTOCOMPARE_API_KEY = os.environ.get('CRYPTOCOMPARE_API_KEY') 

# --- FUNGSI HELPER (Analisis, Sinyal, dll) ---
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
    # Fungsi ini sekarang aman karena kita sudah memastikan df memiliki >= 2 baris
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

# --- FUNGSI INTI (Chart, Analisis, Berita) ---
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
        f"📊 **Analisis: {pair} | {timeframe}**\n"
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

# --- HANDLER PERINTAH ---
def start_command(update: Update, context: CallbackContext):
    text = (
        "👋 **Selamat Datang di Bot Analisis Kripto v3!**\n\n"
        "Berikut perintah yang tersedia:\n"
        "📈 `/chart <simbol> <timeframe>`\n"
        "   (Contoh: `/chart btc 4h`)\n\n"
        "🔭 `/analyze <simbol>`\n"
        "   (Menganalisis 15m, 1h, 4h, 1d)\n\n"
        "❤️ **Watchlist & Peringatan Harga:**\n"
        "   `/add <simbol>` - Tambah koin ke pantauan\n"
        "   `/remove <simbol>` - Hapus koin\n"
        "   `/watchlist` - Lihat daftar pantauan\n\n"
        "📰 `/news <simbol>`\n"
        "   (Menampilkan berita terbaru)"
    )
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def chart_command(update: Update, context: CallbackContext):
    if len(context.args) != 2:
        update.message.reply_text("Format salah. Gunakan: `/chart <simbol> <timeframe>`")
        return
    pair_input = context.args[0].upper()
    timeframe = context.args[1].lower()
    pair = f"{pair_input}/USDT" if '/' not in pair_input else pair_input
    
    wait_message = update.message.reply_text(f"⏳ Memproses `{pair}` timeframe `{timeframe}`...", parse_mode=ParseMode.MARKDOWN)
    
    try:
        filename, caption, symbol = generate_chart_and_caption(pair, timeframe)
        if not filename:
            context.bot.edit_message_text(chat_id=update.message.chat_id, message_id=wait_message.message_id, text=f"Gagal menghasilkan analisis untuk `{pair}`: {caption}", parse_mode=ParseMode.MARKDOWN)
            return

        keyboard = [
            [InlineKeyboardButton("Refresh 🔃", callback_data=f"refresh_{pair}_{timeframe}")],
            [
                InlineKeyboardButton("1H", callback_data=f"chart_{pair}_1h"),
                InlineKeyboardButton("4H", callback_data=f"chart_{pair}_4h"),
                InlineKeyboardButton("1D", callback_data=f"chart_{pair}_1d"),
            ],
            [InlineKeyboardButton("Tambah ke Watchlist ❤️", callback_data=f"add_{symbol}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        with open(filename, 'rb') as photo:
            context.bot.send_photo(chat_id=update.message.chat_id, photo=photo, caption=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        
        context.bot.delete_message(chat_id=update.message.chat_id, message_id=wait_message.message_id)
        os.remove(filename)
    except Exception as e:
        print(f"Error di chart_command: {e}")
        context.bot.edit_message_text(chat_id=update.message.chat_id, message_id=wait_message.message_id, text=f"Terjadi kesalahan: {e}", parse_mode=ParseMode.MARKDOWN)

def analyze_command(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Format salah. Gunakan: `/analyze <simbol>`")
        return
    symbol = context.args[0].upper()
    pair = f"{symbol}/USDT"
    timeframes = ['15m', '1h', '4h', '1d']
    
    wait_message = update.message.reply_text(f"🔬 Menganalisis `{symbol}` di berbagai timeframe...", parse_mode=ParseMode.MARKDOWN)
    
    summary_text = f"**Analisis Multi-Timeframe untuk {symbol}**\n\n"
    exchange = ccxt.kucoin()
    
    has_buy = False
    has_sell = False

    sentiment = get_market_sentiment(symbol) 

    for tf in timeframes:
        try:
            ohlcv = exchange.fetch_ohlcv(pair, timeframe=tf, limit=100)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df['ma9'] = ta.trend.sma_indicator(df['close'], window=9)
            df['ma26'] = ta.trend.sma_indicator(df['close'], window=26)
            df['rsi'] = ta.momentum.rsi(df['close'], window=14)
            macd = ta.trend.MACD(df['close'])
            df['macd'] = macd.macd()
            df['macd_signal'] = macd.macd_signal()
            df.dropna(inplace=True)
            
            if len(df) < 2:
                summary_text += f"`{tf}`: ⏳ Data tidak cukup.\n"
                continue

            analysis = analyze_indicators(df)
            signal = determine_final_signal(analysis, sentiment)
            
            signal_emoji = "➡️"
            if "BELI" in signal: 
                signal_emoji = "🟢"
                has_buy = True
            if "JUAL" in signal: 
                signal_emoji = "🔴"
                has_sell = True

            summary_text += f"`{tf}`: {signal_emoji} {analysis['ma']}, RSI {analysis['rsi'].split(' ')[1]}, MACD {analysis['macd'].split(' ')[1]}\n"
        except Exception:
            summary_text += f"`{tf}`: ❌ Gagal dimuat.\n"
    
    final_verdict = "⚠️ **Kesimpulan: NETRAL / KONSOLIDASI**"
    if has_buy and not has_sell:
        final_verdict = "✅ **Kesimpulan: CENDERUNG BULLISH**"
    elif has_sell and not has_buy:
        final_verdict = "❌ **Kesimpulan: CENDERUNG BEARISH**"

    summary_text += f"\n{final_verdict}"
    context.bot.edit_message_text(chat_id=update.message.chat_id, message_id=wait_message.message_id, text=summary_text, parse_mode=ParseMode.MARKDOWN)

def news_command(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Format salah. Gunakan: `/news <simbol>`")
        return
    symbol = context.args[0]
    update.message.reply_text(f"📰 Mencari berita terbaru untuk `{symbol}`...", parse_mode=ParseMode.MARKDOWN)
    
    try:
        url = f"https://min-api.cryptocompare.com/data/v2/news/?lang=EN&categories={symbol.upper()}&api_key={CRYPTOCOMPARE_API_KEY}"
        response = requests.get(url)
        response.raise_for_status()
        news_data = response.json()['Data'][:3] 
        
        if not news_data:
            update.message.reply_text(f"Tidak ada berita yang ditemukan untuk `{symbol}`.", parse_mode=ParseMode.MARKDOWN)
            return
            
        for news in news_data:
            text = f"**{news['title']}**\n\n_{news['source_info']['name']} - {datetime.fromtimestamp(news['published_on']).strftime('%d %b %Y')}_\n[Baca Selengkapnya]({news['url']})"
            update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
            
    except Exception as e:
        update.message.reply_text(f"Gagal mengambil berita: {e}")

# --- HANDLER WATCHLIST (Database) ---
def add_command(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if not context.args:
        update.message.reply_text("Format salah. Gunakan: `/add <simbol>`")
        return
    symbol = context.args[0].upper()
    
    if user_id not in db:
        db[user_id] = []
    
    user_watchlist = list(db[user_id])
    if symbol not in user_watchlist:
        user_watchlist.append(symbol)
        db[user_id] = user_watchlist
        update.message.reply_text(f"✅ `{symbol}` berhasil ditambahkan ke watchlist Anda.", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text(f"⚠️ `{symbol}` sudah ada di watchlist Anda.", parse_mode=ParseMode.MARKDOWN)

def remove_command(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if not context.args:
        update.message.reply_text("Format salah. Gunakan: `/remove <simbol>`")
        return
    symbol = context.args[0].upper()
    
    if user_id in db:
        user_watchlist = list(db[user_id])
        if symbol in user_watchlist:
            user_watchlist.remove(symbol)
            db[user_id] = user_watchlist
            update.message.reply_text(f"🗑️ `{symbol}` berhasil dihapus dari watchlist.", parse_mode=ParseMode.MARKDOWN)
        else:
            update.message.reply_text(f"❌ `{symbol}` tidak ditemukan di watchlist Anda.", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("🤷 Anda belum memiliki watchlist.", parse_mode=ParseMode.MARKDOWN)

def watchlist_command(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if user_id in db and db[user_id]:
        coins = ", ".join([f"`{c}`" for c in db[user_id]])
        update.message.reply_text(f"❤️ **Watchlist Anda:**\n{coins}", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("🤷 Watchlist Anda kosong. Gunakan `/add <simbol>` untuk menambahkan.", parse_mode=ParseMode.MARKDOWN)

# --- HANDLER TOMBOL INTERAKTIF ---
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    data = query.data
    action, params = data.split('_', 1)
    
    if action == "refresh":
        pair, timeframe = params.rsplit('_', 1)
        filename, caption, symbol = generate_chart_and_caption(pair, timeframe)
        if filename:
            with open(filename, 'rb') as photo:
                query.edit_message_media(media=InputMediaPhoto(photo, caption=caption, parse_mode=ParseMode.MARKDOWN), reply_markup=query.message.reply_markup)
            os.remove(filename)

    elif action == "chart":
        pair, timeframe = params.rsplit('_', 1)
        filename, caption, symbol = generate_chart_and_caption(pair, timeframe)
        if filename:
            keyboard = [
                [InlineKeyboardButton("Refresh 🔃", callback_data=f"refresh_{pair}_{timeframe}")],
                [
                    InlineKeyboardButton("1H", callback_data=f"chart_{pair}_1h"),
                    InlineKeyboardButton("4H", callback_data=f"chart_{pair}_4h"),
                    InlineKeyboardButton("1D", callback_data=f"chart_{pair}_1d"),
                ],
                [InlineKeyboardButton("Tambah ke Watchlist ❤️", callback_data=f"add_{symbol}")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            with open(filename, 'rb') as photo:
                query.edit_message_media(media=InputMediaPhoto(photo, caption=caption, parse_mode=ParseMode.MARKDOWN), reply_markup=reply_markup)
            os.remove(filename)

    elif action == "add":
        symbol = params
        user_id = str(query.from_user.id)
        if user_id not in db:
            db[user_id] = []
        user_watchlist = list(db[user_id])
        if symbol not in user_watchlist:
            user_watchlist.append(symbol)
            db[user_id] = user_watchlist
            query.message.reply_text(f"✅ `{symbol}` berhasil ditambahkan ke watchlist Anda.", parse_mode=ParseMode.MARKDOWN)
        else:
            query.message.reply_text(f"⚠️ `{symbol}` sudah ada di watchlist Anda.", parse_mode=ParseMode.MARKDOWN)

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
    dispatcher.add_handler(CommandHandler("analyze", analyze_command))
    dispatcher.add_handler(CommandHandler("news", news_command))
    dispatcher.add_handler(CommandHandler("add", add_command))
    dispatcher.add_handler(CommandHandler("remove", remove_command))
    dispatcher.add_handler(CommandHandler("watchlist", watchlist_command))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    
    updater.start_polling()
    print("Bot Power-User berhasil dijalankan...")
    updater.idle()

if __name__ == "__main__":
    main()
