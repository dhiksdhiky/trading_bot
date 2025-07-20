# main.py
# VERSI DENGAN SISTEM WATCHLIST HIBRIDA (INTI + PRIBADI)
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

# --- Bagian untuk Web Server & API ---
from flask import Flask, request, jsonify
from threading import Thread

app = Flask('')
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# --- KONFIGURASI PENYIMPANAN & WATCHLIST ---
DATA_DIR = "/app/data"
DB_FILE = os.path.join(DATA_DIR, "user_data.json")
CORE_WATCHLIST = ["BTC", "ETH", "SOL", "BNB", "DOGE", "AVAX", "XRP", "ADA", "DOT", "LINK"]

os.makedirs(DATA_DIR, exist_ok=True)

def load_db():
    try:
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

@app.route('/')
def home():
    return "Bot sedang aktif dan berjalan di Railway."

@app.route('/api/data')
def get_user_data_api():
    provided_key = request.args.get('secret')
    if provided_key != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_data = load_db()
    return jsonify({"users": user_data, "core_watchlist": CORE_WATCHLIST})

def run_web_server():
  port = int(os.environ.get("PORT", 8080))
  app.run(host='0.0.0.0', port=port)

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')

# --- FUNGSI HELPER (Tidak berubah) ---
def get_gemini_analysis(prompt: str):
    if not GEMINI_API_KEY: return "Analisis AI tidak tersedia."
    try:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(api_url, json=payload, timeout=45)
        response.raise_for_status()
        return response.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"Error saat berkomunikasi dengan Gemini: {e}")
        return "Gagal mendapatkan analisis dari AI."

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
        if "Extreme Fear" in classification or "Fear" in classification: sentiment_score, emoji = 1, "😨"
        elif "Extreme Greed" in classification or "Greed" in classification: sentiment_score, emoji = -1, "🤑"
        return {"status": "ok", "score": sentiment_score, "text": f"{emoji} {classification} ({value})"}
    except Exception as e:
        print(f"Error di get_fear_and_greed_index: {e}")
        return {"status": "error", "message": "Gagal memuat F&G Index."}

def analyze_indicators(df: pd.DataFrame, symbol: str):
    last, prev = df.iloc[-1], df.iloc[-2]
    analysis = {}
    if last['close'] > last['ma9'] and last['ma9'] > last['ma26']: analysis['ma'] = f"🟢 Bullish ({last['ma9']:.2f} > {last['ma26']:.2f})"
    elif last['close'] < last['ma9'] and last['ma9'] < last['ma26']: analysis['ma'] = f"🔴 Bearish ({last['ma9']:.2f} < {last['ma26']:.2f})"
    else: analysis['ma'] = "⚪ Netral"
    if last['rsi'] > 70: analysis['rsi'] = f"🔴 Overbought ({last['rsi']:.2f})"
    elif last['rsi'] < 30: analysis['rsi'] = f"🟢 Oversold ({last['rsi']:.2f})"
    else: analysis['rsi'] = f"⚪ Netral ({last['rsi']:.2f})"
    if prev['macd'] < prev['macd_signal'] and last['macd'] > last['macd_signal']: analysis['macd'] = "🟢 Golden Cross"
    elif prev['macd'] > prev['macd_signal'] and last['macd'] < last['macd_signal']: analysis['macd'] = "🔴 Death Cross"
    else: analysis['macd'] = "⚪ Netral"
    analysis['bb_score'] = 0
    if last['close'] < last['bb_low']:
        analysis['bb'] = f"🟢 Di bawah Lower Band ({last['bb_low']:.2f})"
        analysis['bb_score'] = 1
    elif last['close'] > last['bb_high']:
        analysis['bb'] = f"🔴 Di atas Upper Band ({last['bb_high']:.2f})"
        analysis['bb_score'] = -1
    else: analysis['bb'] = "⚪ Di dalam Bands"
    avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
    if last['volume'] > avg_volume * 1.75: analysis['volume'] = f"🔥 Tinggi ({last['volume']:,.0f} {symbol})"
    else: analysis['volume'] = f"⚪ Normal ({last['volume']:,.0f} {symbol})"
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
    if sentiment.get('status') == 'ok': score += sentiment.get('score', 0)
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
    df['macd'], df['macd_signal'], df['macd_hist'] = macd.macd(), macd.macd_signal(), macd.macd_diff()
    bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
    df['bb_high'], df['bb_low'] = bb.bollinger_hband(), bb.bollinger_lband()
    df.dropna(inplace=True)
    
    if len(df) < 2: return None, "Gagal menganalisis, data tidak cukup.", None

    symbol = pair.split('/')[0]
    indicator_analysis = analyze_indicators(df, symbol)
    sentiment_analysis = get_fear_and_greed_index()
    final_signal = determine_final_signal(indicator_analysis, sentiment_analysis)
    
    df_for_plot = df.tail(30)
    change_pct = ((df_for_plot['close'].iloc[-1] - df_for_plot['close'].iloc[0]) / df_for_plot['close'].iloc[0]) * 100
    change_emoji = "📈" if change_pct >= 0 else "📉"
    change_str = f"{change_emoji} {change_pct:+.2f}%"

    prompt = f"Anda adalah seorang analis teknikal kripto profesional. Berikan ringkasan analisis pasar singkat (maksimal 3 kalimat) dalam bahasa Indonesia berdasarkan data ini untuk {pair} {timeframe}: MA: {indicator_analysis['ma']}, RSI: {indicator_analysis['rsi']}, MACD: {indicator_analysis['macd']}, Bollinger Bands: {indicator_analysis['bb']}, Volume: {indicator_analysis['volume']}. Fokus pada kesimpulan utama."
    ai_summary = get_gemini_analysis(prompt)

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
    
    harga_terkini_usd = df['close'].iloc[-1]
    harga_terkini_idr_str = "N/A"
    try:
        ticker_idr = ccxt.indodax().fetch_ticker('USDT/IDR')
        harga_terkini_idr = harga_terkini_usd * ticker_idr['last']
        harga_terkini_idr_str = f"Rp {harga_terkini_idr:,.0f}"
    except Exception as e: print(f"Gagal mengambil harga IDR: {e}")

    waktu_sekarang = datetime.now(pytz.timezone('Asia/Jakarta')).strftime('%d %b %Y, %H:%M WIB')
    filename = f'analysis_{pair.replace("/", "")}_{timeframe}.png'
    mpf.plot(df_for_plot, type='candle', style=s, title=f'Analisis {pair} - Timeframe {timeframe}', ylabel='Harga (USDT)', volume=True, mav=(9, 26), addplot=addplots, panel_ratios=(8, 3, 3), figscale=1.5, savefig=filename)
    
    caption = (
        f"📊 **Analisis: {pair} | {timeframe} ({change_str})**\n"
        f"*(Harga: **{harga_terkini_idr_str}** | **${harga_terkini_usd:,.2f}** pada {waktu_sekarang})*\n\n"
        f"**Indikator Teknikal:**\n"
        f"1. **Moving Average**: {indicator_analysis['ma']}\n"
        f"2. **RSI**: {indicator_analysis['rsi']}\n"
        f"3. **MACD**: {indicator_analysis['macd']}\n"
        f"4. **Bollinger Bands**: {indicator_analysis['bb']}\n"
        f"5. **Volume**: {indicator_analysis['volume']}\n\n"
        f"**🧠 Analisis AI:**\n_{ai_summary}_\n\n"
        f"**Sentimen Pasar**: {sentiment_analysis['text']}\n"
        f"------------------------------------\n"
        f"**{final_signal}**"
    )
    return filename, caption, symbol

# --- HANDLER PERINTAH ---
def start_command(update: Update, context: CallbackContext):
    update.message.reply_text("👋 **Selamat Datang di Bot Sinyal Hibrida!**\n\nBot ini memantau koin inti dan watchlist pribadi Anda, serta dapat memberikan Sinyal Eksekusi & Peringatan Dini.\n\nGunakan `/help` untuk melihat semua perintah.", parse_mode=ParseMode.MARKDOWN)

def help_command(update: Update, context: CallbackContext):
    text = (
        "**Perintah yang Tersedia:**\n\n"
        "📈 `/chart <simbol>` - Analisis detail (default 4 jam)\n"
        "ℹ️ `/info` - Penjelasan singkat tentang indikator\n\n"
        "**Watchlist:**\n"
        "❤️ `/add <simbol>` - Tambah koin ke pantauan pribadi\n"
        "💔 `/remove <simbol>` - Hapus koin dari pantauan pribadi\n"
        "📋 `/watchlist` - Lihat daftar pantauan Anda\n\n"
        "**Auto-Signal:**\n"
        "🎯 `/strategy list` - Lihat status notifikasi Anda\n"
        "🔔 `/strategy toggle_alert <nama>` - Aktifkan/nonaktifkan Peringatan Dini\n"
        "✅ `/strategy toggle_signal <nama>` - Aktifkan/nonaktifkan Sinyal Eksekusi"
    )
    if update.callback_query: update.callback_query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    else: update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def info_command(update: Update, context: CallbackContext):
    text = (
        "**ℹ️ Penjelasan Singkat Indikator Teknikal**\n\n"
        "1. **Moving Average (MA)**\nMenunjukkan arah tren harga rata-rata.\n\n"
        "2. **Relative Strength Index (RSI)**\n"
        "Mengukur momentum. Di atas 70 (Overbought), di bawah 30 (Oversold).\n\n"
        "3. **MACD**\n"
        "Mengukur momentum tren. 'Golden Cross' sinyal beli, 'Death Cross' sinyal jual.\n\n"
        "4. **Bollinger Bands (BB)**\n"
        "Mengukur volatilitas. Harga di luar pita menandakan pergerakan signifikan.\n\n"
        "5. **Volume**\n"
        "Jumlah koin yang diperdagangkan. Volume tinggi mengkonfirmasi tren."
    )
    if update.callback_query: update.callback_query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    else: update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def chart_command(update: Update, context: CallbackContext):
    if len(context.args) != 1:
        update.message.reply_text("Format salah. Gunakan: `/chart <simbol>`")
        return
    
    pair_input = context.args[0].upper()
    timeframe = '4h'
    pair = f"{pair_input}/USDT" if '/' not in pair_input else pair_input
    
    wait_message = update.message.reply_text(f"⏳ Menganalisis `{pair}` dengan AI...", parse_mode=ParseMode.MARKDOWN)
    
    try:
        filename, caption, symbol = generate_chart_and_caption(pair, timeframe)
        if not filename:
            context.bot.edit_message_text(chat_id=update.message.chat_id, message_id=wait_message.message_id, text=f"Gagal: {caption}", parse_mode=ParseMode.MARKDOWN)
            return

        keyboard = [
            [
                InlineKeyboardButton("Refresh 🔃", callback_data=f"refresh_{pair}_{timeframe}"),
                InlineKeyboardButton("Info Indikator ℹ️", callback_data="show_info")
            ],
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

# --- HANDLER WATCHLIST & STRATEGI ---
def add_command(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if not context.args:
        update.message.reply_text("Format: `/add <simbol>`")
        return
    symbol = context.args[0].upper()
    
    db = load_db()
    if user_id not in db:
        db[user_id] = {"watchlist": [], "strategies": {}}
    if "watchlist" not in db[user_id]:
        db[user_id]["watchlist"] = []
    
    if symbol not in db[user_id]["watchlist"]:
        db[user_id]["watchlist"].append(symbol)
        save_db(db)
        update.message.reply_text(f"✅ `{symbol}` ditambahkan ke watchlist pribadi.", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text(f"⚠️ `{symbol}` sudah ada di watchlist pribadi.", parse_mode=ParseMode.MARKDOWN)

def remove_command(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if not context.args:
        update.message.reply_text("Format: `/remove <simbol>`")
        return
    symbol = context.args[0].upper()
    
    db = load_db()
    if user_id in db and symbol in db[user_id].get("watchlist", []):
        db[user_id]["watchlist"].remove(symbol)
        save_db(db)
        update.message.reply_text(f"🗑️ `{symbol}` dihapus dari watchlist pribadi.", parse_mode=ParseMode.MARKDOWN)
    else:
        update.message.reply_text(f"❌ `{symbol}` tidak ditemukan di watchlist pribadi.", parse_mode=ParseMode.MARKDOWN)

def watchlist_command(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    db = load_db()
    
    text = f"❤️ **Watchlist Inti (Dipantau Otomatis):**\n"
    text += ", ".join([f"`{c}`" for c in CORE_WATCHLIST])
    
    user_watchlist = db.get(user_id, {}).get("watchlist", [])
    if user_watchlist:
        text += "\n\n📋 **Watchlist Pribadi Anda:**\n"
        text += ", ".join([f"`{c}`" for c in user_watchlist])
    else:
        text += "\n\n🤷 Anda belum memiliki watchlist pribadi. Gunakan `/add <simbol>`."
        
    update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

def strategy_command(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    args = context.args
    AVAILABLE_STRATEGIES = {
        "pullback_buy": "Sinyal Beli saat koreksi di tren naik.",
        "breakdown_sell": "Sinyal Jual saat tembus support di tren turun."
    }
    
    if not args or args[0] not in ['list', 'toggle_alert', 'toggle_signal']:
        update.message.reply_text("Format salah. Gunakan `/strategy list`, `toggle_alert <nama>`, atau `toggle_signal <nama>`.")
        return

    sub_command = args[0]
    db = load_db()

    if user_id not in db:
        db[user_id] = {"watchlist": [], "strategies": {}}

    if sub_command == 'list':
        text = "**Status Notifikasi Strategi Anda:**\n\n"
        user_strategies = db.get(user_id, {}).get("strategies", {})
        for name, desc in AVAILABLE_STRATEGIES.items():
            prefs = user_strategies.get(name, {})
            alert_status = "✅ Aktif" if prefs.get("alert_on", False) else "❌ Nonaktif"
            signal_status = "✅ Aktif" if prefs.get("signal_on", False) else "❌ Nonaktif"
            text += f"**{name}**\n_{desc}_\n- Peringatan Dini: {alert_status}\n- Sinyal Eksekusi: {signal_status}\n\n"
        update.message.reply_text(text)
        return

    if sub_command in ['toggle_alert', 'toggle_signal']:
        if len(args) < 2 or args[1] not in AVAILABLE_STRATEGIES:
            update.message.reply_text("Nama strategi tidak valid.")
            return
        
        strategy_name = args[1]
        toggle_type = "alert_on" if sub_command == 'toggle_alert' else "signal_on"
        
        if "strategies" not in db[user_id]: db[user_id]["strategies"] = {}
        if strategy_name not in db[user_id]["strategies"]: db[user_id]["strategies"][strategy_name] = {}
            
        current_status = db[user_id]["strategies"][strategy_name].get(toggle_type, False)
        db[user_id]["strategies"][strategy_name][toggle_type] = not current_status
        save_db(db)
        
        type_text = "Peringatan Dini" if toggle_type == "alert_on" else "Sinyal Eksekusi"
        new_status = "diaktifkan" if not current_status else "dinonaktifkan"
        update.message.reply_text(f"{type_text} untuk `{strategy_name}` berhasil {new_status}.", parse_mode=ParseMode.MARKDOWN)

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    
    if data == "show_info":
        info_command(update, context)
        return
    
    if data == "show_help":
        help_command(update, context)
        return

    action, params = data.split('_', 1)
    
    if action == "refresh" or action == "chart":
        pair, timeframe = params.rsplit('_', 1)
        query.edit_message_caption(caption=f"⏳ Memuat ulang {pair} timeframe {timeframe}...")
        
        filename, caption, symbol = generate_chart_and_caption(pair, timeframe)
        if filename:
            keyboard = [
                [
                    InlineKeyboardButton("Refresh 🔃", callback_data=f"refresh_{pair}_{timeframe}"),
                    InlineKeyboardButton("Info Indikator ℹ️", callback_data="show_info")
                ],
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
        # Re-use add_command logic
        class MockMessage:
            def __init__(self, text):
                self.text = text
                self.from_user = query.from_user
            def reply_text(self, text, parse_mode):
                context.bot.send_message(chat_id=query.message.chat_id, text=text, parse_mode=parse_mode)

        class MockUpdate:
            def __init__(self, text):
                self.effective_user = query.from_user
                self.message = MockMessage(text)

        mock_update = MockUpdate(f"/add {symbol}")
        context.args = [symbol]
        add_command(mock_update, context)


# --- FUNGSI UTAMA BOT ---
def main_bot():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN tidak diset.")
        return
    
    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher
    
    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("info", info_command))
    dispatcher.add_handler(CommandHandler("chart", chart_command))
    dispatcher.add_handler(CommandHandler("add", add_command))
    dispatcher.add_handler(CommandHandler("remove", remove_command))
    dispatcher.add_handler(CommandHandler("watchlist", watchlist_command))
    dispatcher.add_handler(CommandHandler("strategy", strategy_command))
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot Sinyal Hibrida berhasil dijalankan...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    web_thread = Thread(target=run_web_server)
    web_thread.start()
    main_bot()
