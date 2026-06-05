async def summary_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        print("=== CALLBACK MASUK ===")

        query = update.callback_query

        print("callback_data =", query.data)

        await query.answer()

        user_id = query.from_user.id

        pool = await get_pool()

        filter_sql = ""

        if query.data == "today":
            filter_sql = "AND DATE(created_at)=CURRENT_DATE"

        elif query.data == "month":
            filter_sql = """
            AND DATE_TRUNC('month', created_at)
            =
            DATE_TRUNC('month', NOW())
            """

        sql = f"""
        SELECT
            type,
            COALESCE(SUM(amount),0) total
        FROM transactions
        WHERE user_id=$1
        {filter_sql}
        GROUP BY type
        """

        print(sql)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                sql,
                user_id
            )

        print("ROWS =", rows)

        masuk_total = 0
        keluar_total = 0

        for r in rows:
            if r["type"] == "masuk":
                masuk_total = float(r["total"])

            if r["type"] == "keluar":
                keluar_total = float(r["total"])

        saldo = masuk_total - keluar_total

        text = f"""
Pemasukan : {masuk_total:,.0f}
Pengeluaran : {keluar_total:,.0f}
Saldo : {saldo:,.0f}
"""

        await query.edit_message_text(text)

        print("=== SELESAI ===")

    except Exception as e:
        print("ERROR SUMMARY CALLBACK:")
        print(str(e))

        try:
            await query.message.reply_text(
                f"ERROR:\n{str(e)}"
            )
        except:
            pass
