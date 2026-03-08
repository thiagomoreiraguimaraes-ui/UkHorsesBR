import os
import time
import logging
import threading
import requests
import pytz
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")
UK_TZ        = pytz.timezone("Europe/London")
BR_TZ        = pytz.timezone("America/Sao_Paulo")
HEADERS      = {
    "x-rapidapi-host": "horse-racing.p.rapidapi.com",
    "x-rapidapi-key":  RAPIDAPI_KEY,
}

app = Flask(__name__)
CORS(app)
_cache = {}

def deve_atualizar(date_str):
    if date_str not in _cache:
        return True
    _, saved_at = _cache[date_str]
    saved_dt = datetime.fromtimestamp(saved_at, UK_TZ)
    return saved_dt.date() != datetime.now(UK_TZ).date()

def buscar_e_salvar(date_str):
    try:
        r = requests.get(
            "https://horse-racing.p.rapidapi.com/racecards",
            headers=HEADERS,
            params={"date": date_str},
            timeout=10
        )
        r.raise_for_status()
        data     = r.json()
        corridas = list(data.values()) if isinstance(data, dict) else data
        _cache[date_str] = (corridas, time.time())
        log.info(f"Cache: {date_str} — {len(corridas)} corridas")
        return corridas
    except Exception as e:
        log.error(f"Erro API: {e}")
        return _cache[date_str][0] if date_str in _cache else []

@app.route("/racecards")
def racecards():
    date = request.args.get("date", datetime.now(UK_TZ).strftime("%Y-%m-%d"))
    corridas = buscar_e_salvar(date) if deve_atualizar(date) else _cache[date][0]
    return jsonify(corridas)

@app.route("/status")
def status():
    info = {"status": "ok", "cache": {}}
    for d, (corridas, ts) in _cache.items():
        info["cache"][d] = {
            "corridas": len(corridas),
            "salvo_em": datetime.fromtimestamp(ts, UK_TZ).strftime("%H:%M UK")
        }
    return jsonify(info)

IRLANDA = {
    "naas","leopardstown","curragh","the curragh","fairyhouse",
    "punchestown","gowran park","gowran","tipperary","cork",
    "limerick","galway","killarney","sligo","roscommon",
    "navan","dundalk","bellewstown","down royal","downpatrick",
    "clonmel","tramore","wexford","ballinrobe","listowel",
    "thurles","laytown","kilbeggan","mallow"
}
JUMP_TIPOS = {"CHS","HRD","NOV-CHS","NOV-HRD","NHF","NOV"}

def bandeira(course):
    return "🇮🇪" if course.lower().strip() in IRLANDA else "🇬🇧"

def tipo_corrida(title):
    t = title.lower()
    if "national hunt flat" in t or "nh flat" in t or "bumper" in t: return "NHF"
    if "novices" in t and "chase" in t:  return "NOV-CHS"
    if "novices" in t and "hurdle" in t: return "NOV-HRD"
    if "novices" in t:                   return "NOV"
    if "chase" in t:                     return "CHS"
    if "hurdle" in t:                    return "HRD"
    if "maiden" in t:                    return "MDN"
    if "handicap" in t:                  return "HCP"
    if "stakes" in t:                    return "STKS"
    if "conditions" in t:                return "COND"
    if "claiming" in t:                  return "CLM"
    if "selling" in t:                   return "SELL"
    return "FLAT"

def uk_para_brt(date_field):
    try:
        parts    = date_field.split(" ")
        y, mo, d = map(int, parts[0].split("-"))
        h, m     = map(int, parts[1][:5].split(":"))
        uk_dt    = UK_TZ.localize(datetime(y, mo, d, h, m))
        return uk_dt.astimezone(BR_TZ).strftime("%H:%M")
    except:
        return "??:??"

def get_corridas(date_str):
    return buscar_e_salvar(date_str) if deve_atualizar(date_str) else _cache[date_str][0]

def formatar(corridas, titulo, data_label, filtro=None):
    now_brt = datetime.now(BR_TZ).strftime("%H:%M")
    now_uk  = datetime.now(UK_TZ)
    fuso    = "BST" if bool(now_uk.dst()) else "GMT"
    linhas  = []
    uk_c = ie_c = 0

    for r in corridas:
        course = r.get("course", "?")
        tipo   = tipo_corrida(r.get("title", ""))
        flag   = bandeira(course)
        dist   = r.get("distance", "?")
        brt    = uk_para_brt(r.get("date", ""))

        if filtro == "FLAT" and tipo in JUMP_TIPOS: continue
        if filtro == "JUMP" and tipo not in JUMP_TIPOS: continue
        if filtro == "UK"   and flag != "🇬🇧": continue
        if filtro == "IE"   and flag != "🇮🇪": continue

        if flag == "🇮🇪": ie_c += 1
        else: uk_c += 1
        linhas.append({"s": brt, "t": f"{flag} {brt} - {course} - {tipo} - {dist}"})

    linhas.sort(key=lambda x: x["s"])
    txt  = f"🏇 *CORRIDAS UK & IRLANDA*\n"
    txt += f"📅 *{titulo}* — {data_label}\n"
    txt += f"🇧🇷 {now_brt} | 🇬🇧 {now_uk.strftime('%H:%M')} ({fuso})\n"
    txt += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    txt += "\n".join(l["t"] for l in linhas) if linhas else "_Nenhuma corrida._"
    txt += f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
    txt += f"🏁 {len(linhas)} corridas  |  🇬🇧 {uk_c}  🇮🇪 {ie_c}"
    return txt

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

if __name__ == "__main__":
    if BOT_TOKEN:
        threading.Thread(target=start_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
