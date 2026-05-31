from .client import BaseMealieClient
from .recipe import RecipeMixin
from .shopping_list import ShoppingListMixin
from .mealplan import MealplanMixin
from .labels import LabelsMixin
from .users import UsersMixin

class MealieClient(
    RecipeMixin,
    ShoppingListMixin,
    MealplanMixin,
    LabelsMixin,
    UsersMixin,
    BaseMealieClient
):
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MealieClient, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
