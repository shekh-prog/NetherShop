"""Хранилище FSM в базе данных: состояния диалогов переживают перезапуск бота."""
import json
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey, StateType

from app.database import Session
from app.models import FsmState


def _key(key: StorageKey) -> str:
    return ":".join(str(x) for x in (
        key.bot_id, key.chat_id, key.user_id,
        key.thread_id, getattr(key, "business_connection_id", None), key.destiny,
    ))


class DbStorage(BaseStorage):
    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        async with Session() as s:
            row = await s.get(FsmState, _key(key))
            if row is None:
                if value is None:
                    return
                row = FsmState(key=_key(key), state=value, data="{}")
                s.add(row)
            else:
                row.state = value
                if value is None and row.data in ("", "{}"):
                    await s.delete(row)
            await s.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        async with Session() as s:
            row = await s.get(FsmState, _key(key))
            return row.state if row else None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        async with Session() as s:
            row = await s.get(FsmState, _key(key))
            if row is None:
                if not data:
                    return
                s.add(FsmState(key=_key(key), state=None, data=payload))
            else:
                row.data = payload
                if row.state is None and not data:
                    await s.delete(row)
            await s.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with Session() as s:
            row = await s.get(FsmState, _key(key))
            return json.loads(row.data) if row and row.data else {}

    async def close(self) -> None:
        return None
