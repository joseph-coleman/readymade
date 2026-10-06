# To do

Ideas and gaps noted along the way, roughly by area.

## Runtime
- **Menu item `visible`**: Tk can't hide a menu entry; supporting it means rebuilding the menu.
- **Break mode**: pause a running program at an error, as VB did (needs a debugger).
- **macOS shortcuts**: treat "Ctrl" as ⌘ (Command) and "Alt" as Option on macOS, the way Qt and Electron's CmdOrCtrl do, and show native ⌘O labels. Needs a Mac to check how Tk on macOS parses accelerator labels, and whether its native menus already fire the shortcut (which would make pybasic's own binding run handlers twice).

## IDE
- **Copy and paste**: optionally bring the controls' event handlers along (renamed to match), which VB never did. Also a selection box inside a Frame (today it only works on the form itself; Ctrl+click works anywhere).
- **Project Explorer**: remove a form, module or library.
- **Environments**: create conda/mamba environments (existing ones work via Choose Python Interpreter).
- **Add Library**: keep comments inside the `dependencies` list when it's rewritten.
- **Code window**: after jumping to a run-time error, name the handler in the Object/Event dropdowns.
- **Renaming a form**: also update references to it in other files (like `forms.OldName`).

## Code editor
- **Settings**: indent width (4 spaces today, a constant in `pybasic/ide/codeview.py`), font, theme. Needs an IDE settings dialog.
- **Themes**: a dark theme; the colours are all in `pybasic/ide/highlight.py`. Also mark a run-time error's line in the line numbers.
- **Folding** and an outline, from an error-tolerant parser (parso, MIT). The same parsing would let Enter see past the current line: today, after a call spread over several lines, the next line keeps the continuation indent instead of returning to the statement's level.
- **A language server option (LSP)**: completion and definitions use Jedi today. An LSP client would let people choose Pyright (or basedpyright, which pip-installs with its own Node.js), python-lsp-server, jedi-language-server or Ruff's server, configured like linting, and would also bring hover info, signature help and rename. Pylance can't be used outside Microsoft's VS Code. The form-control declarations (assist.py) carry over, as the IDE chooses the text it sends.
- **Completion follow-ups**: `forms.<name>` (forms are found by name at run time), signatures and docstrings beside the list, Back after Go to Definition (Alt+Left).
- **Help follow-ups**: show help beside the completion list for the chosen entry; help on hover; links between topics (a property's help linking to its control); format reStructuredText and Google-style docstrings instead of showing them as plain text.
  - Color codes get stripped out via PYTHON_COLORS or NO_COLOR because that broke the "jump to error line" feature.  Is there ever a situation where colors in help could be useful?
- **Formatting follow-ups**: format just the selection; let a project insist on no formatting (today an unset project falls back to each person's default); format in the background instead of briefly waiting with a busy cursor.
- **Linting follow-ups**: a Problems list next to the Immediate window (every problem in the project, click to jump); quick fixes (`ruff check --fix`); different colours for errors and warnings; pylint/mypy checking as you type via a temporary copy.
- These libraries would be IDE-only dependencies, like Pygments in the `ide` extra (`pip install -e ".[ide]"`), so programs never need them.

## Bigger features
- **Make EXE options**: an icon, one-folder instead of one-file, version details. (Extra files are bundled: pictures the forms show, and `[tool.pybasic] include`; perhaps an Include list in the Project Explorer rather than editing pyproject.toml.) Perhaps a small dialog, with various build options. Options true everywhere (icon, name) belong in `pyproject.toml`'s `[tool.pybasic]`; anything tied to one machine (a signing certificate, an interpreter) in `.pybasic/local.json`, kept per machine and out of git.
    - Longer term idea, executables need to be able to be signed. 
- **More controls**: third-party controls from installed libraries appearing in the Toolbox.
- **Image drawing follow-ups**: flood fill (Pillow's `ImageDraw.floodfill`); mouse coordinates in the picture's pixels when it's scaled (stretch, zoom) or centred; anti-aliased shapes (Pillow draws them jagged; drawing larger and shrinking is the usual trick); undo for paint programs (keep copies of the picture).
- **Canvas follow-ups**: keyboard events (a Tk canvas takes no focus by default); scrolling and zooming a canvas bigger than the control; saving a canvas as a picture (Tk can only write PostScript, so this needs drawing through Pillow too); dragging shapes with less code (perhaps `shape.draggable = True`).
- **Appearance follow-ups**: a form `font` that new controls start with (as VB's form Font was); colours for disabled controls (Tk greys them its own way); `selectcolor` for check box and option button indicators. Known limits: macOS buttons keep the system's colours, and Windows' native theme may ignore a ComboBox's field colour (both are Tk's).
- **More properties**: TextBox `readonly`, `password` and `maxlength`; `tooltip`; `tag`.
- **Keyboard follow-ups**: `tabstop` (leave a control out of the Tab order without disabling it); arrow keys moving between the OptionButtons of a group, with only the chosen one a Tab stop (as in Windows); access keys (Alt+letter from an `&` in a caption); a `keydown`/`keyup` pair for games (keypress repeats while a key is held).
- **Image follow-ups**: show an Image's outline in the designer when its picture is smaller than the control (sizing normal, center or zoom); offer to delete a copied picture from images/ when nothing uses it any more; animated GIFs; pictures on Buttons and Labels (Tk supports both).

## Biggest features
- **Form Packing**: Tkinter supports more than just absolute positioning and sizing for widgets.  Supporting grid or packing schemes would really elevate this above what VB could ever do.
  - The Format menu (align, same size, spacing, center, order) is for absolutely placed controls only; its pure geometry lives in `pybasic/ide/arrange.py`. Grid/pack containers would disable it for their controls or offer their own equivalents (sticky, anchor, padx/pady, weights). Selections already stay within one container, so the container can decide which tools apply.
- **Backend Swappable**:  Being able to design for a PyQt6 or some other GUI backend instead of Tkinter for a project.  There are two optional paths to this: One is keeping Tkinter for the IDE and designing a project with a different GUI backend, or having the IDE match the target project GUI.  Is a GUI target potentially a plugin?  Either way, this looks like a separation of concerns type of refactor.
  - Keep pybasic's own API free of Tk: shapes are pybasic objects, colours `#rrggbb`, angles in degrees, fonts `(family, size, style)`. Still Tk-specific: colour names Canvas shapes accept beyond `#rrggbb`, and `.widget` / `form.root` (fine as documented escape hatches). If Qt: PySide6 (LGPL) rather than PyQt6 (GPL), for programs made with Make EXE.
- **Plugins**: A plugin architecture to extend features.  Allow other people to create plugins like VB or VS Code allows.
