# scheduled_run.py
# SKRIP UNTUK DIJALANKAN OLEH GITHUB ACTIONS SESUAI JADWAL
import os
import telegram
from telegram import ParseMode, Bot

# Impor fungsi inti dari main.py agar tidak duplikasi kode
# Catatan: GitHub Actions tidak akan menjalankan bagian web server dari main.py
from main import generate_analysis_and_send

# --- KONFIGURASI ---
PAIR_TO_ANALYZE = 'BTC/USDT'
TIMEFRAME_TO_ANALYZE = '4h'

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

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
    mock_context = MockContext(bot)

    try:
        # Panggil fungsi inti dari main.py
        generate_analysis_and_send(
            chat_id=int(TELEGRAM_CHAT_ID),
            pair=PAIR_TO_ANALYZE,
            timeframe=TIMEFRAME_TO_ANALYZE,
            context=mock_context
        )
        print("Analisis terjadwal berhasil dikirim.")
    except Exception as e:
        print(f"Terjadi kesalahan saat menjalankan tugas terjadwal: {e}")
        error_message = f"Gagal menjalankan analisis terjadwal untuk {PAIR_TO_ANALYZE}.\nError: `{e}`"
        bot.send_message(chat_id=int(TELEGRAM_CHAT_ID), text=error_message, parse_mode=ParseMode.MARKDOWN)

if __name__ == "__main__":
    run_scheduled_job()
