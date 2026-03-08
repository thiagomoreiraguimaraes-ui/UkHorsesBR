def start_bot():
    import asyncio
    from telegram import Update, ReplyKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

    MENU = ReplyKeyboardMarkup(
        [["🗓 Hoje","🗓 Amanhã"],["⚡ Flat","🌿 Jump"],
         ["🇬🇧 Só UK","🇮🇪 Só Irlanda"],["🏇 Todas","🕐 Horário"]],
        resize_keyboard=True, is_persistent=True
    )

    async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        now_uk  = datetime.now(UK_TZ)
        now_brt = datetime.now(BR_TZ)
        diff    = int((now_uk.utcoffset() - now_brt.utcoffset()).total_seconds() / 3600)
        dst     = bool(now_uk.dst())
        await update.message.reply_text(
            f"🐴 *Bem-vindo ao UKHorsesBR!*\n\n"
            f"Corridas de UK & Irlanda em horário de Brasília.\n\n"
            f"🕐 🇬🇧 `{now_uk.strftime('%H:%M')}` → 🇧🇷 `{now_brt.strftime('%H:%M')}`\n"
            f"UK está *{diff}h à frente* ({'BST verão' if dst else 'GMT inverno'})\n\n"
            f"Use os botões abaixo 👇",
            parse_mode="Markdown", reply_markup=MENU
        )

    async def handler_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        texto  = update.message.text
        hoje   = datetime.now(UK_TZ).strftime("%Y-%m-%d")
        amanha = (datetime.now(UK_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
        dl_h   = datetime.now(UK_TZ).strftime("%d/%m/%Y")
        dl_a   = (datetime.now(UK_TZ) + timedelta(days=1)).strftime("%d/%m/%Y")

        async def responder(date_str, titulo, dl, filtro=None):
            msg = await update.message.reply_text("⏳ Buscando...")
            corridas = get_corridas(date_str)
            await msg.delete()
            if not corridas:
                await update.message.reply_text("❌ Nenhuma corrida.", reply_markup=MENU)
                return
            await update.message.reply_text(
                formatar(corridas, titulo, dl, filtro=filtro),
                parse_mode="Markdown", reply_markup=MENU
            )

        if   texto == "🗓 Hoje":        await responder(hoje,   "HOJE",       dl_h)
        elif texto == "🗓 Amanhã":      await responder(amanha, "AMANHÃ",     dl_a)
        elif texto == "⚡ Flat":        await responder(hoje,   "FLAT",       dl_h, "FLAT")
        elif texto == "🌿 Jump":        await responder(hoje,   "JUMP",       dl_h, "JUMP")
        elif texto == "🇬🇧 Só UK":      await responder(hoje,   "SÓ UK",      dl_h, "UK")
        elif texto == "🇮🇪 Só Irlanda": await responder(hoje,   "SÓ IRLANDA", dl_h, "IE")
        elif texto == "🏇 Todas":       await responder(hoje,   "TODAS",      dl_h)
        elif texto == "🕐 Horário":
            now_uk  = datetime.now(UK_TZ)
            now_brt = datetime.now(BR_TZ)
            dst     = bool(now_uk.dst())
            diff    = int((now_uk.utcoffset() - now_brt.utcoffset()).total_seconds() / 3600)
            await update.message.reply_text(
                f"🕐 *HORÁRIO ATUAL*\n━━━━━━━━━━━━━━━━━━━━━\n"
                f"🇬🇧 `{now_uk.strftime('%H:%M')}` — {'BST' if dst else 'GMT'}\n"
                f"🇧🇷 `{now_brt.strftime('%H:%M')}` — Brasília\n\n"
                f"UK está *{diff}h à frente*",
                parse_mode="Markdown", reply_markup=MENU
            )

    async def run():
        telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
        telegram_app.add_handler(CommandHandler("start", cmd_start))
        telegram_app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, handler_menu
        ))
        log.info("🐴 Bot Telegram iniciado!")
        async with telegram_app:
            await telegram_app.start()
            await telegram_app.updater.start_polling(drop_pending_updates=True)
            await asyncio.Event().wait()

    asyncio.run(run())
