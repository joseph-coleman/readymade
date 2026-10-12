"""Recipe Box: readymade's controls doing a real job. README.md walks through it."""

from readymade import Form, inputbox, msgbox
from recipes import RECIPES

ALIGNMENTS = ("left", "center", "right")  # Align[0], Align[1], Align[2]


class Form1(Form):
    def Form_load(self):
        self.recipe = None  # the recipe showing: one of RECIPES' dicts
        for category, recipes in RECIPES.items():
            node = self.Recipes.add(category, key=category)
            for name in recipes:
                node.add(name)
            node.expanded = True
        self.Recipes.selected = self.Recipes.nodes[0].children[0]  # (runs Recipes_nodeclick)

    # ----- choosing a recipe -----

    def Recipes_nodeclick(self, node):
        if node.parent is None:  # a category
            self.Status.text = f"{node.text}: {len(node.children)} recipes"
            return
        self.recipe = RECIPES[node.parent.text][node.text]
        self.Servings.value = self.recipe["serves"]  # (Servings_change runs only if this changes it, so:)
        self.show_ingredients()
        self.Method.text = self.recipe["method"]
        self.Minutes.value = self.recipe["minutes"]
        self.Status.text = f"{node.text}: serves {self.recipe['serves']}, about {self.recipe['minutes']} minutes"

    def show_ingredients(self):
        """The ingredients, for the number of servings chosen."""
        self.Ingredients.clear()
        if self.recipe is None:
            return
        scale = self.Servings.value / self.recipe["serves"]
        for name, amount, unit in self.recipe["ingredients"]:
            scaled = amount * scale
            self.Ingredients.add(name, f"{scaled:g}" if scaled == int(scaled) else f"{scaled:.1f}", unit)

    def Servings_change(self):
        self.show_ingredients()

    # ----- the toolbar -----

    def NewRecipe_click(self):
        node = self.Recipes.selected
        category = (node.parent or node).text if node else self.Recipes.nodes[0].text
        name = inputbox(f"Name of the new {category.lower()} recipe:", "New recipe", "My recipe")
        if not name:
            return
        if name in RECIPES[category]:
            msgbox(f"There's already a recipe called {name}.", icon="warning")
            return
        RECIPES[category][name] = {"serves": 2, "minutes": 10, "ingredients": [], "method": ""}
        self.Recipes.selected = self.Recipes.node(category).add(name)

    def DeleteRecipe_click(self):
        node = self.Recipes.selected
        if node is None or node.parent is None:
            msgbox("Choose a recipe to delete.", icon="info")
            return
        name = node.text
        if msgbox(f"Delete {name}?", buttons="yesno", icon="question") == "yes":
            del RECIPES[node.parent.text][name]
            node.remove()  # (gone from the tree: from here on, name remembers it)
            self.recipe = None
            self.show_ingredients()
            self.Method.text = ""
            self.Status.text = f"Deleted {name}"

    def Bold_click(self):
        self.show_method_font()

    def Align_click(self, index):  # one handler for Align[0], Align[1] and Align[2]: a control array
        self.Method.alignment = ALIGNMENTS[index]

    # ----- the method -----

    def Method_change(self):
        if self.recipe is not None:
            self.recipe["method"] = self.Method.text  # (kept while the program runs)

    def TextSize_change(self):
        self.show_method_font()

    def show_method_font(self):
        self.Method.font = f", {self.TextSize.value}" + (", bold" if self.Bold.value else "")

    # ----- cooking -----

    def Minutes_change(self):
        self.MinutesValue.text = str(self.Minutes.value)

    def Start_click(self):
        if self.CookTimer.enabled:  # Stop
            self.CookTimer.enabled = False
            self.Start.text = "Start"
            self.CookStatus.text = "Stopped"
            return
        self.Progress.max = self.Minutes.value
        self.Progress.value = 0
        self.CookTimer.enabled = True  # each tick is a "minute" (interval 250: a quarter of a second)
        self.Start.text = "Stop"
        self.CookStatus.text = "Cooking..."

    def CookTimer_timer(self):
        self.Progress.value += 1
        left = self.Progress.max - self.Progress.value
        self.CookStatus.text = f"Cooking: {left} minute{'s' * (left != 1)} to go"
        if left == 0:
            self.CookTimer.enabled = False
            self.Start.text = "Start"
            self.CookStatus.text = "Ready!"
            msgbox("Ready!", "Recipe Box")


if __name__ == "__main__":
    Form1.run()
