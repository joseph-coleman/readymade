"""The recipes the Recipe Box starts with: {category: {name: recipe}}. Each recipe says how
many it serves, how long it cooks, its ingredients (name, amount for that many, unit) and
its method. The program changes these as you edit (they aren't saved to a file)."""

RECIPES = {
    "Breakfast": {
        "Pancakes": {
            "serves": 4,
            "minutes": 15,
            "ingredients": [("Flour", 200, "g"), ("Milk", 300, "ml"), ("Eggs", 2, ""), ("Sugar", 1, "tbsp"),
                            ("Butter", 30, "g")],
            "method": "Whisk the flour, sugar, eggs and milk into a smooth batter.\n"
                      "Melt a little butter in a hot pan, pour in a ladleful, and cook until bubbles "
                      "show; turn it and cook the other side.\nKeep them warm while you make the rest.",
        },
        "Porridge": {
            "serves": 2,
            "minutes": 8,
            "ingredients": [("Oats", 80, "g"), ("Milk", 500, "ml"), ("Salt", 1, "pinch"), ("Honey", 2, "tsp")],
            "method": "Put the oats, milk and salt in a pan.\nStir over a medium heat until thick and creamy.\n"
                      "Serve with honey.",
        },
    },
    "Dinner": {
        "Tomato soup": {
            "serves": 4,
            "minutes": 30,
            "ingredients": [("Tomatoes", 800, "g"), ("Onion", 1, ""), ("Garlic", 2, "cloves"),
                            ("Stock", 500, "ml"), ("Olive oil", 2, "tbsp")],
            "method": "Soften the onion and garlic in the oil.\nAdd the tomatoes and stock, and simmer.\n"
                      "Blend until smooth, and season to taste.",
        },
        "Fried rice": {
            "serves": 2,
            "minutes": 12,
            "ingredients": [("Cooked rice", 300, "g"), ("Peas", 100, "g"), ("Eggs", 2, ""), ("Soy sauce", 2, "tbsp"),
                            ("Spring onions", 3, "")],
            "method": "Scramble the eggs in a hot wok and set them aside.\nFry the rice and peas, then add the "
                      "eggs back with the soy sauce.\nScatter the spring onions over it.",
        },
    },
    "Dessert": {
        "Fruit salad": {
            "serves": 4,
            "minutes": 10,
            "ingredients": [("Apples", 2, ""), ("Oranges", 2, ""), ("Grapes", 200, "g"), ("Lemon juice", 1, "tbsp")],
            "method": "Chop the fruit into bite-sized pieces.\nToss it with the lemon juice so it stays fresh.",
        },
    },
}
