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

RAPIDAPI_KEY        = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_KEY_BACKUP = os.environ.get("RAPIDAPI_KEY_BACKUP", "")
BOT_TOKEN           = os.environ.get("BOT_TOKEN", "")
UK_TZ               = pytz.timezone("Europe/London")
BR_TZ               = pytz.timezone("America/Sao_Paulo")

app = Flask(__name__)
CORS(app)
_cache = {}

# ─── ALERTAS ─────────────────────────────────────────────────────
# {chat_id: [{brt: "14:25", texto: "...", enviado: False}]}
_alertas = {}
_aguardando_selecao = {}  # {chat_id: [lista de corridas]}

def deve_atualizar(date_str):
    if date_str not in _cache:
        return True
    _, saved_at = _cache[date_str]
    saved_dt = datetime.fromtimestamp(saved_at, UK_TZ)
    return saved_dt.date() != datetime.now(UK_TZ).date()

def buscar_com_chave(date_str, api_key):
    r = requests.get(
        "https://horse-racing.p.rapidapi.com/racecards",
        headers={
            "x-rapidapi-host": "horse-racing.p.rapidapi.com",
            "x-rapidapi-key":  api_key,
        },
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

@app.route("/racecards")
def racecards():
    date = request.args.get("date", datetime.now(UK_TZ).strftime("%Y-%m-%d"))
    corridas = get_corridas(date)
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

# ─── HELPERS ─────────────────────────────────────────────────────
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

def data_hoje_uk():
    """Retorna a data UK atual — mas se for depois das 21h BRT usa data BRT"""
    now_brt = datetime.now(BR_TZ)
    now_uk  = datetime.now(UK_TZ)
    # Se UK já virou para o dia seguinte mas BRT ainda não, usa data de hoje BRT convertida para UK
    if now_uk.date() > now_brt.date():
        return now_brt.strftime("%Y-%m-%d")
    return now_uk.strftime("%Y-%m-%d")

def processar_corridas(corridas, filtro=None):
    resultado = []
    for r in corridas:
        course = r.get("course", "?")
        tipo   = tipo_corrida(r.get("title", ""))
        flag   = bandeira(course)
        dist   = r.get("distance", "?")
        brt, brt_dt = uk_para_brt(r.get("date", ""))

        if filtro == "FLAT" and tipo in JUMP_TIPOS: continue
        if filtro == "JUMP" and tipo not in JUMP_TIPOS: continue
        if filtro == "UK"   and flag != "🇬🇧": continue
        if filtro == "IE"   and flag != "🇮🇪": continue

        resultado.append({
            "sort": brt,
            "brt": brt,
            "brt_dt": brt_dt,
            "texto": f"{flag} {brt} - {course} - {tipo} - {dist}",
            "flag": flag,
            "course": course,
            "tipo": tipo,
            "dist": dist,
        })

    resultado.sort(key=lambda x: x["sort"])
    return resultado

def formatar(corridas, titulo, filtro=None):
    now_brt = datetime.now(BR_TZ).strftime("%H:%M")
    now_uk  = datetime.now(UK_TZ)
    fuso    = "BST" if bool(now_uk.dst()) else "GMT"
    data_label = datetime.now(BR_TZ).strftime("%d/%m/%Y")
    linhas  = processar_corridas(corridas, filtro)
    uk_c    = sum(1 for l in linhas if l["flag"] == "🇬🇧")
    ie_c    = sum(1 for l in linhas if l["flag"] == "🇮🇪")

    txt  = f"🏇 *CORRIDAS UK & IRLANDA*\n"
    txt += f"📅 *{titulo}* — {data_label}\n"
    txt += f"🇧🇷 {now_brt} | 🇬🇧 {now_uk.strftime('%H:%M')} ({fuso})\n"
    txt += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    txt += "\n".join(l["texto"] for l in linhas) if linhas else "_Nenhuma corrida._"
    txt += f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
    txt += f"🏁 {len(linhas)} corridas  |  🇬🇧 {uk_c}  🇮🇪 {ie_c}"
    return txt

def formatar_com_numeros(corridas, filtro=None):
    """Formata corridas numeradas para seleção de alertas"""
    linhas = processar_corridas(corridas, filtro)
    now_brt = datetime.now(BR_TZ).strftime("%H:%M")
    now_uk  = datetime.now(UK_TZ)
    fuso    = "BST" if bool(now_uk.dst()) else "GMT"

    txt  = f"🔔 *SELECIONAR ALERTAS*\n"
    txt += f"🇧🇷 {now_brt} | 🇬🇧 {now_uk.strftime('%H:%M')} ({fuso})\n"
    txt += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    txt += "Digite os números das corridas que quer ser avisado *5 minutos antes*:\n\n"

    for i, l in enumerate(linhas, 1):
        txt += f"`{i:2d}.` {l['texto']}\n"

    txt += f"\n━━━━━━━━━━━━━━━━━━━━━\n"
    txt += f"Ex: `1 3 7` para alertar 3 corridas\n"
    txt += f"Digite `0` para cancelar"
    return txt, linhas

# ─── WORKER DE ALERTAS ───────────────────────────────────────────
def worker_alertas(bot_app):
    import asyncio

    async def enviar_alertas():
        while True:
            now_brt = datetime.now(BR_TZ)
            now_str = now_brt.strftime("%H:%M")

            for chat_id, alertas in list(_alertas.items()):
                for alerta in alertas:
                    if not alerta["enviado"] and alerta["brt"] == now_str:
                        try:
                            await bot_app.bot.send_message(
                                chat_id=chat_id,
                                text=f"🔔 *CORRIDA EM 5 MINUTOS!*\n\n{alerta['texto']}\n\n⏰ Agora: {now_str} BRT",
                                parse_mode="Markdown"
                            )
                            alerta["enviado"] = True
                            log.info(f"Alerta enviado para {chat_id}: {alerta['texto']}")
                        except Exception as e:
                            log.error(f"Erro ao enviar alerta: {e}")

            # Limpa alertas enviados e passados
            for chat_id in list(_alertas.keys()):
                _alertas[chat_id] = [
                    a for a in _alertas[chat_id]
                    if not a["enviado"]
                ]
                if not _alertas[chat_id]:
                    del _alertas[chat_id]

            await asyncio.sleep(30)

    asyncio.run(enviar_alertas())

# ─── BOT ─────────────────────────────────────────────────────────
def start_bot():
    import asyncio
    from telegram import Update, ReplyKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

    MENU = ReplyKeyboardMarkup(
        [["🗓 Hoje","🔔 Alertas"],
         ["⚡ Flat","🌿 Jump"],
         ["🇬🇧 Só UK","🇮🇪 Só Irlanda"],
         ["🏇 Todas","🕐 Horário"]],
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

    async def mostrar_hoje(update, filtro=None, titulo="HOJE"):
        msg = await update.message.reply_text("⏳ Buscando...")
        corridas = get_corridas(data_hoje_uk())
        await msg.delete()
        if not corridas:
            await update.message.reply_text("❌ Nenhuma corrida encontrada.", reply_markup=MENU)
            return
        await update.message.reply_text(
            formatar(corridas, titulo, filtro=filtro),
            parse_mode="Markdown", reply_markup=MENU
        )

    async def handler_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        texto   = update.message.text
        chat_id = update.message.chat_id

        # Verifica se usuário está selecionando alertas
        if chat_id in _aguardando_selecao:
            if texto.strip() == "0":
                del _aguardando_selecao[chat_id]
                await update.message.reply_text("❌ Alertas cancelados.", reply_markup=MENU)
                return

            corridas_lista = _aguardando_selecao[chat_id]
            try:
                numeros = [int(n) for n in texto.strip().split() if n.isdigit()]
                selecionadas = [corridas_lista[n-1] for n in numeros if 1 <= n <= len(corridas_lista)]

                if not selecionadas:
                    await update.message.reply_text("❌ Números inválidos. Tente novamente ou digite `0` para cancelar.", parse_mode="Markdown", reply_markup=MENU)
                    return

                # Calcula horário do alerta (5 min antes)
                novos_alertas = []
                for c in selecionadas:
                    if c["brt_dt"]:
                        alerta_dt  = c["brt_dt"] - timedelta(minutes=5)
                        alerta_brt = alerta_dt.strftime("%H:%M")
                        novos_alertas.append({
                            "brt": alerta_brt,
                            "texto": c["texto"],
                            "enviado": False
                        })

                if chat_id not in _alertas:
                    _alertas[chat_id] = []
                _alertas[chat_id].extend(novos_alertas)
                del _aguardando_selecao[chat_id]

                confirmacao = "\n".join(f"✅ {a['texto']} → alerta às {a['brt']} BRT" for a in novos_alertas)
                await update.message.reply_text(
                    f"🔔 *Alertas definidos!*\n\n{confirmacao}",
                    parse_mode="Markdown", reply_markup=MENU
                )
            except Exception as e:
                log.error(f"Erro alertas: {e}")
                await update.message.reply_text("❌ Erro ao processar. Tente novamente.", reply_markup=MENU)
            return

        # Menu normal
        if   texto in ["🗓 Hoje", "/hoje"]:       await mostrar_hoje(update)
        elif texto in ["⚡ Flat", "/flat"]:        await mostrar_hoje(update, filtro="FLAT", titulo="FLAT")
        elif texto in ["🌿 Jump", "/jump"]:        await mostrar_hoje(update, filtro="JUMP", titulo="JUMP")
        elif texto in ["🇬🇧 Só UK", "/uk"]:        await mostrar_hoje(update, filtro="UK",   titulo="SÓ UK")
        elif texto in ["🇮🇪 Só Irlanda","/irlanda"]: await mostrar_hoje(update, filtro="IE", titulo="SÓ IRLANDA")
        elif texto in ["🏇 Todas", "/todas"]:      await mostrar_hoje(update, titulo="TODAS")
        elif texto in ["🔔 Alertas", "/alertas"]:
            msg = await update.message.reply_text("⏳ Buscando corridas...")
            corridas = get_corridas(data_hoje_uk())
            await msg.delete()
            if not corridas:
                await update.message.reply_text("❌ Nenhuma corrida hoje.", reply_markup=MENU)
                return
            txt, lista = formatar_com_numeros(corridas)
            _aguardando_selecao[chat_id] = lista
            await update.message.reply_text(txt, parse_mode="Markdown")
        elif texto in ["🕐 Horário", "/horario"]:
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
        telegram_app.add_handler(CommandHandler("start",    cmd_start))
        telegram_app.add_handler(CommandHandler("hoje",     handler_menu))
        telegram_app.add_handler(CommandHandler("flat",     handler_menu))
        telegram_app.add_handler(CommandHandler("jump",     handler_menu))
        telegram_app.add_handler(CommandHandler("uk",       handler_menu))
        telegram_app.add_handler(CommandHandler("irlanda",  handler_menu))
        telegram_app.add_handler(CommandHandler("todas",    handler_menu))
        telegram_app.add_handler(CommandHandler("alertas",  handler_menu))
        telegram_app.add_handler(CommandHandler("horario",  handler_menu))
        telegram_app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, handler_menu
        ))
        log.info("🐴 Bot Telegram iniciado!")

        # Inicia worker de alertas em thread separada
        threading.Thread(
            target=worker_alertas,
            args=(telegram_app,),
            daemon=True
        ).start()

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
