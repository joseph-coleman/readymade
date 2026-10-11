import pytest

from readymade import codegen


def add(source, name, params=()):
    edit = codegen.add_method(source, "Form1", name, params)
    return edit.apply(source), edit.method_line


def test_first_handler_replaces_the_placeholder_pass():
    source, line = add(codegen.new_module("Form1"), "Button1_click")
    assert "class Form1(Form):\n    def Button1_click(self):\n        pass\n\n\nif __name__" in source
    assert source.splitlines()[line - 1] == "    def Button1_click(self):"
    compile(source, "Form1.py", "exec")


def test_later_handlers_go_at_the_end_of_the_class():
    source, _ = add(codegen.new_module("Form1"), "Form_load")
    source, line = add(source, "TextBox1_keypress", ("key",))
    assert source.splitlines()[line - 1] == "    def TextBox1_keypress(self, key):"
    assert source.index("Form_load") < source.index("TextBox1_keypress") < source.index("__main__")
    assert "        pass\n\n    def TextBox1_keypress" in source
    compile(source, "Form1.py", "exec")


def test_adding_works_while_the_code_has_a_syntax_error():
    source = "class Form1(Form):\n    def Form_load(self):\n        x = (\n"
    source, line = add(source, "Button1_click")
    assert source.splitlines()[line - 1] == "    def Button1_click(self):"


def test_adding_to_a_file_without_a_trailing_newline():
    source, line = add("class Form1(Form):\n    def Form_load(self):\n        pass", "Button1_click")
    assert source == (
        "class Form1(Form):\n    def Form_load(self):\n        pass\n\n    def Button1_click(self):\n        pass\n"
    )
    assert line == 5


def test_class_indentation_is_followed():
    source, _ = add("class Form1(Form):\n\tdef Form_load(self):\n\t\tpass\n", "Button1_click")
    assert "\tdef Button1_click(self):\n\t\tpass\n" in source


def test_missing_class_is_an_error():
    with pytest.raises(codegen.CodeGenError, match="class Form1"):
        codegen.add_method("x = 1\n", "Form1", "Form_load")


def test_find_and_list_methods():
    source = "class Form1(Form):\n    def Form_load(self):\n        pass\n\n    def Button1_click(self):\n        pass\n"
    assert codegen.find_method(source, "Button1_click") == 5
    assert codegen.find_method(source, "Button1_dblclick") is None
    assert codegen.defined_methods(source) == {"Form_load", "Button1_click"}


def test_rename_control_renames_handlers_and_references_only():
    source = (
        "class Form1(Form):\n"
        "    def Button1_click(self):\n"
        "        self.Button1.text = 'Button1'\n"
        "        self.Button10.text = ''\n"
        "    def Button1_helper(self):\n"
        "        pass\n"
    )
    renamed = codegen.rename_control(source, "Button1", "btnOK", ["click", "gotfocus"])
    assert "def btnOK_click(self):" in renamed
    assert "self.btnOK.text = 'Button1'" in renamed  # strings are left alone
    assert "self.Button10.text" in renamed
    assert "def Button1_helper" in renamed  # not an event handler


def test_rename_class():
    source = codegen.new_module("Form1")
    assert codegen.rename_class(source, "Form1", "Main") == codegen.new_module("Main")


def test_the_method_a_line_is_in():
    from readymade.codegen import method_at

    source = "class Form1(Form):\n    def Button1_click(self):\n        if x:\n\n            y = (\n" \
             "    1)\n        z = 1\n\n    async def Timer1_timer(self):\n        pass\n\nx = 1\n"
    assert [method_at(source, n) for n in (1, 2, 3, 5, 6, 7, 9, 10, 12)] == [
        None, "Button1_click", "Button1_click", "Button1_click", "Button1_click", "Button1_click", "Timer1_timer",
        "Timer1_timer", None]
