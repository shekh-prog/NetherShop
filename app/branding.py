from pathlib import Path
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery, FSInputFile

LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
CAPTION_LIMIT = 1024

def ref_of(msg: Message) -> list:
    """Ссылка на сообщение бота: [chat_id, message_id, это_фото]."""
    return [msg.chat.id, msg.message_id, bool(getattr(msg, "photo", None))]

async def send_branded(message: Message, text: str, reply_markup=None):
    if LOGO_PATH.is_file():
        photo = FSInputFile(LOGO_PATH)
        if len(text) <= CAPTION_LIMIT:
            return await message.answer_photo(photo, caption=text, reply_markup=reply_markup)
        await message.answer_photo(photo, caption="<b>NetherShop</b>")
    return await message.answer(text, reply_markup=reply_markup)

async def edit_message(bot, chat_id: int, message_id: int, text: str, reply_markup=None, photo: bool = False) -> list:
    """Правит сообщение на месте (подпись у фото с логотипом или обычный текст).

    Новое сообщение отправляется только в крайнем случае (сообщение удалено/устарело или текст
    длиннее лимита подписи) — тогда старое удаляется. Возвращает актуальную ссылку [chat, id, фото].
    """
    try:
        if photo and len(text) <= CAPTION_LIMIT:
            await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=text, reply_markup=reply_markup)
            return [chat_id, message_id, True]
        if not photo:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup)
            return [chat_id, message_id, False]
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return [chat_id, message_id, photo]
    sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass
    return [chat_id, sent.message_id, False]

async def edit_branded(call: CallbackQuery, text: str, reply_markup=None) -> list:
    msg = call.message
    return await edit_message(call.bot, msg.chat.id, msg.message_id, text, reply_markup,
                              photo=bool(getattr(msg, "photo", None)))

async def remember(state, ref: list) -> None:
    """Запоминает «главное» сообщение диалога, чтобы потом править его после ввода текста."""
    await state.update_data(ui_ref=ref)

async def show(message: Message, state, text: str, reply_markup=None) -> None:
    """Показывает текст в запомненном сообщении диалога (правка на месте); если его нет — шлёт новое."""
    ref = (await state.get_data()).get("ui_ref")
    if ref:
        new_ref = await edit_message(message.bot, ref[0], ref[1], text, reply_markup, photo=ref[2])
    else:
        new_ref = ref_of(await send_branded(message, text, reply_markup))
    await remember(state, new_ref)
