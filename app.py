
import os
import time
import logging
import threading
import requests
import pytz
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ─── CONFIG ─────────────────────────────────────────────────────
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
BOT_TOKEN    = os.environ.get("BOT_TOKEN", "")

UK_TZ   = pytz.timezone("Europe/London")
BR_TZ   = pytz.timezone("America/Sao_Paulo")
HEADERS = {
    "x-rapidapi-host": "horse-racing.p.rapidapi.com",
    "x-rapidapi-key":  RAPIDAPI_KEY,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ─── FLASK ───────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

_cache = {}

def deve_atualizar(date_str):
    if date_str not in _cache:
        return True
    _, saved_at = _cache[date_str]
    saved_dt = datetime.fromtimestamp(saved_at, UK_TZ)
    now_uk   = datetime.now(UK_TZ)
    return saved_dt.date() != now_uk.date()

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
        log.info(f"Cache atualizado para {date_str}: {len(corridas)} corridas")
        return corridas
    except Exception as e:
        log.error(f"Erro API: {e}")
        if date_str in _cache:
            return _cache[date_str][0]
        return []

@app.route("/racecards")
def racecards():
    date = request.args.get("date", datetime.now(UK_TZ).strftime("%Y-%m-%d"))
    if deve_atualizar(date):
        corridas = buscar_e_salvar(date)
    else:
        corridas, _ = _cache[date]
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

# ─── BOT HELPERS ─────────────────────────────────────────────────
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
        if not date_field or len(date_field) < 16:
            return (None, None)
        parts    = date_field.split(" ")
        date_part = parts[0]
        time_part = parts[1][:5]
        h, m     = map(int, time_part.split(":"))
        y, mo, d = map(int, date_part.split("-"))
        uk_dt    = UK_TZ.localize(datetime(y, mo, d, h, m, 0))
        brt_dt   = uk_dt.astimezone(BR_TZ)
        return (uk_dt.strftime("%H:%M"), brt_dt.strftime("%H:%M"))
    except:
        return (None, None)

def buscar_corridas_bot(date_str=None):
    if not date_str:
        date_str = datetime.now(UK_TZ).strftime("%Y-%m-%d")
    if deve_atualizar(date_str):
        return buscar_e_salvar(date_str)
    return _cache[date_str][0]

def formatar_corridas(corridas, titulo, data_label, filtro=None):
    now_brt    = datetime.now(BR_TZ).strftime("%H:%M")
    now_uk     = datetime.now(UK_TZ)
    now_uk_str = now_uk.strftime("%H:%M")
    fuso       = "BST" if bool(now_uk.dst()) else "GMT"
    linhas     = []
    count_uk   = 0
    count_ie   = 0

    for r in corridas:
        date_field = r.get("date", "")
        _, brt     = uk_para_brt(date_field)
        course     = r.get("course", "?")
        dist       = r.get("distance", "?")
        tipo       = tipo_corrida(r.get("title", ""))
        flag       = bandeira(course)

        if filtro == "FLAT" and tipo in JUMP_TIPOS: continue
        if filtro == "JUMP" and tipo not in JUMP_TIPOS: continue
        if filtro == "UK"   and flag != "🇬🇧": continue
        if filtro == "IE"   and flag != "🇮🇪": continue

        if flag == "🇮🇪": count_ie += 1
        else: count_uk += 1

        hora = brt if brt else "??:??"
        linhas.append({"sort": brt or "99:99", "texto": f"{flag} {hora} - {course} - {tipo} - {dist}"})

    linhas.sort(key=lambda x: x["sort"])

    txt  = f"🏇 *CORRIDAS UK & IRLANDA*\n"
    txt += f"📅 *{titulo}* — {data_label}\n"
    txt += f"🇧🇷 {now_brt} | 🇬🇧 {now_uk_str} ({fuso})\n"
    txt += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    txt += "\n".join(l["texto"] for l in linhas) if linhas else "_Nenhuma corrida encontrada._"
    txt += f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
    txt += f"🏁 {len(linhas)} corridas  |  🇬🇧 {count_uk}  🇮🇪 {count_ie}"
    return txt

# ─── BOT MENU ────────────────────────────────────────────────────
MENU = ReplyKeyboardMarkup(
    [["🗓 Hoje","🗓 Amanhã"],["⚡ Flat","🌿 Jump"],
     ["🇬🇧 Só UK","🇮🇪 Só Irlanda"],["🏇 Todas","🕐 Horário"]],
    resize_keyboard=True, is_persistent=True,
    input_field_placeholder="Escolha uma opção..."
)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now_uk  = datetime.now(UK_TZ)
    now_brt = datetime.now(BR_TZ)
    diff    = int((now_uk.utcoffset() - now_brt.utcoffset()).total_seconds() / 3600)
    dst     = bool(now_uk.dst())
    await update.message.reply_text(
        f"🐴 *Bem-vindo ao UKHorsesBR!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Corridas de UK & Irlanda com horários em Brasília.\n\n"
        f"🕐 *Agora:* 🇬🇧 `{now_uk.strftime('%H:%M')}` → 🇧🇷 `{now_brt.strftime('%H:%M')}`\n"
        f"🌍 UK está *{diff}h à frente* do Brasil ({'BST verão' if dst else 'GMT inverno'})\n\n"
        f"Use os botões abaixo! 👇",
        parse_mode="Markdown", reply_markup=MENU
    )

async def handler_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto  = update.message.text
    hoje   = datetime.now(UK_TZ).strftime("%Y-%m-%d")
    amanha = (datetime.now(UK_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
    dl_hoje   = datetime.now(UK_TZ).strftime("%d/%m/%Y")
    dl_amanha = (datetime.now(UK_TZ) + timedelta(days=1)).strftime("%d/%m/%Y")

    async def responder(date_str, titulo, data_label, filtro=None):
        msg      = await update.message.reply_text("⏳ Buscando corridas...")
        corridas = buscar_corridas_bot(date_str)
        await msg.delete()
        if not corridas:
            await update.message.reply_text("❌ Nenhuma corrida encontrada.", reply_markup=MENU)
            return
        txt = formatar_corridas(corridas, titulo, data_label, filtro=filtro)
        await update.message.reply_text(txt, parse_mode="Markdown", reply_markup=MENU)

    if   texto == "🗓 Hoje":        await responder(hoje,   "HOJE",              dl_hoje)
    elif texto == "🗓 Amanhã":      await responder(amanha, "AMANHÃ",            dl_amanha)
    elif texto == "⚡ Flat":        await responder(hoje,   "FLAT — HOJE",       dl_hoje,   filtro="FLAT")
    elif texto == "🌿 Jump":        await responder(hoje,   "JUMP — HOJE",       dl_hoje,   filtro="JUMP")
    elif texto == "🇬🇧 Só UK":      await responder(hoje,   "SÓ UK — HOJE",      dl_hoje,   filtro="UK")
    elif texto == "🇮🇪 Só Irlanda": await responder(hoje,   "SÓ IRLANDA — HOJE", dl_hoje,   filtro="IE")
    elif texto == "🏇 Todas":       await responder(hoje,   "TODAS — HOJE",      dl_hoje)
    elif texto == "🕐 Horário":
        now_uk  = datetime.now(UK_TZ)
        now_brt = datetime.now(BR_TZ)
        dst     = bool(now_uk.dst())
        diff    = int((now_uk.utcoffset() - now_brt.utcoffset()).total_seconds() / 3600)
        await update.message.reply_text(
            f"🕐 *HORÁRIO ATUAL*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🇬🇧 UK:  `{now_uk.strftime('%H:%M')}` — {'BST (Verão)' if dst else 'GMT (Inverno)'}\n"
            f"🇧🇷 BRT: `{now_brt.strftime('%H:%M')}` — Brasília\n\n"
            f"⏱ UK está *{diff}h à frente* do Brasil",
            parse_mode="Markdown", reply_markup=MENU
        )

# ─── INICIAR BOT EM THREAD ───────────────────────────────────────
def start_bot():
    import asyncio
    async def run():
        telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
        telegram_app.add_handler(CommandHandler("start", cmd_start))
        telegram_app.add_handler(MessageHandler(
            filters.TEXT & filters.Regex(
                r"^(🗓 Hoje|🗓 Amanhã|⚡ Flat|🌿 Jump|🇬🇧 Só UK|🇮🇪 Só Irlanda|🏇 Todas|🕐 Horário)$"
            ), handler_menu
        ))
        log.info("🐴 Bot iniciado!")
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling(drop_pending_updates=True)
        await telegram_app.updater.idle()
    asyncio.run(run())

if __name__ == "__main__":
    if BOT_TOKEN:
        t = threading.Thread(target=start_bot, daemon=True)
        t.start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
