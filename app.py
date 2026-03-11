import os
import re
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

RAPIDAPI_KEY        = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_KEY_BACKUP = os.environ.get("RAPIDAPI_KEY_BACKUP", "")
BOT_TOKEN           = os.environ.get("BOT_TOKEN", "")
UK_TZ               = pytz.timezone("Europe/London")
BR_TZ               = pytz.timezone("America/Sao_Paulo")

app = Flask(__name__)
CORS(app)
_cache   = {}
_alertas = {}  # {chat_id: [{brt, texto, enviado}]}

# ─── UTILS ───────────────────────────────────────────────────────

def esc(text):
    """Escapa caracteres especiais para MarkdownV2"""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))

# ─── API / CACHE ─────────────────────────────────────────────────

def deve_atualizar(date_str):
    if date_str not in _cache:
        return True
    _, saved_at = _cache[date_str]
    return datetime.fromtimestamp(saved_at, UK_TZ).date() != datetime.now(UK_TZ).date()

def buscar_com_chave(date_str, api_key):
    r = requests.get(
        "https://horse-racing.p.rapidapi.com/racecards",
        headers={"x-rapidapi-host": "horse-racing.p.rapidapi.com", "x-rapidapi-key": api_key},
        params={"date": date_str},
        timeout=10
    )
    r.raise_for_status()
    data = r.json()
    return list(data.values()) if isinstance(data, dict) else data

def buscar_e_salvar(date_str):
    for label, key in [("principal", RAPIDAPI_KEY), ("backup", RAPIDAPI_KEY_BACKUP)]:
        if not key:
            continue
        try:
            corridas = buscar_com_chave(date_str, key)
            _cache[date_str] = (corridas, time.time())
            log.info(f"Cache ({label}): {date_str} — {len(corridas)} corridas")
            return corridas
        except Exception as e:
            log.warning(f"Chave {label} falhou: {e}")
    log.error("Ambas as chaves falharam!")
    return _cache[date_str][0] if date_str in _cache else []

def get_corridas(date_str):
    return buscar_e_salvar(date_str) if deve_atualizar(date_str) else _cache[date_str][0]

def data_hoje_brt():
    """Retorna a data de hoje no fuso BRT convertida para string UK-format"""
    now_brt = datetime.now(BR_TZ)
    now_uk  = datetime.now(UK_TZ)
    # Se UK já virou para amanhã mas BRT ainda não, usa data BRT
    if now_uk.date() > now_brt.date():
        return now_brt.strftime("%Y-%m-%d")
    return now_uk.strftime("%Y-%m-%d")

# ─── FLASK ───────────────────────────────────────────────────────

@app.route("/racecards")
def racecards():
    date = request.args.get("date", datetime.now(UK_TZ).strftime("%Y-%m-%d"))
    return jsonify(get_corridas(date))

@app.route("/status")
def status():
    info = {"status": "ok", "cache": {}}
    for d, (corridas, ts) in _cache.items():
        info["cache"][d] = {
            "corridas": len(corridas),
            "salvo_em": datetime.fromtimestamp(ts, UK_TZ).strftime("%H:%M UK")
        }
    return jsonify(info)

# ─── HELPERS CORRIDAS ────────────────────────────────────────────

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
        brt_dt   = uk_dt.astimezone(BR_TZ)
        return brt_dt.strftime("%H:%M"), brt_dt
    except:
        return "??:??", None

def processar_corridas(corridas, filtro=None):
    resultado = []
    for r in corridas:
        course      = r.get("course", "?")
        tipo        = tipo_corrida(r.get("title", ""))
        flag        = bandeira(course)
        dist        = r.get("distance", "?")
        brt, brt_dt = uk_para_brt(r.get("date", ""))

        if filtro == "FLAT" and tipo in JUMP_TIPOS: continue
        if filtro == "JUMP" and tipo not in JUMP_TIPOS: continue
        if filtro == "UK"   and flag != "🇬🇧": continue
        if filtro == "IE"   and flag != "🇮🇪": continue

        resultado.append({
            "sort":   brt,
            "brt":    brt,
            "brt_dt": brt_dt,
            "texto":  f"{flag} {brt} - {course} - {tipo} - {dist}",
            "flag":   flag,
            "course": course,
            "tipo":   tipo,
            "dist":   dist,
        })

    resultado.sort(key=lambda x: x["sort"])
    return resultado

def formatar(corridas, titulo, filtro=None):
    now_brt     = datetime.now(BR_TZ)
    now_brt_str = now_brt.strftime("%H:%M")
    now_uk      = datetime.now(UK_TZ)
    fuso        = "BST" if bool(now_uk.dst()) else "GMT"
    data_label  = now_brt.strftime("%d/%m/%Y")
    linhas      = processar_corridas(corridas, filtro)

    uk_c   = sum(1 for l in linhas if l["flag"] == "🇬🇧")
    ie_c   = sum(1 for l in linhas if l["flag"] == "🇮🇪")
    flat_c = sum(1 for l in linhas if l["tipo"] not in JUMP_TIPOS)
    jump_c = sum(1 for l in linhas if l["tipo"] in JUMP_TIPOS)

    txt  = f"🏇 *CORRIDAS UK & IRLANDA*\n"
    txt += f"📅 *{esc(titulo)}* — {esc(data_label)}\n"
    txt += f"🇧🇷 {esc(now_brt_str)} \\| 🇬🇧 {esc(now_uk.strftime('%H:%M'))} \\({esc(fuso)}\\)\n"
    txt += f"━━━━━━━━━━━━━━━━━━━━━\n\n"

    for l in linhas:
        linha_esc = esc(l['texto'])
        if l["brt_dt"] and l["brt_dt"] < now_brt:
            txt += f"~{linha_esc}~\n"
        else:
            txt += f"{linha_esc}\n"

    if not linhas:
        txt += "_Nenhuma corrida\\._\n"

    txt += f"\n━━━━━━━━━━━━━━━━━━━━━\n"
    txt += f"🎯 {len(linhas)} corridas  \\|  🇬🇧 {uk_c}  🇮🇪 {ie_c}  \\|  🏁 {flat_c} flat  🚧 {jump_c} jump"
    return txt

# ─── WORKER ALERTAS ──────────────────────────────────────────────

def worker_alertas(bot_app):
    import asyncio

    async def loop():
        while True:
            now_brt = datetime.now(BR_TZ)
            now_str = now_brt.strftime("%H:%M")
            for chat_id, alertas in list(_alertas.items()):
                for alerta in alertas:
                    if not alerta["enviado"] and alerta["brt"] == now_str:
                        try:
                            await bot_app.bot.send_message(
                                chat_id=chat_id,
                                text=f"🔔 *CORRIDA EM 5 MINUTOS\\!*\n\n{esc(alerta['texto'])}\n\n⏰ Agora: {esc(now_str)} BRT",
                                parse_mode="MarkdownV2"
                            )
                            alerta["enviado"] = True
                            log.info(f"Alerta enviado para {chat_id}")
                        except Exception as e:
                            log.error(f"Erro alerta: {e}")
            for chat_id in list(_alertas.keys()):
                _alertas[chat_id] = [a for a in _alertas[chat_id] if not a["enviado"]]
                if not _alertas[chat_id]:
                    del _alertas[chat_id]
            await asyncio.sleep(30)

    asyncio.run(loop())

# ─── BOT ─────────────────────────────────────────────────────────

def start_bot():
    import asyncio
    from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (ApplicationBuilder, CommandHandler, MessageHandler,
                               CallbackQueryHandler, filters, ContextTypes)

    MENU = ReplyKeyboardMarkup(
        [["🗓 Hoje",    "🔔 Alertas"],
         ["⚡ Flat",    "🌿 Jump"],
         ["🇬🇧 Só UK",  "🇮🇪 Só Irlanda"],
         ["🏇 Todas",   "🕐 Horário"]],
        resize_keyboard=True, is_persistent=True
    )

    async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        now_uk  = datetime.now(UK_TZ)
        now_brt = datetime.now(BR_TZ)
        diff    = int((now_uk.utcoffset() - now_brt.utcoffset()).total_seconds() / 3600)
        fuso    = "BST verão" if bool(now_uk.dst()) else "GMT inverno"
        await update.message.reply_text(
            f"🐴 *Bem\\-vindo ao UKHorsesBR\\!*\n\n"
            f"Corridas de UK & Irlanda em horário de Brasília\\.\n\n"
            f"🕐 🇬🇧 `{now_uk.strftime('%H:%M')}` → 🇧🇷 `{now_brt.strftime('%H:%M')}`\n"
            f"UK está *{diff}h à frente* \\({esc(fuso)}\\)\n\n"
            f"Use os botões abaixo 👇",
            parse_mode="MarkdownV2", reply_markup=MENU
        )

    async def mostrar_hoje(update, filtro=None, titulo="HOJE"):
        msg = await update.message.reply_text("⏳ Buscando...")
        corridas = get_corridas(data_hoje_brt())
        await msg.delete()
        if not corridas:
            await update.message.reply_text("❌ Nenhuma corrida encontrada\\.", reply_markup=MENU)
            return
        await update.message.reply_text(
            formatar(corridas, titulo, filtro=filtro),
            parse_mode="MarkdownV2", reply_markup=MENU
        )

    async def mostrar_alertas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        msg = await update.message.reply_text("⏳ Buscando corridas...")
        corridas = get_corridas(data_hoje_brt())
        await msg.delete()
        if not corridas:
            await update.message.reply_text("❌ Nenhuma corrida hoje\\.", reply_markup=MENU)
            return

        linhas  = processar_corridas(corridas)
        chat_id = update.message.chat_id
        ctx.user_data["corridas_alerta"] = linhas
        alertas_ativos = {a["texto"] for a in _alertas.get(chat_id, [])}

        keyboard = []
        for i, l in enumerate(linhas):
            ativo = l["texto"] in alertas_ativos
            emoji = "🔔" if ativo else "🔕"
            label = f"{emoji} {l['brt']} - {l['course']} - {l['tipo']}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"alerta_{i}")])
        keyboard.append([InlineKeyboardButton("✅ Confirmar alertas", callback_data="alerta_confirmar")])
        keyboard.append([InlineKeyboardButton("❌ Cancelar tudo",     callback_data="alerta_cancelar")])

        await update.message.reply_text(
            "🔔 *DEFINIR ALERTAS*\n\nToque nas corridas para ativar/desativar alerta *5 min antes*:",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def callback_alerta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query   = update.callback_query
        chat_id = query.message.chat_id
        data    = query.data
        await query.answer()

        if data == "alerta_cancelar":
            if chat_id in _alertas:
                del _alertas[chat_id]
            await query.edit_message_text("❌ Todos os alertas cancelados\\.", parse_mode="MarkdownV2")
            return

        if data == "alerta_confirmar":
            n = len(_alertas.get(chat_id, []))
            await query.edit_message_text(
                f"✅ *{n} alertas confirmados\\!*\nVocê será avisado 5 min antes de cada corrida\\.",
                parse_mode="MarkdownV2"
            )
            return

        if data.startswith("alerta_"):
            idx     = int(data.split("_")[1])
            linhas  = ctx.user_data.get("corridas_alerta", [])
            if idx >= len(linhas):
                return
            corrida = linhas[idx]

            if chat_id not in _alertas:
                _alertas[chat_id] = []

            alertas_ativos = {a["texto"] for a in _alertas[chat_id]}

            if corrida["texto"] in alertas_ativos:
                _alertas[chat_id] = [a for a in _alertas[chat_id] if a["texto"] != corrida["texto"]]
            else:
                if corrida["brt_dt"]:
                    alerta_dt = corrida["brt_dt"] - timedelta(minutes=5)
                    _alertas[chat_id].append({
                        "brt":     alerta_dt.strftime("%H:%M"),
                        "texto":   corrida["texto"],
                        "enviado": False
                    })

            alertas_ativos = {a["texto"] for a in _alertas.get(chat_id, [])}
            keyboard = []
            for i, l in enumerate(linhas):
                ativo = l["texto"] in alertas_ativos
                emoji = "🔔" if ativo else "🔕"
                label = f"{emoji} {l['brt']} - {l['course']} - {l['tipo']}"
                keyboard.append([InlineKeyboardButton(label, callback_data=f"alerta_{i}")])
            keyboard.append([InlineKeyboardButton("✅ Confirmar alertas", callback_data="alerta_confirmar")])
            keyboard.append([InlineKeyboardButton("❌ Cancelar tudo",     callback_data="alerta_cancelar")])
            await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))

    async def handler_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        texto = update.message.text
        if   texto in ["🗓 Hoje",         "/hoje"]:    await mostrar_hoje(update)
        elif texto in ["⚡ Flat",          "/flat"]:    await mostrar_hoje(update, filtro="FLAT",  titulo="FLAT")
        elif texto in ["🌿 Jump",          "/jump"]:    await mostrar_hoje(update, filtro="JUMP",  titulo="JUMP")
        elif texto in ["🇬🇧 Só UK",        "/uk"]:      await mostrar_hoje(update, filtro="UK",    titulo="SÓ UK")
        elif texto in ["🇮🇪 Só Irlanda",   "/irlanda"]: await mostrar_hoje(update, filtro="IE",    titulo="SÓ IRLANDA")
        elif texto in ["🏇 Todas",         "/todas"]:   await mostrar_hoje(update, titulo="TODAS")
        elif texto in ["🔔 Alertas",       "/alertas"]: await mostrar_alertas(update, ctx)
        elif texto in ["🕐 Horário",       "/horario"]:
            now_uk  = datetime.now(UK_TZ)
            now_brt = datetime.now(BR_TZ)
            diff    = int((now_uk.utcoffset() - now_brt.utcoffset()).total_seconds() / 3600)
            fuso    = "BST" if bool(now_uk.dst()) else "GMT"
            await update.message.reply_text(
                f"🕐 *HORÁRIO ATUAL*\n━━━━━━━━━━━━━━━━━━━━━\n"
                f"🇬🇧 `{now_uk.strftime('%H:%M')}` — {esc(fuso)}\n"
                f"🇧🇷 `{now_brt.strftime('%H:%M')}` — Brasília\n\n"
                f"UK está *{diff}h à frente*",
                parse_mode="MarkdownV2", reply_markup=MENU
            )

    async def run():
        telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()
        for cmd, handler in [
            ("start",   cmd_start),
            ("hoje",    handler_menu), ("flat",    handler_menu),
            ("jump",    handler_menu), ("uk",      handler_menu),
            ("irlanda", handler_menu), ("todas",   handler_menu),
            ("alertas", handler_menu), ("horario", handler_menu),
        ]:
            telegram_app.add_handler(CommandHandler(cmd, handler))
        telegram_app.add_handler(CallbackQueryHandler(callback_alerta))
        telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler_menu))

        threading.Thread(target=worker_alertas, args=(telegram_app,), daemon=True).start()

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
