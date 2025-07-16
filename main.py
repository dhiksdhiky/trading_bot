# main.py
# VERSI DENGAN INDIKATOR VOLUME DIKEMBALIKAN
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

# --- Bagian untuk Web Server & API Watchlist ---
from flask import Flask, request, jsonify
from threading import Thread

app = Flask('')
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")

# --- KONFIGURASI PENYIMPANAN JSON ---
DATA_DIR = "/app/data"
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")

os.makedirs(DATA_DIR, exist_ok=True)

def load_watchlist_db():
    try:
        with open(WATCHLIST_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_watchlist_db(data):
    with open(WATCHLIST_FILE, 'w') as f:
        json.dump(data, f, indent=4)

@app.route('/')
def home():
    return "Bot sedang aktif dan berjalan di Railway."

@app.route('/api/watchlist')
def get_watchlist_api():
    provided_key = request.args.get('secret')
    if provided_key != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    watchlist_data = load_watchlist_db()
    return jsonify(watchlist_data)

def run_web_server():
  port = int(os.environ.get("PORT", 8080))
  app.run(host='0.0.0.0', port=port)

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CRYPTOCOMPARE_API_KEY = os.environ.get('CRYPTOCOMPARE_API_KEY') 

# --- FUNGSI HELPER BARU & DIPERBARUI ---
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
    # MA
    if last['close'] > last['ma9'] and last['ma9'] > last['ma26']: analysis['ma'] = "🟢 Bullish"
    elif last['close'] < last['ma9'] and last['ma9'] < last['ma26']: analysis['ma'] = "🔴 Bearish"
    else: analysis['ma'] = "⚪ Netral"
    # RSI
    if last['rsi'] > 70: analysis['rsi'] = f"🔴 Overbought ({last['rsi']:.2f})"
    elif last['rsi'] < 30: analysis['rsi'] = f"🟢 Oversold ({last['rsi']:.2f})"
    else: analysis['rsi'] = f"⚪ Netral ({last['rsi']:.2f})"
    # MACD
    if prev['macd'] < prev['macd_signal'] and last['macd'] > last['macd_signal']: analysis['macd'] = "🟢 Golden Cross"
    elif prev['macd'] > prev['macd_signal'] and last['macd'] < last['macd_signal']: analysis['macd'] = "🔴 Death Cross"
    else: analysis['macd'] = "⚪ Netral"
    # Bollinger Bands
    analysis['bb_score'] = 0
    if last['close'] < last['bb_low']:
        analysis['bb'] = "🟢 Harga di bawah Lower Band"
        analysis['bb_score'] = 1
    elif last['close'] > last['bb_high']:
        analysis['bb'] = "🔴 Harga di atas Upper Band"
        analysis['bb_score'] = -1
    else:
        analysis['bb'] = "⚪ Harga di dalam Bands"
    # PEMBARUAN: Tambahkan kembali analisis Volume
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

# --- FUNGSI INTI ---
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
    
    # PEMBARUAN: Tambahkan kembali Volume ke caption
    caption = (
        f"📊 **Analisis: {pair} | {timeframe} ({change_str})**\n"
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

# --- HANDLER PERINTAH ---
def start_command(update: Update, context: CallbackContext):
    text = (
        "👋 **Selamat Datang di Bot Analisis Kripto v4!**\n\n"
        "Fitur baru: Bollinger Bands & Fear/Greed Index untuk sinyal yang lebih akurat.\n\n"
        "Gunakan `/help` untuk daftar perintah."
    )
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def help_command(update: Update, context: CallbackContext):
    text = (
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

    sentiment = get_fear_and_greed_index()

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
            bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
            df['bb_high'] = bb.bollinger_hband()
            df['bb_low'] = bb.bollinger_lband()
            df.dropna(inplace=True)
            
            if len(df) < 2:
                summary_text += f"`{tf}`: ⏳ Data tidak cukup.\n"
                continue

            analysis = analyze_indicators(df)
            signal = determine_final_signal(analysis, sentiment)
            
            df_period = df.tail(24)
            change_str = ""
            if len(df_period) >= 2:
                first_price = df_period['close'].iloc[0]
                last_price = df_period['close'].iloc[-1]
                change_pct = ((last_price - first_price) / first_price) * 100
                change_str = f"({change_pct:+.1f}%)"

            signal_emoji = "➡️"
            if "BELI" in signal: 
                signal_emoji = "🟢"
                has_buy = True
            if "JUAL" in signal: 
                signal_emoji = "🔴"
                has_sell = True

            summary_text += f"`{tf}`: {signal_emoji} {analysis['ma']} {change_str}\n"
        except Exception:
            summary_text += f"`{tf}`: ❌ Gagal dimuat.\n"
    
    final_verdict = "⚠️ **Kesimpulan: NETRAL / KONSOLIDASI**"
    if has_buy and not has_sell:
        final_verdict = "✅ **Kesimpulan: CENDERUNG BULLISH**"
    elif has_sell and not has_buy:
        final_verdict = "❌ **Kesimpulan: CENDERUNG BEARISH**"

    summary_text += f"\n{final_verdict}\n\n*Sentimen Pasar Global: {sentiment['text']}*"
    context.bot.edit_message_text(chat_id=update.message.chat_id, message_id=wait_message.message_id, text=summary_text, parse_mode=ParseMode.MARKDOWN)

# --- HANDLER WATCHLIST & TOMBOL ---
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

def add_command(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if not context.args:
        update.message.reply_text("Format salah. Gunakan: `/add <simbol>`")
        return
    symbol = context.args[0].upper()
    
    db = load_watchlist_db()
    if user_id not in db:
        db[user_id] = []
    
    if symbol not in db[user_id]:
        db[user_id].append(symbol)
        save_watchlist_db(db)
        update.message.reply_text(f"✅ `{symbol}` berhasil ditambahkan ke watchlist Anda.", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text(f"⚠️ `{symbol}` sudah ada di watchlist Anda.", parse_mode=ParseMode.MARKDOWN)

def remove_command(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if not context.args:
        update.message.reply_text("Format salah. Gunakan: `/remove <simbol>`")
        return
    symbol = context.args[0].upper()
    
    db = load_watchlist_db()
    if user_id in db and symbol in db[user_id]:
        db[user_id].remove(symbol)
        save_watchlist_db(db)
        update.message.reply_text(f"🗑️ `{symbol}` berhasil dihapus dari watchlist.", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text(f"❌ `{symbol}` tidak ditemukan di watchlist Anda.", parse_mode=ParseMode.MARKDOWN)

def watchlist_command(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    db = load_watchlist_db()
    if user_id in db and db[user_id]:
        coins = ", ".join([f"`{c}`" for c in db[user_id]])
        update.message.reply_text(f"❤️ **Watchlist Anda:**\n{coins}", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text("🤷 Watchlist Anda kosong. Gunakan `/add <simbol>` untuk menambahkan.", parse_mode=ParseMode.MARKDOWN)

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
        db = load_watchlist_db()
        if user_id not in db:
            db[user_id] = []
        if symbol not in db[user_id]:
            db[user_id].append(symbol)
            save_watchlist_db(db)
            query.message.reply_text(f"✅ `{symbol}` berhasil ditambahkan ke watchlist Anda.", parse_mode=ParseMode.MARKDOWN)
        else:
            query.message.reply_text(f"⚠️ `{symbol}` sudah ada di watchlist Anda.", parse_mode=ParseMode.MARKDOWN)

# --- FUNGSI UTAMA BOT ---
def main_bot():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN tidak diset. Bot tidak akan berjalan.")
        return
    
    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher
    
    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("chart", chart_command))
    dispatcher.add_handler(CommandHandler("analyze", analyze_command))
    dispatcher.add_handler(CommandHandler("news", news_command))
    dispatcher.add_handler(CommandHandler("add", add_command))
    dispatcher.add_handler(CommandHandler("remove", remove_command))
    dispatcher.add_handler(CommandHandler("watchlist", watchlist_command))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    
    print("Memulai polling untuk bot Telegram...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    main_bot()
