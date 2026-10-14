# To do

Ideas and gaps noted along the way, roughly by area.

## Runtime
- **Menu item `visible`**: Tk can't hide a menu entry; supporting it means rebuilding the menu.
- **Debugging threads** (future): breaking in threads started with `in_thread` (tracing is only on the program's main thread). First, more examples that use threads, to get a feel for how pausing one thread should affect the others in this kind of program.
- **Edit and continue** (tabled): VB let you change code while paused. Python can't swap the code of a function that's running, so today edits take effect next run (a note above the code says so).

## IDE
- **Find follow-ups**: Replace in Files (today Find in Files finds; replacing is file by file); searching the Immediate window's output.
- **Project Files follow-ups**: Markdown shown formatted (a preview beside the text); dragging files into the Project Explorer from the system's file manager.
- **Environments**: create conda/mamba environments (existing ones work via Choose Python Interpreter).

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
- **Anchor and dock follow-ups**: a visual anchor picker in the Properties panel (four edges to click, as in Visual Studio) instead of the dropdown; dragging a docked control in the designer springs back (only its free edge resizes).
- **Make EXE follow-ups**: signing the program (Windows Authenticode, macOS codesign and notarizing; the certificate is per machine, in `.readymade/local.json`); a Mac app's bundle identifier; an installer (Inno Setup on Windows, a .dmg on the Mac); license notices for libraries that bundle other code of their own (today: each library's own license files).
- **More controls**: third-party controls from installed libraries appearing in the Toolbox (to decide: loading a library's controls from the project's environment into the IDE, with a labeled placeholder box when it can't load). VB's controls still missing, from Tk's own widgets:
  - **MaskedEdit**: as TextBox properties rather than a control (`mask = "(###) ###-####"`, numbers only), with Tk's validation.
  - **RichTextBox**: bold, colors and fonts in parts of the text (`tk.Text` tags); maybe a `rich` mode of TextBox. Loading and saving RTF probably isn't worth it.
  - **DataTable follow-ups**: a money kind (`decimal.Decimal`), dates, per-cell colors; perhaps `isin()` on a Column (`table["Size"].isin(["S", "M"])`).
  - **DTPicker / MonthView**: Tk has no calendar, and tkcalendar is GPL (not one to bundle in EXEs), so our own drop-down month.
  - Not planned: StatusBar and Toolbar (a docked Label, and a borderless docked Frame of `flat` picture Buttons and button-look toggles, do these with real controls); DriveListBox, DirListBox, FileListBox (the file dialogs and a TreeView do better), Data, OLE, WebBrowser (Windows COM, or a browser engine), Winsock, Inet, MSComm, MMControl (Python's libraries do these: socket, urllib, pyserial; examples with `in_thread` instead), ImageList (pictures come from `images/`), Line and Shape as controls (a Tk widget can't be see-through; Canvas draws them).
- **ScrollBar, Slider, UpDown, ProgressBar follow-ups**: tick marks on a Slider (ttk's Scale has none; VB's TickFrequency); colors for the bars (Windows' and macOS's own themes ignore them, so not offered yet); a `scroll` event apart from `change` (VB's ScrollBar had both: while dragging, and after); decimal values (today whole numbers, as in VB).
- **TabStrip, TreeView, ListView follow-ups**: access keys in tab captions (`&General`) and Ctrl+Tab between pages; pictures on TreeView nodes and ListView rows; ListView column widths saved from the designer, and its Icon and List views (Tk has neither); TreeView check boxes; editing a node's or row's text in place (VB's LabelEdit).
- **Control array follow-ups**: menu item arrays (VB had them, for a recent-files list).
- **Image drawing follow-ups**: flood fill (Pillow's `ImageDraw.floodfill`); mouse coordinates in the picture's pixels when it's scaled (stretch, zoom) or centered; anti-aliased shapes (Pillow draws them jagged; drawing larger and shrinking is the usual trick); undo for paint programs (keep copies of the picture).
- **Canvas follow-ups**: keyboard events (a Tk canvas takes no focus by default); scrolling and zooming a canvas bigger than the control; saving a canvas as a picture (Tk can only write PostScript, so this needs drawing through Pillow too); dragging shapes with less code (perhaps `shape.draggable = True`).
- **Appearance follow-ups**: the designer draws ttk controls (TabStrip, ScrollBar, Slider, ProgressBar, UpDown, ComboBox, the trees, flat buttons) in the IDE's own theme, while a program uses the system's (macOS's and Windows' native looks), so they look different and can differ a little in size (a TabStrip's tabs, say); a preview in the system's look could close the gap. A form `font` that new controls start with (as VB's form Font was); colors for disabled controls (Tk grays them its own way); `selectcolor` for check box and option button indicators. Known limits: macOS buttons keep the system's colors, macOS ignores a flat button's backcolor, and Windows' native theme may ignore a ComboBox's field color (all Tk's).
- **TextBox follow-ups**: `readonly` on a multi-line box can't be copied from with the keyboard (it's a disabled Text underneath, which takes no focus from a click); `maxlength` doesn't stop a middle-click paste on Linux.
- **Keyboard follow-ups**: keydown and keyup on controls too (today on the form, which sees every key); which modifier keys are held, for mouse events (Shift+click).
- **Image follow-ups**: show an Image's outline in the designer when its picture is smaller than the control (sizing normal, center or zoom); offer to delete a copied picture from images/ when nothing uses it any more; animated GIFs.

## Biggest features
- **Grid follow-ups**: add and remove rows and columns from the designer (today: the Grid's `columns` and `rows` properties); show each track's size along the Grid's edges; a form that sizes itself to its contents; single-direction rows and columns (a `Stack`, like Qt's QHBoxLayout/QVBoxLayout), which would also cover Tk's pack.
- **Backend Swappable**:  Being able to design for a PyQt6 or some other GUI backend instead of Tkinter for a project.  There are two optional paths to this: One is keeping Tkinter for the IDE and designing a project with a different GUI backend, or having the IDE match the target project GUI.  Is a GUI target potentially a plugin?  Either way, this looks like a separation of concerns type of refactor.
  - Keep readymade's own API free of Tk: shapes are readymade objects, colors `#rrggbb`, angles in degrees, fonts `(family, size, style)`. Still Tk-specific: color names Canvas shapes accept beyond `#rrggbb`, and `.widget` / `form.root` (fine as documented escape hatches). If Qt: PySide6 (LGPL) rather than PyQt6 (GPL), for programs made with Make EXE.
- **Plugins**: A plugin architecture to extend features.  Allow other people to create plugins like VB or VS Code allows.
