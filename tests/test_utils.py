from mealie_planner.utils import extract_ingredient_texts

def test_extract_ingredient_texts_none():
    assert extract_ingredient_texts(None) == []

def test_extract_ingredient_texts_empty_dict():
    assert extract_ingredient_texts({}) == []

def test_extract_ingredient_texts_missing_key():
    assert extract_ingredient_texts({'name': 'Recipe'}) == []

def test_extract_ingredient_texts_valid_ingredients():
    recipe_details = {
        'recipeIngredient': [
            {'display': '1 cup sugar'},
            {'originalText': '2 cups flour'},
            {'note': 'salt'},
            {'display': ''},
            {'display': '  '},
            {}
        ]
    }
    expected = [
        '1 cup sugar',
        '2 cups flour',
        'None None salt',
        'None None',
        'None None'
    ]
    assert extract_ingredient_texts(recipe_details) == expected
