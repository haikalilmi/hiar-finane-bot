import os
import io
import asyncpg
import pandas as pd
import re
import dj_database_url  # Tambahkan import ini di bagian atas file

from datetime import datetime

from fastapi import FastAPI, Request

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# ==========================================
# CONFIG
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

app = FastAPI()

db_pool = None

telegram_app = Application.builder().token(BOT_TOKEN).build()

async def error_handler(update, context):
    print("================================")
    print("GLOBAL ERROR")
    print(context.error)
    print("================================")

telegram_app.add_error_handler(error_handler)

# ==========================================
# DATABASE
# ==========================================

async def get_pool():
    global db_pool

    if db_pool is None:
        db_pool = await asyncpg.create_pool(
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            database=DB_NAME,
            port=int(DB_PORT),
            min_size=1,
            max_size=5
        )

    return db_pool


async def add_transaction(
    user_id,
    trx_type,
    amount,
    category,
    note
):
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO transactions
            (user_id,type,amount,category,note)
            VALUES($1,$2,$3,$4,$5)
            """,
            user_id,
            trx_type,
            amount,
            category,
            note
        )


# ==========================================
# COMMANDS
# ==========================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        """
Selamat datang.

Format:

/masuk 100000 Gaji Bulanan
/keluar 50000 Makan Siang

/summary
/export
"""
    )

async def test(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "TEST BERHASIL"
    )

async def masuk(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        # 1. Bersihkan spasi-spasi aneh (unicode/NBSP) menjadi spasi normal
        clean_text = re.sub(r'\s+', ' ', update.message.text).strip()
        
        # 2. Pisahkan teks berdasarkan spasi normal
        args = clean_text.split(' ')

        # Karena kata pertama adalah '/masuk', maka minimal harus ada 3 elemen 
        # contoh: ['/masuk', '10000000', 'gaji'] -> panjangnya 3
        if len(args) < 3:
            raise ValueError("Kekurangan argumen")

        # 3. Ambil angka (elemen indeks ke-1) dan bersihkan dari titik/koma jika ada
        amount_str = args[1].replace(".", "").replace(",", "").strip()
        amount = float(amount_str)
        
        # 4. Ambil kategori (elemen indeks ke-2)
        category = args[2]
        
        # 5. Ambil sisa teks sebagai catatan (jika ada)
        note = " ".join(args[3:]) if len(args) > 3 else ""

        # Lakukan debug print untuk melihat hasil parser di log Vercel
        print(f"PARSED SUCCESS -> Amount: {amount}, Category: {category}, Note: {note}")

        await add_transaction(
            update.effective_user.id,
            "masuk",
            amount,
            category,
            note
        )

        await update.message.reply_text("Pemasukan berhasil disimpan.")

    except ValueError as val_err:
        print(f"DEBUG MASUK (ValueError) - Teks: '{update.message.text}' | Detail: {str(val_err)}")
        await update.message.reply_text(
            "Format salah!\nPastikan jumlah uang berupa angka tanpa titik/koma.\nContoh: /masuk 100000 Gaji"
        )
    except Exception as e:
        print("ERROR SISTEM DI FUNGSI MASUK:", str(e))
        await update.message.reply_text(f"Gagal menyimpan ke database. Error: {str(e)}")


async def keluar(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        clean_text = re.sub(r'\s+', ' ', update.message.text).strip()
        args = clean_text.split(' ')

        if len(args) < 3:
            raise ValueError("Kekurangan argumen")

        amount_str = args[1].replace(".", "").replace(",", "").strip()
        amount = float(amount_str)
        
        category = args[2]
        note = " ".join(args[3:]) if len(args) > 3 else ""

        print(f"PARSED SUCCESS -> Amount: {amount}, Category: {category}, Note: {note}")

        await add_transaction(
            update.effective_user.id,
            "keluar",
            amount,
            category,
            note
        )

        await update.message.reply_text("Pengeluaran berhasil disimpan.")

    except ValueError as val_err:
        print(f"DEBUG KELUAR (ValueError) - Teks: '{update.message.text}' | Detail: {str(val_err)}")
        await update.message.reply_text(
            "Format salah!\nPastikan jumlah uang berupa angka tanpa titik/koma.\nContoh: /keluar 50000 Makan"
        )
    except Exception as e:
        print("ERROR SISTEM DI FUNGSI KELUAR:", str(e))
        await update.message.reply_text(f"Gagal menyimpan ke database. Error: {str(e)}")

async def summary(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    keyboard = [
        [
            InlineKeyboardButton(
                "Hari Ini",
                callback_data="today"
            )
        ],
        [
            InlineKeyboardButton(
                "Bulan Ini",
                callback_data="month"
            )
        ],
        [
            InlineKeyboardButton(
                "Semua",
                callback_data="all"
            )
        ]
    ]

    await update.message.reply_text(
        "Pilih laporan:",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


async def summary_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    try:
        await query.answer()

        user_id = query.from_user.id

        pool = await get_pool()

        filter_sql = ""

        if query.data == "today":
            filter_sql = "AND DATE(created_at) = CURRENT_DATE"

        elif query.data == "month":
            filter_sql = """
            AND DATE_TRUNC('month', created_at)
            =
            DATE_TRUNC('month', NOW())
            """

        sql = f"""
        SELECT
            type,
            COALESCE(SUM(amount),0) AS total
        FROM transactions
        WHERE user_id = $1
        {filter_sql}
        GROUP BY type
        """

        print("RUNNING SQL:")
        print(sql)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                sql,
                user_id
            )

        print("ROWS:", rows)

        masuk_total = 0
        keluar_total = 0

        for row in rows:

            if row["type"] == "masuk":
                masuk_total = float(row["total"])

            elif row["type"] == "keluar":
                keluar_total = float(row["total"])

        saldo = masuk_total - keluar_total

        text = (
            f"📊 Ringkasan\n\n"
            f"💰 Pemasukan : {masuk_total:,.0f}\n"
            f"💸 Pengeluaran : {keluar_total:,.0f}\n"
            f"🏦 Saldo : {saldo:,.0f}"
        )

        await query.edit_message_text(text)

    except Exception as e:

        print("SUMMARY CALLBACK ERROR:")
        print(str(e))

        await query.message.reply_text(
            f"ERROR:\n{str(e)}"
        )


async def export_excel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    pool = await get_pool()

    async with pool.acquire() as conn:

        rows = await conn.fetch(
            """
            SELECT
            created_at,
            type,
            amount,
            category,
            note
            FROM transactions
            WHERE user_id=$1
            ORDER BY created_at DESC
            """,
            user_id
        )

    df = pd.DataFrame(
        [dict(r) for r in rows]
    )

    output = io.BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:
        df.to_excel(
            writer,
            index=False
        )

    output.seek(0)

    await update.message.reply_document(
        document=InputFile(
            output,
            filename="laporan.xlsx"
        )
    )

# ==========================================
# REGISTER HANDLER
# ==========================================

telegram_app.add_handler(
    CommandHandler("start", start)
)

telegram_app.add_handler(
    CommandHandler("test", test)
)

telegram_app.add_handler(
    CommandHandler("masuk", masuk)
)

telegram_app.add_handler(
    CommandHandler("keluar", keluar)
)

telegram_app.add_handler(
    CommandHandler("summary", summary)
)

telegram_app.add_handler(
    CallbackQueryHandler(
        summary_callback
    )
)

telegram_app.add_handler(
    CommandHandler("export", export_excel)
)

# ==========================================
# FASTAPI
# ==========================================

@app.get("/")
async def root():
    return {
        "status": "running"
    }


@app.post("/webhook")
async def webhook(
    request: Request
):
    try:

        data = await request.json()

        print("================================")
        print("UPDATE MASUK")
        print(data)
        print("================================")

        update = Update.de_json(
            data,
            telegram_app.bot
        )

        await telegram_app.process_update(
            update
        )

        return {
            "ok": True
        }

    except Exception as e:

        print("WEBHOOK ERROR")
        print(str(e))

        return {
            "ok": False,
            "error": str(e)
        }


@app.on_event("startup")
async def startup():
    await telegram_app.initialize()
    await telegram_app.start()
