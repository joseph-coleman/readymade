# To do

Ideas and gaps noted along the way, roughly by area.

## Runtime
- **Menu item `visible`**: Tk can't hide a menu entry; supporting it means rebuilding the menu.
- **Debugging threads** (future): breaking in threads started with `in_thread` (tracing is only on the program's main thread). First, more examples that use threads, to get a feel for how pausing one thread should affect the others in this kind of program.
- **Edit and continue** (tabled): VB let you change code while paused. Python can't swap the code of a function that's running, so today edits take effect next run (a note above the code says so).

## IDE
- **Project Files follow-ups**: new files and folders from the Project Explorer; renaming files; noticing files added or changed outside the IDE (today: Project > Refresh); Markdown shown formatted.
- **Search and Replace**:  The ability to search for a term in a code file and optionally replace occurrences of it.
- **Project Explorer**: when a form is removed, point out code that still uses it (`forms.Name`, imports); rename a form from the Explorer (today: its name in the Properties panel).
- **Environments**: create conda/mamba environments (existing ones work via Choose Python Interpreter).
- **Add Library**: keep comments inside the `dependencies` list when it's rewritten.
- **Code window**: after jumping to a run-time error, name the handler in the Object/Event dropdowns.
- **Renaming a form**: also update references to it in other files (like `forms.OldName`).
- **Watch**: Interface quirk? When something is being watched and either "Break when value is true" or "Break when the value changes is true" is selected, that type of watch condition is effectively a breakpoint. It doesn't correspond to any particular line in the program because it is a vastly more broad observation tool.  I had a watch that was breaking on a variable change and I was confused because I didn't see any breakpoints explicitly set. And it's not obvious from the Watches window what type a watch is--the "Type" in that view is for variable type, not monitor or break watch type.  Something to think about in terms of visibility and usability.

## Code editor
- **Options follow-ups**: more themes; mark a run-time error's line in the line numbers; let a project ask for an indent width (today it's each person's, and generated handlers always use 4). Dark gaps: the menu bar on Windows and macOS (the system draws it), dialogs' title bars on Windows (only the main window's is dark), and the font chooser's family list.
- **A modern look**: the Sun Valley ttk theme (`sv-ttk`, MIT, pip-installable) gives ttk widgets a Windows 11 look in light and dark. It could go in the `ide` extra, used when installed and falling back to today's clam-based look. Tabs, buttons, fields, scrollbars and lists would change; the Toolbox buttons (plain Tk), the code area and the menus keep their own colors, and Windows still draws its menu bar white (darkening it needs undocumented Windows calls).
- **Folding** and an outline, from an error-tolerant parser (parso, MIT). The same parsing would let Enter see past the current line: today, after a call spread over several lines, the next line keeps the continuation indent instead of returning to the statement's level.
- **A language server option (LSP)**: completion and definitions use Jedi today. An LSP client would let people choose Pyright (or basedpyright, which pip-installs with its own Node.js), python-lsp-server, jedi-language-server or Ruff's server, configured like linting, and would also bring hover info, signature help and rename. Pylance can't be used outside Microsoft's VS Code. The form-control declarations (assist.py) carry over, as the IDE chooses the text it sends.
- **Completion follow-ups**: `forms.<name>` (forms are found by name at run time), signatures and docstrings beside the list, Back after Go to Definition (Alt+Left).
- **Help follow-ups**: show help beside the completion list for the chosen entry; help on hover; links between topics (a property's help linking to its control); format reStructuredText and Google-style docstrings instead of showing them as plain text.
  - Color codes get stripped out via PYTHON_COLORS or NO_COLOR because that broke the "jump to error line" feature.  Is there ever a situation where colors in help could be useful?
- **Formatting follow-ups**: format just the selection; let a project insist on no formatting (today an unset project falls back to each person's default); format in the background instead of briefly waiting with a busy cursor.
- **Linting follow-ups**: quick fixes (`ruff check --fix`); different colors for errors and warnings; pylint/mypy checking as you type via a temporary copy. The Problems tab: sort by column, filter by file or tool, and notice files added or changed outside the IDE.
- These libraries would be IDE-only dependencies, like Pygments in the `ide` extra (`pip install -e ".[ide]"`), so programs never need them.

## Bigger features
- **Anchor follow-ups**: a visual anchor picker in the Properties panel (four edges to click, as in Visual Studio) instead of the dropdown; a form `minwidth`/`minheight` so anchored controls can't be squeezed together; `dock` (fill an edge of the form, as WinForms' Dock does).
- **Make EXE options**: one-folder instead of one-file, version details (Windows' file properties); license notices for readymade, Python and the bundled libraries next to the program, for people who give their programs away (MIT and the PSF license ask for the notice to come along). The program's icon is done (Project > Program Icon). (Extra files are bundled: pictures the forms show, and `[tool.readymade] include`; perhaps an Include list in the Project Explorer rather than editing pyproject.toml.) Perhaps a small dialog, with various build options. Options true everywhere (icon, name) belong in `pyproject.toml`'s `[tool.readymade]`; anything tied to one machine (a signing certificate, an interpreter) in `.readymade/local.json`, kept per machine and out of git.
    - Longer term idea, executables need to be able to be signed. 
- **More controls**: third-party controls from installed libraries appearing in the Toolbox.
- **Image drawing follow-ups**: flood fill (Pillow's `ImageDraw.floodfill`); mouse coordinates in the picture's pixels when it's scaled (stretch, zoom) or centered; anti-aliased shapes (Pillow draws them jagged; drawing larger and shrinking is the usual trick); undo for paint programs (keep copies of the picture).
- **Canvas follow-ups**: keyboard events (a Tk canvas takes no focus by default); scrolling and zooming a canvas bigger than the control; saving a canvas as a picture (Tk can only write PostScript, so this needs drawing through Pillow too); dragging shapes with less code (perhaps `shape.draggable = True`).
- **Appearance follow-ups**: a form `font` that new controls start with (as VB's form Font was); colors for disabled controls (Tk grays them its own way); `selectcolor` for check box and option button indicators. Known limits: macOS buttons keep the system's colors, and Windows' native theme may ignore a ComboBox's field color (both are Tk's).
- **TextBox follow-ups**: `readonly` on a multi-line box can't be copied from with the keyboard (it's a disabled Text underneath, which takes no focus from a click); `maxlength` doesn't stop a middle-click paste on Linux.
- **Keyboard follow-ups**: `tabstop` (leave a control out of the Tab order without disabling it); arrow keys moving between the OptionButtons of a group, with only the chosen one a Tab stop (as in Windows); a `keydown`/`keyup` pair for games (keypress repeats while a key is held).
- **Image follow-ups**: show an Image's outline in the designer when its picture is smaller than the control (sizing normal, center or zoom); offer to delete a copied picture from images/ when nothing uses it any more; animated GIFs; pictures on Buttons and Labels (Tk supports both).

## Biggest features
- **Grid follow-ups**: add and remove rows and columns from the designer (today: the Grid's `columns` and `rows` properties); show each track's size along the Grid's edges; a form that sizes itself to its contents; single-direction rows and columns (a `Stack`, like Qt's QHBoxLayout/QVBoxLayout), which would also cover Tk's pack.
- **Backend Swappable**:  Being able to design for a PyQt6 or some other GUI backend instead of Tkinter for a project.  There are two optional paths to this: One is keeping Tkinter for the IDE and designing a project with a different GUI backend, or having the IDE match the target project GUI.  Is a GUI target potentially a plugin?  Either way, this looks like a separation of concerns type of refactor.
  - Keep readymade's own API free of Tk: shapes are readymade objects, colors `#rrggbb`, angles in degrees, fonts `(family, size, style)`. Still Tk-specific: color names Canvas shapes accept beyond `#rrggbb`, and `.widget` / `form.root` (fine as documented escape hatches). If Qt: PySide6 (LGPL) rather than PyQt6 (GPL), for programs made with Make EXE.
- **Plugins**: A plugin architecture to extend features.  Allow other people to create plugins like VB or VS Code allows.
