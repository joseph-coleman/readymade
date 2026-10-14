"""The debugger in the program (readymade.debugger), driven by a pretend IDE: no windows."""

import importlib.util
import json
import sys
import textwrap

import pytest

from readymade import debugger, protocol

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
        protocol.check(message)  # one of the messages the IDE knows
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


def test_break_when_true_of_something_neither_true_nor_false(tmp_path, shop):
    module, _ = shop
    ide = PretendIDE("continue")
    dbg = make(tmp_path, ide)
    ambiguous = "Ambiguous() if count > 0 else False"  # (as numpy's arrays and a DataTable's Columns are)
    module.Ambiguous = type("Ambiguous", (), {"__bool__": lambda self: 1 / 0, "__repr__": lambda self: "Ambiguous()"})
    dbg.set_watches([watch(ambiguous, kind="true", function="total", file="shop.py")])
    assert module.checkout([1, 2, 3]) == 8  # the program carries on after the one pause
    stop, = ide.paused()  # once: not again while it stays that way
    assert stop["reason"] == "watch" and stop["message"] == (
        f"can't tell whether {ambiguous} is true (ZeroDivisionError: division by zero) on line {LINE['count += price']}")
    shown, = stop["watches"]
    assert shown["value"] == "Ambiguous()" and shown["note"] == "neither true nor false: ZeroDivisionError: division by zero"


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


# ----- breakpoint conditions, hit counts, Set Next Statement, starting -----

def test_a_breakpoint_with_a_condition(tmp_path, shop):
    module, path = shop
    ide = PretendIDE()
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [{"line": LINE["count += price"], "condition": "price > 4"}]})
    module.total([1, 5, 2, 9])
    assert [names(s)["price"] for s in ide.paused()] == ["5", "9"]
    assert ide.paused()[0]["message"] == "price > 4 is true"


def test_hit_counts(tmp_path, shop):
    module, path = shop
    for mode, hits, wanted in (("=", 3, ["3"]), (">=", 3, ["3", "4", "5"]), ("%", 2, ["2", "4"])):
        ide = PretendIDE()
        dbg = make(tmp_path, ide)
        dbg.set_breakpoints({path: [{"line": LINE["count += price"], "hit_mode": mode, "hits": hits}]})
        module.total([1, 2, 3, 4, 5])
        assert [names(s)["price"] for s in ide.paused()] == wanted, mode
        sys.settrace(None)
    assert ide.paused()[0]["message"] == "hit 2 times"


def test_hit_counts_survive_other_breakpoint_changes(tmp_path, shop):
    module, path = shop
    counted = {"line": LINE["count += price"], "hit_mode": "=", "hits": 3}
    ide = PretendIDE()
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [counted]})
    module.total([1, 2])  # two hits
    dbg.set_breakpoints({path: [counted, LINE["return result"]]})  # (another one added)
    module.total([3])  # the third
    assert [names(s)["price"] for s in ide.paused()] == ["3"]


def test_a_broken_condition_stops_and_says(tmp_path, shop):
    module, path = shop
    ide = PretendIDE()
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [{"line": LINE["count = 0"], "condition": "nonsense > 1"}]})
    module.total([1])
    assert ide.paused()[0]["message"] == ("The breakpoint's condition nonsense > 1 failed: "
                                          "NameError: name 'nonsense' is not defined")


def test_set_next_statement(tmp_path, shop):
    module, path = shop
    ide = PretendIDE({"cmd": "jump", "file": path, "line": LINE["return count"]},  # skip the loop
                     {"cmd": "jump", "file": path, "line": LINE["tax = 2"]},  # another function
                     "continue")
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [LINE["for price in prices:"]]})
    assert module.total([1, 2]) == 0
    first, moved = ide.paused()
    assert where(moved) == ("total", LINE["return count"]) and moved["reason"] == first["reason"]
    notes = [m["text"] for m in ide.told if m["event"] == "note"]
    assert notes[-1].startswith(f"Can't go on from line {LINE['tax = 2']}: ")


def test_no_set_next_statement_after_an_error(tmp_path, shop):
    module, path = shop
    ide = PretendIDE({"cmd": "jump", "file": path, "line": LINE['name = order["name"]']}, "continue")
    dbg = make(tmp_path, ide)
    try:
        module.broken({"name": "tea"})
    except KeyError as error:
        dbg.post_mortem(error, starting=True)
    assert ide.paused()[0]["ends"] is True
    note, = [m for m in ide.told if m["event"] == "note"]
    assert "after an error" in note["text"]


def test_starting_in_step_mode(tmp_path, shop):
    module, path = shop
    ide = PretendIDE()
    dbg = debugger.start(ide, tmp_path, {"step": True})
    dbg.break_into_event()  # the first event
    module.total([1])
    assert where(ide.paused()[0]) == ("total", LINE["count = 0"])


# ----- logpoints, breaking where errors are raised, changing values -----

def test_a_logpoint_logs_instead_of_stopping(tmp_path, shop):
    module, path = shop
    ide = PretendIDE()
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [
        {"line": LINE["count += price"], "log": "adding {price}, {count=}", "condition": "price > 1"},
        {"line": LINE["return count"], "log": "{nonsense}"},
    ]})
    assert module.total([1, 2, 3]) == 6
    assert ide.paused() == []
    logs = [m["text"] for m in ide.told if m["event"] == "log"]
    assert logs == ["adding 2, count=1", "adding 3, count=3",
                    "{nonsense}  <NameError: name 'nonsense' is not defined>"]


def test_breaking_where_an_error_is_raised(tmp_path, shop):
    module, path = shop
    ide = PretendIDE("continue")
    dbg = make(tmp_path, ide)
    dbg.break_on_all = True
    dbg.trace_if_needed()
    try:
        module.broken({"name": "tea"})  # a KeyError, caught by this try
    except KeyError as error:
        caught = error
    stop, = ide.paused()  # once, where it was raised (not again in each frame it leaves)
    assert stop["reason"] == "raised" and stop["message"] == "KeyError: 'missing'" and stop["stepping"]
    assert where(stop) == ("broken", LINE['return name.upper() + order["missing"]'])
    assert dbg.raised_here(caught)  # (an event that fails with it doesn't pause again)


def test_errors_that_are_how_python_works_dont_stop(tmp_path, shop):
    module, _ = shop
    ide = PretendIDE()
    dbg = make(tmp_path, ide)
    dbg.break_on_all = True
    dbg.trace_if_needed()
    assert module.total(iter([1, 2])) == 3  # (StopIteration ends the loop)
    assert ide.paused() == []


def test_changing_values_while_paused(tmp_path, shop):
    module, path = shop
    ide = PretendIDE({"cmd": "assign", "path": ["self", "items", "[0]"], "value": "'milk'"},
                     {"cmd": "assign", "path": ["self", "owner", "'name'"], "value": "'Bo' * 2"},
                     {"cmd": "assign", "path": ["self", "owner"], "value": "nonsense"},
                     {"cmd": "assign", "path": ["self", "items"], "value": "('a', 'tuple')"},
                     {"cmd": "assign", "path": ["self", "items", "[1]"], "value": "'x'"},
                     "continue")
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [LINE["self._secret = 1"]]})
    basket = module.Basket()
    assert basket.items == ("a", "tuple") and basket.owner == {"name": "BoBo"}
    notes = [m["text"] for m in ide.told if m["event"] == "note"]
    assert notes == ["Can't change self.owner: NameError: name 'nonsense' is not defined",
                     "Can't change self.items[1]: TypeError: a tuple's items can't be changed"]
    frames = [m for m in ide.told if m["event"] == "frame"]
    assert len(frames) == 5  # Locals shows the new values after each


def test_changing_a_variable_while_paused(tmp_path, shop):
    module, path = shop
    ide = PretendIDE({"cmd": "assign", "path": ["prices"], "value": "[10, 20]"}, "continue")
    dbg = make(tmp_path, ide)
    dbg.set_breakpoints({path: [LINE["for price in prices:"]]})
    result = module.total([1])
    notes = [m["text"] for m in ide.told if m["event"] == "note"]
    if sys.version_info >= (3, 13):
        assert result == 30 and notes == []
    else:
        assert result == 1 and "before Python 3.13" in notes[0]
