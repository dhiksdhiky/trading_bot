# scheduled_run.py
# VERSI FINAL UNTUK DIJALANKAN OLEH GITHUB ACTIONS
import os
import telegram
from telegram import ParseMode, Bot

# PERBAIKAN: Impor fungsi dengan nama yang benar dari main.py
from main import generate_chart_and_caption

# --- KONFIGURASI ---
PAIR_TO_ANALYZE = 'BTC/USDT'
TIMEFRAME_TO_ANALYZE = '4h'

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Buat objek context tiruan sederhana untuk kompatibilitas
class MockContext:
    def __init__(self, bot_instance):
        self.bot = bot_instance

def run_scheduled_job():
    """Fungsi utama untuk menjalankan tugas terjadwal."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: TELEGRAM_TOKEN atau TELEGRAM_CHAT_ID tidak diset.")
        return

    print(f"Memulai analisis terjadwal untuk {PAIR_TO_ANALYZE}...")
    bot = Bot(token=TELEGRAM_TOKEN)
    
    try:
        # PERBAIKAN: Panggil fungsi dengan nama yang baru
        filename, caption, symbol = generate_chart_and_caption(
            pair=PAIR_TO_ANALYZE,
            timeframe=TIMEFRAME_TO_ANALYZE
        )
        
        if not filename:
            print(f"Gagal menghasilkan chart: {caption}")
            return

        # Kirim foto dengan caption (tanpa tombol interaktif)
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
