import os
import io
import asyncpg
import pandas as pd

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
DATABASE_URL = os.getenv("DATABASE_URL")
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
            DATABASE_URL,
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
        # Pengecekan argumen dasar
        if len(context.args) < 2:
            raise ValueError("Kekurangan argumen")

        amount = float(context.args[0])
        category = context.args[1]
        note = " ".join(context.args[2:]) if len(context.args) > 2 else ""

        await add_transaction(
            update.effective_user.id,
            "masuk",
            amount,
            category,
            note
        )

        await update.message.reply_text(
            "Pemasukan berhasil disimpan."
        )

    # Tangkap error jika input user bukan angka (misal: /masuk seratus ...)
    except ValueError:
        await update.message.reply_text(
            "Format salah!\nPastikan jumlah uang berupa angka tanpa titik/koma.\nContoh: /masuk 100000 Gaji Bulanan"
        )
    
    # Tangkap error sistem (biasanya masalah database)
    except Exception as e:
        print("ERROR DI FUNGSI MASUK:", str(e)) # Ini akan muncul di log Vercel
        await update.message.reply_text(
            f"Gagal menyimpan ke database. Error: {str(e)}"
        )

async def keluar(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        # Pengecekan argumen dasar: minimal harus ada jumlah dan kategori
        if len(context.args) < 2:
            raise ValueError("Kekurangan argumen")

        amount = float(context.args[0])
        category = context.args[1]
        note = " ".join(context.args[2:]) if len(context.args) > 2 else ""

        await add_transaction(
            update.effective_user.id,
            "keluar", # Tipe transaksi diset sebagai keluar
            amount,
            category,
            note
        )

        await update.message.reply_text(
            "Pengeluaran berhasil disimpan."
        )

    # Tangkap error jika input jumlah uang bukan angka atau argumen kurang
    except ValueError:
        await update.message.reply_text(
            "Format salah!\nPastikan jumlah uang berupa angka tanpa titik/koma.\nContoh: /keluar 50000 Makan"
        )
    
    # Tangkap error sistem, terutama jika query ke PostgreSQL gagal
    except Exception as e:
        print("ERROR DI FUNGSI KELUAR:", str(e)) # Membantu melacak error di log Vercel
        await update.message.reply_text(
            f"Gagal menyimpan ke database. Error: {str(e)}"
        )
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
