"""The debugger in the program (readymade.debugger), driven by a pretend IDE: no windows."""

import importlib.util
import json
import sys
import textwrap

import pytest

from readymade import debugger

CODE = textwrap.dedent('''\
    import json


    def total(prices):
        count = 0
        for price in prices:
            count += price
        return count


    def checkout(prices):
        tax = 2
        subtotal = total(prices)
        result = subtotal + tax
        return result


    def broken(order):
        name = order["name"]
        return name.upper() + order["missing"]


    def uses_a_library(data):
        text = json.dumps(data)
        return len(text)


    class Basket:
        def __init__(self):
            self.items = ["tea", "jam"]
            self.owner = {"name": "Ada"}
            self._secret = 1
''')
LINE = {text.strip(): n for n, text in enumerate(CODE.splitlines(), 1) if text.strip()}


class PretendIDE:
    """A channel: the commands to send, in order, and what the program told it."""

    def __init__(self, *commands):
        self.commands = [c if isinstance(c, dict) else {"cmd": c} for c in commands]
        self.told = []

    def send(self, **message):
        json.dumps(message)  # it must travel as JSON
        self.told.append(message)

    def receive(self, timeout=None):
        return self.commands.pop(0) if self.commands else {"cmd": "continue"}

    def paused(self):
        return [m for m in self.told if m["event"] == "paused"]


@pytest.fixture
def shop(tmp_path):
    path = tmp_path / "shop.py"
    path.write_text(CODE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("shop", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module, str(path)
    sys.settrace(None)


def make(tmp_path, ide):
    return debugger.Debugger(ide, tmp_path)


def where(message):
    top = message["stack"][-1]
    return top["function"], top["line"]


def names(message):
    return {v["name"]: v["value"] for v in message["locals"]}


def test_breakpoint_and_stepping(tmp_path, shop):
    module, path = shop
    ide = PretendIDE("next", "step", "next")
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [LINE["subtotal = total(prices)"]]})
    assert module.checkout([1, 2, 3]) == 8  # it still works
    stops = ide.paused()
    assert [where(m) for m in stops] == [
        ("checkout", LINE["subtotal = total(prices)"]),  # the breakpoint
        ("checkout", LINE["result = subtotal + tax"]),  # step over the call
        ("checkout", LINE["return result"]),  # step into: nothing to go into
    ]  # stepping on returns to the test, which isn't the project's: no stop there
    assert stops[0]["reason"] == "breakpoint" and stops[1]["reason"] == "step"
    assert names(stops[1])["subtotal"] == "6" and names(stops[1])["tax"] == "2"
    assert [f["function"] for f in stops[0]["stack"]] == ["checkout"]  # only the project's frames
    assert ide.told[-1] == {"event": "running"}


def test_step_into_and_out(tmp_path, shop):
    module, path = shop
    ide = PretendIDE("step", "return", "continue")
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [LINE["subtotal = total(prices)"]]})
    module.checkout([5])
    stops = ide.paused()
    assert where(stops[1]) == ("total", LINE["count = 0"])  # stepped into total()
    assert [f["function"] for f in stops[1]["stack"]] == ["checkout", "total"]
    assert where(stops[2])[0] == "checkout"  # stepped out, back in checkout


def test_library_code_is_stepped_over(tmp_path, shop):
    module, path = shop
    ide = PretendIDE("step", "step", "continue")
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [LINE["text = json.dumps(data)"]]})
    module.uses_a_library({"a": 1})
    assert [where(m)[0] for m in ide.paused()] == ["uses_a_library"] * len(ide.paused())  # never in json


def test_run_to_cursor(tmp_path, shop):
    module, path = shop
    ide = PretendIDE({"cmd": "until", "file": path, "line": LINE["return count"]}, "continue")
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [LINE["count = 0"]]})
    module.total([1, 2])
    stops = ide.paused()
    assert where(stops[1]) == ("total", LINE["return count"]) and names(stops[1])["count"] == "3"


def test_immediate_in_the_paused_function(tmp_path, shop, capsys):
    module, path = shop
    ide = PretendIDE({"cmd": "eval", "line": "print(prices, tax * 10)"}, {"cmd": "eval", "line": "tax = 5"}, "continue")
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [LINE["subtotal = total(prices)"]]})
    result = module.checkout([1])
    assert "[1] 20" in capsys.readouterr().out
    if sys.version_info >= (3, 13):
        assert result == 6  # assigning to a local stuck (PEP 667)
    frames = [m for m in ide.told if m["event"] == "frame"]
    assert frames and names(frames[-1])["tax"] == ("5" if sys.version_info >= (3, 13) else "2")


def test_break_at_an_error(tmp_path, shop):
    module, path = shop
    ide = PretendIDE({"cmd": "eval", "line": "print('in', name)"}, {"cmd": "frame", "index": 0}, "continue")
    dbg = make(tmp_path, ide)
    try:
        module.broken({"name": "tea"})
    except KeyError as error:
        dbg.post_mortem(error)
    stop = ide.paused()[0]
    assert stop["reason"] == "error" and stop["message"] == "KeyError: 'missing'"
    assert where(stop) == ("broken", LINE['return name.upper() + order["missing"]'])
    assert names(stop)["name"] == "'tea'" and stop["stepping"] is False
    assert any(m["event"] == "frame" for m in ide.told)


def test_expanding_values(tmp_path, shop):
    module, _ = shop
    basket = module.Basket()
    info = debugger.value_info("basket", basket, ["basket"])
    assert info["expandable"] and info["type"] == "Basket"
    parts = dict(debugger._children(basket))
    assert set(parts) == {"items", "owner"}  # no _secret, no methods
    assert [name for name, _ in debugger._children(basket.items)] == ["[0]", "[1]"]
    assert [name for name, _ in debugger._children(basket.owner)] == ["'name'"]
    assert not debugger.value_info("n", 3, ["n"])["expandable"]
    assert debugger.value_info("d", {"b": 1, "a": 2}, ["d"])["value"] == "{'b': 1, 'a': 2}"  # in its own order


def test_pause_at_the_next_event(tmp_path, shop):
    module, _ = shop
    ide = PretendIDE("continue")
    dbg = make(tmp_path, ide)
    dbg.pause_at_next_event()
    dbg.break_into_event()  # an event handler starts
    module.total([1])
    assert where(ide.paused()[0]) == ("total", LINE["count = 0"])
    sys.settrace(None)


# ----- watches -----

def watch(expression, kind="watch", function="", file=""):
    return {"expression": expression, "kind": kind, "function": function, "file": file}


def test_watch_values_when_paused(tmp_path, shop):
    module, path = shop
    ide = PretendIDE("step", "continue")
    dbg = make(tmp_path, ide)
    dbg.set_watches([watch("prices[0] * 10"), watch("count", function="total"), watch("nonsense +"),
                     watch("missing_name")])
    dbg.set_breakpoints({path: [LINE["subtotal = total(prices)"]]})
    module.checkout([4, 5])
    first, second = ide.paused()
    assert [(w["name"], w["value"]) for w in first["watches"]] == [
        ("prices[0] * 10", "40"),
        ("count", "<out of context>"),  # only in total()
        ("nonsense +", "\"<can't read: nonsense +>\""),
        ("missing_name", "<NameError: name 'missing_name' is not defined>"),
    ]
    assert where(second)[0] == "total" and second["watches"][0]["value"] == "40"
    assert second["watches"][1]["value"].startswith("<NameError")  # in context, but not assigned yet


def test_break_when_true(tmp_path, shop):
    module, _ = shop
    ide = PretendIDE("continue")
    dbg = make(tmp_path, ide)
    dbg.set_watches([watch("count > 4", kind="true", function="total", file="shop.py")])
    module.checkout([1, 2, 3])
    stop, = ide.paused()  # once, when it became true (not again while it stays true)
    assert stop["reason"] == "watch" and stop["message"] == f"count > 4 became true on line {LINE['count += price']}"
    assert stop["changed_line"] == LINE["count += price"]  # the line that did it, before where it paused
    assert where(stop) == ("total", LINE["for price in prices:"]) and names(stop)["count"] == "6"


def test_break_when_it_changes(tmp_path, shop):
    module, _ = shop
    ide = PretendIDE("continue", "continue", "continue")
    dbg = make(tmp_path, ide)
    dbg.set_watches([watch("count", kind="changes", function="total")])
    module.total([5, 0, 7])
    stops = ide.paused()
    assert [s["message"] for s in stops] == [
        f"count was set to 0 on line {LINE['count = 0']}",  # (it didn't exist before)
        f"count changed from 0 to 5 on line {LINE['count += price']}",
        f"count changed from 5 to 12 on line {LINE['count += price']}",
    ]
    assert all(where(s)[0] == "total" for s in stops)  # (adding 0 changed nothing)


def test_a_change_on_the_last_line(tmp_path, shop):
    module, _ = shop
    ide = PretendIDE()
    dbg = make(tmp_path, ide)
    dbg.set_watches([watch("self._secret", kind="changes", function="__init__")])
    module.Basket()
    stop, = ide.paused()  # as __init__ returns: no line comes after
    assert stop["message"] == f"self._secret was set to 1 on line {LINE['self._secret = 1']}"
    assert where(stop) == ("__init__", LINE["self._secret = 1"])


def test_a_function_watch_as_the_function_left_it(tmp_path, shop):
    module, _ = shop
    dbg = make(tmp_path, PretendIDE())
    dbg.set_watches([watch("count", function="total"), watch("prices", function="total")])
    assert [w["value"] for w in dbg._watch_values()] == ["<out of context>"] * 2  # (it hasn't run)
    module.total([1, 2])
    count, prices = dbg._watch_values()
    assert (count["value"], count["note"]) == ("3", "as total left it")
    assert prices["expandable"] and [c["value"] for c in dbg._expand(["#watch", 1])] == ["1", "2"]


def test_expanding_a_watch(tmp_path, shop):
    module, path = shop
    ide = PretendIDE({"cmd": "expand", "path": ["#watch", 0]}, {"cmd": "quick", "expression": "len(prices) + 1"},
                     "continue")
    dbg = make(tmp_path, ide)
    dbg.set_watches([watch("{'n': prices}")])
    dbg.set_breakpoints({path: [LINE["tax = 2"]]})
    module.checkout([3])
    children = next(m for m in ide.told if m["event"] == "children")
    assert [(c["name"], c["value"], c["path"]) for c in children["items"]] == [("'n'", "[3]", ["#watch", 0, "'n'"])]
    quick = next(m for m in ide.told if m["event"] == "quick")
    assert quick["info"]["value"] == "2"
