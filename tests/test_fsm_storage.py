from aiogram.fsm.storage.base import StorageKey

from app.fsm_storage import DbStorage

KEY = StorageKey(bot_id=1, chat_id=2, user_id=3)


async def test_state_and_data_roundtrip():
    st = DbStorage()
    assert await st.get_state(KEY) is None and await st.get_data(KEY) == {}
    await st.set_state(KEY, "CartFlow:details")
    await st.update_data(KEY, {"ui_ref": [2, 10, True], "name": "Берёза"})
    # «Перезапуск»: новый объект хранилища читает то же самое из БД.
    st2 = DbStorage()
    assert await st2.get_state(KEY) == "CartFlow:details"
    assert await st2.get_data(KEY) == {"ui_ref": [2, 10, True], "name": "Берёза"}
    await st2.set_state(KEY, None)
    await st2.set_data(KEY, {})
    assert await st2.get_state(KEY) is None and await st2.get_data(KEY) == {}
