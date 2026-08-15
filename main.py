import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
import re
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ===================== КОНФИГ =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8523531820:AAHhrwX6U3sdhnSDkA3hvlIqIKYG0ltAYIo")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8847450363"))
FUNPAY_LINK = os.getenv("FUNPAY_LINK", "https://funpay.com/lots/offer?id=75088997")

# ===================== ФАЙЛЫ =====================
USERS_FILE = "users.json"
PREMIUM_FILE = "premium.json"

executor = ThreadPoolExecutor(max_workers=5)


def load_json(file):
    if os.path.exists(file):
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def get_user(user_id):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")

    if uid not in users:
        users[uid] = {"snos": 0, "date": today}
        save_json(USERS_FILE, users)
    elif users[uid].get("date") != today:
        # Сброс ежедневного лимита при наступлении нового дня
        users[uid]["snos"] = 0
        users[uid]["date"] = today
        save_json(USERS_FILE, users)

    return users[uid]


def update_user(user_id):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")

    if uid not in users:
        users[uid] = {"snos": 0, "date": today}

    users[uid]["snos"] += 1
    users[uid]["date"] = today
    save_json(USERS_FILE, users)


def is_premium(user_id):
    premium = load_json(PREMIUM_FILE)
    return str(user_id) in premium


def can_snos(user_id):
    if is_premium(user_id):
        return True
    user = get_user(user_id)
    return user["snos"] < 1


# ===================== ПОЧТОВЫЕ АККАУНТЫ (RAMBLER) =====================
senders = {
    "ugtnddpzej@rambler.ru": "9506681adi6MU",
    "cisvzeeuyg@rambler.ru": "6301453fJo4s9",
    "ggflngvlih@rambler.ru": "22408953S2gby",
    "nvynpxnkkd@rambler.ru": "2510571xHHdgR",
    "fjzoyuouuz@rambler.ru": "59097784rDPPd",
    "bzgqlptwhl@rambler.ru": "0816705Tr1FYG",
    "vigzkazhat@rambler.ru": "31932120MtFlm",
    "afgunihnfe@rambler.ru": "9061194g5B45C",
    "ngvxtwpesz@rambler.ru": "2011142rqGxFR",
    "egvwsdlkyr@rambler.ru": "9037151L6w49u",
}

receivers = [
    "stopCA@telegram.org",
    "sms@telegram.org",
    "dmca@telegram.org",
    "abuse@telegram.org",
    "sticker@telegram.org",
    "support@telegram.org",
    "ceo@telegram.org",
]

COMPLAINTS = {
    "spam": "Здравствуйте! Пользователь {target} спамит. Примите меры.",
    "doxxing": (
        "Здравствуйте! Пользователь {target} сливает личные данные."
        " Заблокируйте."
    ),
    "insults": (
        "Здравствуйте! Пользователь {target} оскорбляет людей. Примите меры."
    ),
    "session": (
        "Здравствуйте! Аккаунт {target} взломан. Удалите или обнулите сессии."
    ),
    "virtual": (
        "Здравствуйте! Аккаунт {target} использует виртуальный номер. Проверьте."
    ),
    "animal": (
        "Здравствуйте! Пользователь {target} распространяет жестокий контент."
        " Заблокируйте."
    ),
    "channel_spam": "Здравствуйте! Канал {target} спамит. Примите меры.",
    "channel_doxxing": (
        "Здравствуйте! Канал {target} сливает личные данные. Заблокируйте."
    ),
    "channel_illegal": (
        "Здравствуйте! Канал {target} продает доксинг и сваттинг. Заблокируйте."
    ),
    "group_spam": "Здравствуйте! Группа {target} спамит. Примите меры.",
    "group_illegal": (
        "Здравствуйте! Группа {target} распространяет запрещенный контент."
        " Заблокируйте."
    ),
}

REASON_NAMES = {
    "spam": "Спам",
    "doxxing": "Слив данных",
    "insults": "Оскорбления",
    "session": "Снос сессий",
    "virtual": "Виртуальный номер",
    "animal": "Жестокость",
    "channel_spam": "Спам в канале",
    "channel_doxxing": "Слив данных в канале",
    "channel_illegal": "Незаконные услуги",
    "group_spam": "Спам в группе",
    "group_illegal": "Запрещенный контент",
}


def send_email_sync(receiver, sender_email, sender_password, subject, body):
    try:
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = receiver
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        server = smtplib.SMTP("smtp.rambler.ru", 25, timeout=5)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver, msg.as_string())
        server.quit()
        return True
    except Exception:
        return False


# ===================== КОМАНДЫ БОТА =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    premium_status = "⭐ Premium" if is_premium(user_id) else "👤 Обычный"
    user = get_user(user_id)
    snos_left = (
        "♾️ Безлимит" if is_premium(user_id) else f"{1 - user['snos']} снос(ов)"
    )

    keyboard = [
        [InlineKeyboardButton("👤 Аккаунт", callback_data="account")],
        [InlineKeyboardButton("🤖 Бот", callback_data="bot")],
        [InlineKeyboardButton("📢 Канал", callback_data="channel")],
        [InlineKeyboardButton("👥 Группа", callback_data="group")],
        [InlineKeyboardButton("⭐ Premium", callback_data="premium_info")],
        [InlineKeyboardButton("📊 Помощь", callback_data="help")],
    ]
    if str(user_id) == str(ADMIN_ID):
        keyboard.append(
            [InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin")]
        )

    text = (
        f"🤖 **СНОСЕР БОТ**\n\n"
        f"👤 Статус: {premium_status}\n"
        f"📊 Доступно сносов на сегодня: {snos_left}\n\n"
        f"Выбери тип цели 👇"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data == "help":
        await query.edit_message_text(
            "📖 **Помощь**\n\n"
            "1. Выбери тип цели:\n"
            "   • Аккаунт\n"
            "   • Бот\n"
            "   • Канал\n"
            "   • Группа\n"
            "2. Введи @username или ссылку\n"
            "3. Выбери причину\n"
            "4. Бот отправит жалобы\n\n"
            "▪️ /start — главное меню\n"
            "▪️ /cancel — отмена"
        )
        return

    if query.data == "premium_info":
        keyboard = [
            [InlineKeyboardButton("💳 Купить Premium", url=FUNPAY_LINK)],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")],
        ]
        await query.edit_message_text(
            "⭐ **Premium**\n\n"
            "Преимущества:\n"
            "• ♾️ Безлимитные сносы\n"
            "• 🚀 Приоритетная обработка\n"
            "• 📨 Уведомления о статусе\n\n"
            "💰 Цена: 200₽\n\n"
            "📌 **Инструкция:**\n"
            "1. Нажми кнопку «Купить Premium»\n"
            "2. Оплати товар на FunPay\n"
            "3. Напиши сюда номер заказа\n"
            "4. Premium будет выдан **в течение 10 минут**\n\n"
            "🔗 Ссылка для оплаты:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if query.data == "admin":
        if str(user_id) != str(ADMIN_ID):
            await query.edit_message_text("⛔ Доступ запрещён.")
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    "➕ Добавить Premium", callback_data="add_premium"
                )
            ],
            [
                InlineKeyboardButton(
                    "➖ Удалить Premium", callback_data="remove_premium"
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 Список Premium", callback_data="list_premium"
                )
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")],
        ]
        await query.edit_message_text(
            "⚙️ **Админ-панель**\n\nВыбери действие:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if query.data == "add_premium":
        if str(user_id) != str(ADMIN_ID):
            return
        context.user_data["admin_action"] = "add_premium"
        await query.edit_message_text(
            "🔍 Введи **ID** пользователя для добавления в Premium.\n\n"
            "Пример: `123456789`",
            parse_mode="Markdown",
        )
        return

    if query.data == "remove_premium":
        if str(user_id) != str(ADMIN_ID):
            return
        context.user_data["admin_action"] = "remove_premium"
        await query.edit_message_text(
            "🔍 Введи **ID** пользователя для удаления из Premium.\n\n"
            "Пример: `123456789`",
            parse_mode="Markdown",
        )
        return

    if query.data == "list_premium":
        if str(user_id) != str(ADMIN_ID):
            return
        premium = load_json(PREMIUM_FILE)
        if premium:
            text = "📋 **Premium-пользователи:**\n\n"
            for uid in premium:
                text += f"• `{uid}`\n"
            await query.edit_message_text(text, parse_mode="Markdown")
        else:
            await query.edit_message_text("📋 Premium-пользователей пока нет.")
        return

    if query.data == "back_to_menu":
        await start(update, context)
        return

    # Проверка причин и действий
    if query.data in REASON_NAMES or query.data in COMPLAINTS:
        await reason_handler(update, context)
        return

    # Проверка лимита сносов
    if not can_snos(user_id):
        await query.edit_message_text(
            "❌ **Лимит сносов исчерпан!**\n\n"
            "У тебя 1 бесплатный снос в день.\n"
            "⭐ Купи Premium для безлимитных сносов.\n\n"
            "Нажми на кнопку «Premium» в меню.",
            parse_mode="Markdown",
        )
        return

    context.user_data["target_type"] = query.data
    await query.edit_message_text(
        f"🔍 Введи @username или ссылку на {query.data}.\n\n"
        f"Пример: @durov или https://t.me/durov"
    )


async def handle_text_messages(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # 1. Проверка админ-действий
    admin_action = context.user_data.get("admin_action")
    if admin_action and str(user_id) == str(ADMIN_ID):
        target_id = text
        premium = load_json(PREMIUM_FILE)

        if admin_action == "add_premium":
            if target_id not in premium:
                premium[target_id] = True
                save_json(PREMIUM_FILE, premium)
                await update.message.reply_text(
                    f"✅ Пользователь `{target_id}` добавлен в Premium!",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    f"ℹ️ Пользователь `{target_id}` уже в Premium.",
                    parse_mode="Markdown",
                )

        elif admin_action == "remove_premium":
            if target_id in premium:
                del premium[target_id]
                save_json(PREMIUM_FILE, premium)
                await update.message.reply_text(
                    f"✅ Пользователь `{target_id}` удалён из Premium.",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    f"❌ Пользователь `{target_id}` не найден в Premium.",
                    parse_mode="Markdown",
                )

        context.user_data["admin_action"] = None
        return

    # 2. Ввод целевого объекта
    target_type = context.user_data.get("target_type")
    if not target_type:
        await update.message.reply_text(
            "❌ Сначала выбери тип цели через /start"
        )
        return

    context.user_data["target"] = text

    keyboard = []
    if target_type == "account":
        reasons = [
            ("Спам", "spam"),
            ("Слив данных", "doxxing"),
            ("Оскорбления", "insults"),
            ("Снос сессий", "session"),
            ("Виртуальный номер", "virtual"),
            ("Жестокость", "animal"),
        ]
    elif target_type == "bot":
        reasons = [("Спам", "spam"), ("Нарушение правил", "doxxing")]
    elif target_type == "channel":
        reasons = [
            ("Спам", "channel_spam"),
            ("Слив данных", "channel_doxxing"),
            ("Незаконные услуги", "channel_illegal"),
        ]
    elif target_type == "group":
        reasons = [
            ("Спам", "group_spam"),
            ("Запрещенный контент", "group_illegal"),
        ]
    else:
        reasons = [("Другое", "spam")]

    for name, key in reasons:
        keyboard.append([InlineKeyboardButton(name, callback_data=key)])

    await update.message.reply_text(
        "📌 Выбери причину:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    reason = query.data
    target = context.user_data.get("target")
    target_type = context.user_data.get("target_type")
    user_id = update.effective_user.id

    if not target:
        await query.edit_message_text(
            "❌ Ошибка: цель не найдена. Используй /start"
        )
        return

    complaint = COMPLAINTS.get(reason, f"Жалоба на {target}").format(
        target=target
    )
    total = len(senders) * len(receivers)

    msg = await query.edit_message_text(
        f"⏳ **Отправка жалоб...**\n\n"
        f"🎯 Цель: `{target}`\n"
        f"📌 Тип: {target_type}\n"
        f"📌 Причина: {REASON_NAMES.get(reason, reason)}\n"
        f"📨 Писем: 0/{total}\n\n"
        f"🔄 Прогресс: 0%",
        parse_mode="Markdown",
    )

    sent = 0
    failed = 0
    last_update_time = time.time()
    loop = asyncio.get_running_loop()

    for sender_email, sender_password in senders.items():
        for receiver in receivers:
            subject = (
                f"Жалоба на {target_type}: {REASON_NAMES.get(reason, reason)}"
            )

            # Отправка асинхронно через пул потоков
            success = await loop.run_in_executor(
                executor,
                send_email_sync,
                receiver,
                sender_email,
                sender_password,
                subject,
                complaint,
            )

            if success:
                sent += 1
            else:
                failed += 1

            # Обновление прогресса раз в 3 секунды во избежание Flood control
            if time.time() - last_update_time > 3.0:
                progress = int(((sent + failed) / total) * 100)
                bar = "█" * (progress // 5) + "░" * (20 - progress // 5)
                try:
                    await msg.edit_text(
                        f"⏳ **Отправка жалоб...**\n\n"
                        f"🎯 Цель: `{target}`\n"
                        f"📌 Тип: {target_type}\n"
                        f"📌 Причина: {REASON_NAMES.get(reason, reason)}\n"
                        f"📨 Отправлено: {sent + failed}/{total}\n\n"
                        f"🔄 Прогресс: {progress}%\n"
                        f"`[{bar}]`",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
                last_update_time = time.time()

            await asyncio.sleep(0.05)

    update_user(user_id)
    context.user_data.clear()

    keyboard = [
        [InlineKeyboardButton("🔄 Новый снос", callback_data="back_to_menu")]
    ]

    await msg.edit_text(
        f"✅ **СНОС ЗАВЕРШЁН!**\n\n"
        f"🎯 Цель: `{target}`\n"
        f"📌 Тип: {target_type}\n"
        f"📌 Причина: {REASON_NAMES.get(reason, reason)}\n"
        f"📨 Успешно отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n\n"
        f"🔥 Результат зависит от модерации Telegram.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Действие отменено. Используй /start.")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages)
    )

    print("🚀 Бот-сносер запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
