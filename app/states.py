from aiogram.fsm.state import State, StatesGroup

class Registration(StatesGroup):
    minecraft_nick = State()

class CartFlow(StatesGroup):
    quantity = State()
    details = State()
    head_nick = State()
    head_confirm = State()
    pickup = State()

class AdminFlow(StatesGroup):
    product_category = State()
    product_name = State()
    product_portion = State()
    product_price = State()
    edit_product_price = State()
    product_description = State()
    point_name = State()
    point_dimension = State()
    point_x = State()
    point_y = State()
    point_z = State()
    catalog_upload = State()

class CancelFlow(StatesGroup):
    reason = State()
    confirm = State()


class ProfileFlow(StatesGroup):
    new_nick = State()
    confirm_nick = State()
