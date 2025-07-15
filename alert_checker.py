# alert_checker.py
# Skrip ini dijalankan oleh GitHub Actions untuk memantau harga
import os
import requests
import ccxt
import telegram
from datetime import datetime, timedelta

# --- KONFIGURASI ---
REPLIT_URL = os.environ.get("REPLIT_URL")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ALERT_THRESHOLD = 1.0 # Ambang batas peringatan dalam persen (%)

def get_watchlist_from_repl():
    """Mengambil data watchlist dari API di Replit."""
    try:
        url = f"{REPLIT_URL}/api/watchlist?secret={API_SECRET_KEY}"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Gagal mengambil watchlist dari Replit: {e}")
        return None

def get_price_change(symbol):
    """Mendapatkan perubahan harga dalam 1 jam terakhir."""
    try:
        # PERBAIKAN: Mengganti exchange ke KuCoin agar tidak diblokir
        exchange = ccxt.kucoin() 
        pair = f"{symbol}/USDT"
        
        # Ambil data 1 jam terakhir dengan interval 5 menit
        since = exchange.parse8601((datetime.utcnow() - timedelta(hours=1, minutes=10)).isoformat())
        ohlcv = exchange.fetch_ohlcv(pair, '5m', since=since, limit=12) # 12 candle * 5 menit = 1 jam
        
        if len(ohlcv) < 2:
            return 0.0

        start_price = ohlcv[0][4] # Harga penutupan candle pertama
        end_price = ohlcv[-1][4] # Harga penutupan candle terakhir
        
        if start_price == 0:
            return 0.0
            
        change = ((end_price - start_price) / start_price) * 100
        return change
    except Exception as e:
        print(f"Gagal mengambil data harga untuk {symbol}: {e}")
        return 0.0

def main():
    print("Memulai pengecekan harga...")
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    db_data = get_watchlist_from_repl()
    
    if not db_data:
        print("Gagal memuat data dari database. Keluar.")
        return

    watchlist = {k: v for k, v in db_data.items() if k.isdigit()}
    if not watchlist:
        print("Tidak ada pengguna di watchlist. Selesai.")
        return

    # Buat daftar unik koin untuk dicek agar tidak duplikasi API call
    unique_coins = set()
    for user_id, coins in watchlist.items():
        for coin in coins:
            unique_coins.add(coin)
            
    print(f"Koin yang akan dicek: {list(unique_coins)}")

    # Cek harga untuk setiap koin unik
    for coin in unique_coins:
        change = get_price_change(coin)
        print(f"Perubahan harga {coin} dalam 1 jam: {change:.2f}%")
        
        if abs(change) >= ALERT_THRESHOLD:
            direction = "naik" if change > 0 else "turun"
            emoji = "📈" if change > 0 else "📉"
            
            # Cari semua pengguna yang memantau koin ini
            for user_id, user_coins in watchlist.items():
                if coin in user_coins:
                    try:
                        message = (
                            f"🚨 **PERINGATAN HARGA** 🚨\n\n"
                            f"{emoji} `{coin}` telah **{direction} {abs(change):.2f}%** dalam 1 jam terakhir!"
                        )
                        bot.send_message(chat_id=int(user_id), text=message, parse_mode='Markdown')
                        print(f"Peringatan terkirim ke pengguna {user_id} untuk koin {coin}")
                    except Exception as e:
                        print(f"Gagal mengirim pesan ke {user_id}: {e}")
    
    print("Pengecekan harga selesai.")

if __name__ == "__main__":
    main()
