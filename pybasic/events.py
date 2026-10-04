"""Keeping forms responsive while handlers work, and what happens to events
that arrive while a handler is busy.

Ways to let the window breathe during long work:

    async def btnGo_click(self):                 # an async handler: the usual choice
        for row in rows:
            ...
            await pause()                        # let the window handle clicks and repaint
        total = await in_thread(crunch, data)    # slow or blocking work, off the GUI thread

    def btnGo_click(self):                       # VB style
        for row in rows:
            ...
            doevents()

Code between awaits runs on the GUI thread, so it can use controls freely.

While a handler is busy (awaiting, or inside doevents()), a new event for the
same handler follows a policy:

    "ignore"   drop it (the default, e.g. for clicks: no accidental double start)
    "latest"   run once more afterwards, for the latest one (change, resize, timer, selections)
    "queue"    run every one, in order, afterwards (keypress, mouse down/up)
    "overlap"  run it straight away, nested, as VB's DoEvents did

@while_running("queue") above a handler changes its policy. When a form
closes, its busy handlers stop quietly: async ones are cancelled, and
doevents() in one raises FormClosed, which pybasic catches.
"""

from __future__ import annotations

import asyncio
import collections
import inspect
import threading
import time
import tkinter as tk
import traceback

POLICIES = ("ignore", "latest", "queue", "overlap")
_DEFAULTS = {"change": "latest", "resize": "latest", "timer": "latest",
             "keypress": "queue", "mousedown": "queue", "mouseup": "queue"}
_SLICE = 0.008  # seconds of async work at a time before the window gets a turn
_WAITING = 10  # ms between checks while async handlers are only waiting


class FormClosed(Exception):
    """Raised inside a busy handler whose form has closed, to stop it. pybasic catches it."""


def while_running(policy):
    """Choose what happens to this handler's events while it's busy: @while_running("queue")."""
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of: {', '.join(POLICIES)}")

    def mark(func):
        func.pybasic_policy = policy
        return func

    return mark


def policy_for(func, event_name, declared=""):
    """A handler's policy: its @while_running, else what the event declares, else the default."""
    return getattr(func, "pybasic_policy", None) or declared or _DEFAULTS.get(event_name, "ignore")


async def pause(seconds=0):
    """Let the window handle events (and wait, if seconds is given): `await pause()`."""
    await asyncio.sleep(seconds)


async def in_thread(func, *args, **kwargs):
    """Run slow or blocking work in another thread and wait for its result:
    `total = await in_thread(crunch, data)`. Don't use controls from func.
    The thread doesn't keep the program alive once its forms have closed."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def settle(outcome, value):
        if not future.done():  # the handler may have been cancelled meanwhile
            future.set_result(value) if outcome == "result" else future.set_exception(value)

    def work():
        try:
            outcome, value = "result", func(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001 - handed over to the awaiting handler
            outcome, value = "error", e
        try:
            loop.call_soon_threadsafe(settle, outcome, value)
        except RuntimeError:
            pass  # the program has ended

    threading.Thread(target=work, daemon=True).start()
    return await future


def doevents():
    """VB's DoEvents: let the window handle waiting events, then carry on.
    If the handler's form closed meanwhile, the handler stops here (quietly)."""
    from pybasic.form import app_root

    try:
        app_root().update()
    except tk.TclError:  # the program has ended
        raise FormClosed() from None
    if _running and not _running[-1].form.loaded:
        raise FormClosed()


class Handler:
    """One of a form's event handlers, as Tk calls it: applies the handler's
    while-running policy, and runs async handlers on the event loop."""

    def __init__(self, form, func, policy):
        self.form = form
        self.func = func
        self.policy = policy
        self.busy = 0
        self.pending = collections.deque()

    def __call__(self, *args):
        if self.busy and self.policy != "overlap":
            if self.policy == "latest":
                self.pending.clear()
                self.pending.append(args)
            elif self.policy == "queue":
                self.pending.append(args)
            return None
        self.busy += 1
        if inspect.iscoroutinefunction(self.func):
            task = _event_loop().create_task(self._run_async(args))
            self.form._tasks.add(task)
            task.add_done_callback(self.form._tasks.discard)
            _keep_pumping()
            return None
        _running.append(self)
        try:
            return self.func(*args)
        except FormClosed:
            return None
        finally:
            _running.pop()
            self._done()

    async def _run_async(self, args):
        try:
            await self.func(*args)
        except (FormClosed, asyncio.CancelledError):
            pass
        except Exception:
            traceback.print_exc()  # as Tk does for other handlers, so the IDE can point at the line
        finally:
            self._done()

    def _done(self):
        self.busy -= 1
        if self.pending and not self.busy and self.form.loaded:
            args = self.pending.popleft()
            self.form.root.after_idle(lambda: self(*args))


_loop: asyncio.AbstractEventLoop | None = None
_pump_root = None  # the Tk root the event loop is being run from, while there's async work
_running: list[Handler] = []  # handlers running synchronously, innermost last


def _event_loop():
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


def _keep_pumping():
    """Make sure asyncio gets turns between Tk's events while there's async work."""
    global _pump_root
    from pybasic.form import app_root

    root = app_root()
    if _pump_root is not root:
        _pump_root = root
        root.after(0, _step)


def _step():
    global _pump_root
    loop = _event_loop()
    if not loop.is_running():  # it is if async code called doevents(); then it carries on by itself
        deadline = time.perf_counter() + _SLICE
        while True:
            loop.call_soon(loop.stop)
            loop.run_forever()  # one pass over whatever is ready
            # _ready is CPython's queue of ready callbacks: keep going while there's work, for a while.
            if not getattr(loop, "_ready", None) or time.perf_counter() >= deadline:
                break
    if not asyncio.all_tasks(loop):
        _pump_root = None  # nothing async left: stop polling
        return
    root = _pump_root
    if root is None:
        return
    busy = bool(getattr(loop, "_ready", None))
    try:
        root.after(1 if busy else _WAITING, _step)
    except tk.TclError:  # the program has ended
        _pump_root = None


def shutdown():
    """At the end of the program: stop async handlers that are still running."""
    global _loop, _pump_root
    _pump_root = None
    loop = _loop
    if loop is None or loop.is_closed():
        return
    tasks = asyncio.all_tasks(loop)
    for task in tasks:
        task.cancel()
    if tasks:
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
    loop.close()
    _loop = None
