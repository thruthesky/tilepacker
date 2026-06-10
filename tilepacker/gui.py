"""tkinter-based graphical user interface (GUI) module.

This module provides a desktop GUI for picking individual tile images,
visually configuring :class:`~tilepacker.core.config.PackConfig` settings, and
exporting a uniform-grid tileset (PNG + ``.tsx``/``.tsj``) with a single button
click.

Design policy (very important)::

    * Never ``import tkinter`` at module top level. The runtime environment may
      not have tkinter (e.g. a headless server or a minimal Python build), so
      every tkinter import and class definition is performed lazily inside
      :func:`launch`. As a result, ``import tilepacker.gui`` itself always
      succeeds even without tkinter.
    * The core dependencies (:mod:`tilepacker.core.config`,
      :mod:`tilepacker.core.export`) are likewise imported inside the functions
      (for a lightweight import and consistent lazy loading).

Public symbols:
    * :func:`launch` -- the entry point that opens the GUI. Returns ``0`` on
      success, or ``1`` when it cannot run (e.g. tkinter is unavailable).
"""

from __future__ import annotations

__all__ = ["launch"]


def _make_app_class(tk, ttk, filedialog, messagebox):
    """Take the tkinter modules and dynamically define and return the ``App`` class.

    ``App`` subclasses ``tk.Frame``, so ``tk`` is required at class-definition
    time. To avoid importing tkinter at module load, the class definition is
    confined inside the body of this factory function. It is only called after
    :func:`launch` has successfully imported tkinter.

    Args:
        tk: the ``tkinter`` module.
        ttk: the ``tkinter.ttk`` module (themed widgets).
        filedialog: the ``tkinter.filedialog`` module.
        messagebox: the ``tkinter.messagebox`` module.

    Returns:
        The dynamically defined ``App`` class (a ``tk.Frame`` subclass).
    """

    class App(tk.Frame):
        """The main frame of the tileset packing GUI.

        The left side holds the tile-image file listbox and add/remove buttons;
        the right side holds the grid/cell/preprocessing setting widgets, the
        output path picker, the Export button, and the PNG preview area for the
        packing result.
        """

        def __init__(self, master):
            """Create and lay out the widgets.

            Args:
                master: the parent widget (usually the ``tk.Tk`` root window).
            """
            super().__init__(master)
            self.master = master
            self.pack(fill="both", expand=True)

            # Hold the preview PhotoImage of the packing result (a reference to
            # prevent garbage collection).
            self._preview_photo = None

            self._build_widgets()

        # -- Widget construction ---------------------------------------
        def _build_widgets(self):
            """Create the entire widget tree and lay it out with grid/pack."""
            self.master.title("tilepacker")

            # Two-column left/right layout.
            left = ttk.Frame(self, padding=8)
            left.pack(side="left", fill="y")
            right = ttk.Frame(self, padding=8)
            right.pack(side="left", fill="both", expand=True)

            # ----- Left: tile file list -----
            ttk.Label(left, text="Tile images").pack(anchor="w")

            list_frame = ttk.Frame(left)
            list_frame.pack(fill="both", expand=True)
            scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
            self.file_list = tk.Listbox(
                list_frame,
                selectmode="extended",
                width=40,
                height=16,
                yscrollcommand=scrollbar.set,
            )
            scrollbar.config(command=self.file_list.yview)
            scrollbar.pack(side="right", fill="y")
            self.file_list.pack(side="left", fill="both", expand=True)

            btn_row = ttk.Frame(left)
            btn_row.pack(fill="x", pady=(4, 0))
            ttk.Button(btn_row, text="Add...", command=self._on_add_files).pack(
                side="left"
            )
            ttk.Button(
                btn_row, text="Remove", command=self._on_remove_selected
            ).pack(side="left", padx=4)
            ttk.Button(btn_row, text="Clear", command=self._on_clear_files).pack(
                side="left"
            )

            # ----- Right: settings -----
            self._build_settings(right)

        def _build_settings(self, parent):
            """Build the right-side settings panel (inputs/combobox/checkbox/output/button/preview).

            Args:
                parent: the parent frame that holds the setting widgets.
            """
            # Integer input fields. Order: (label text, attribute name, default).
            self._int_vars = {}
            grid = ttk.Frame(parent)
            grid.pack(anchor="w", fill="x")

            int_specs = [
                ("Tile width", "tile_width", 32),
                ("Tile height", "tile_height", 32),
                ("Columns (0=auto)", "columns", 0),
                ("Margin", "margin", 0),
                ("Spacing", "spacing", 0),
                ("Extrude", "extrude", 0),
            ]
            for row, (label, attr, default) in enumerate(int_specs):
                ttk.Label(grid, text=label).grid(
                    row=row, column=0, sticky="w", padx=(0, 6), pady=2
                )
                var = tk.StringVar(value=str(default))
                self._int_vars[attr] = var
                ttk.Entry(grid, textvariable=var, width=10).grid(
                    row=row, column=1, sticky="w", pady=2
                )

            # Tileset name.
            name_row = len(int_specs)
            ttk.Label(grid, text="Name").grid(
                row=name_row, column=0, sticky="w", padx=(0, 6), pady=2
            )
            self._name_var = tk.StringVar(value="tileset")
            ttk.Entry(grid, textvariable=self._name_var, width=18).grid(
                row=name_row, column=1, sticky="w", pady=2
            )

            # ----- Comboboxes: resize_mode / resample -----
            combo_frame = ttk.Frame(parent)
            combo_frame.pack(anchor="w", fill="x", pady=(8, 0))

            ttk.Label(combo_frame, text="Resize mode").grid(
                row=0, column=0, sticky="w", padx=(0, 6), pady=2
            )
            self._resize_var = tk.StringVar(value="fit")
            ttk.Combobox(
                combo_frame,
                textvariable=self._resize_var,
                values=sorted(self._resize_modes),
                state="readonly",
                width=12,
            ).grid(row=0, column=1, sticky="w", pady=2)

            ttk.Label(combo_frame, text="Resample").grid(
                row=1, column=0, sticky="w", padx=(0, 6), pady=2
            )
            self._resample_var = tk.StringVar(value="nearest")
            ttk.Combobox(
                combo_frame,
                textvariable=self._resample_var,
                values=sorted(self._resample_filters),
                state="readonly",
                width=12,
            ).grid(row=1, column=1, sticky="w", pady=2)

            # ----- Checkboxes: pre/post-processing options -----
            check_frame = ttk.Frame(parent)
            check_frame.pack(anchor="w", fill="x", pady=(8, 0))

            self._bool_vars = {}
            bool_specs = [
                ("Remove background", "bg_remove"),
                ("Trim transparent border", "trim"),
                ("Deduplicate tiles", "deduplicate"),
                ("Drop empty tiles", "drop_empty"),
            ]
            for label, attr in bool_specs:
                var = tk.BooleanVar(value=False)
                self._bool_vars[attr] = var
                ttk.Checkbutton(check_frame, text=label, variable=var).pack(
                    anchor="w"
                )

            # Whether to write the definition files (.tsx/.tsj).
            self._write_tsx_var = tk.BooleanVar(value=True)
            self._write_tsj_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                check_frame, text="Write .tsx", variable=self._write_tsx_var
            ).pack(anchor="w")
            ttk.Checkbutton(
                check_frame, text="Write .tsj", variable=self._write_tsj_var
            ).pack(anchor="w")

            # ----- Output path -----
            out_frame = ttk.Frame(parent)
            out_frame.pack(anchor="w", fill="x", pady=(8, 0))
            ttk.Label(out_frame, text="Output PNG").pack(anchor="w")
            out_row = ttk.Frame(out_frame)
            out_row.pack(fill="x")
            self._out_var = tk.StringVar(value="")
            ttk.Entry(out_row, textvariable=self._out_var, width=32).pack(
                side="left", fill="x", expand=True
            )
            ttk.Button(out_row, text="Browse...", command=self._on_pick_output).pack(
                side="left", padx=(4, 0)
            )

            # ----- Export button -----
            ttk.Button(parent, text="Export", command=self._on_export).pack(
                anchor="w", pady=(10, 0)
            )

            # ----- Preview area -----
            ttk.Label(parent, text="Preview").pack(anchor="w", pady=(10, 0))
            self._preview_label = ttk.Label(
                parent, text="(no preview)", anchor="center"
            )
            self._preview_label.pack(anchor="w", fill="both", expand=True)

            # ----- Status bar -----
            self._status_var = tk.StringVar(value="Ready.")
            ttk.Label(
                parent, textvariable=self._status_var, relief="sunken", anchor="w"
            ).pack(fill="x", pady=(8, 0))

        # -- File list callbacks ---------------------------------------
        def _on_add_files(self):
            """Open a file picker dialog and add the chosen tile images to the list."""
            paths = filedialog.askopenfilenames(
                title="Select tile images",
                filetypes=[
                    ("Image files", "*.png *.gif *.bmp *.jpg *.jpeg *.webp"),
                    ("All files", "*.*"),
                ],
            )
            for p in paths:
                self.file_list.insert("end", p)
            if paths:
                self._status_var.set(f"{len(paths)} file(s) added.")

        def _on_remove_selected(self):
            """Remove the selected items from the listbox."""
            # Delete in reverse order so the indices don't shift.
            for index in reversed(self.file_list.curselection()):
                self.file_list.delete(index)

        def _on_clear_files(self):
            """Clear all items from the listbox."""
            self.file_list.delete(0, "end")

        def _on_pick_output(self):
            """Open a save-path dialog to choose the output PNG path."""
            path = filedialog.asksaveasfilename(
                title="Save tileset PNG as",
                defaultextension=".png",
                filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
            )
            if path:
                self._out_var.set(path)

        # -- Settings collection ---------------------------------------
        def _collect_config(self):
            """Read the current widget values and build and return a validated :class:`PackConfig`.

            Returns:
                A ``PackConfig`` instance that passed consistency validation.

            Raises:
                ValueError: when an integer input is not a number or a setting
                    value is invalid.
            """
            from tilepacker.core.config import PackConfig

            kwargs = {}
            for attr, var in self._int_vars.items():
                raw = var.get().strip()
                try:
                    kwargs[attr] = int(raw)
                except (TypeError, ValueError):
                    raise ValueError(f"'{attr}' value is not an integer: {raw!r}")

            kwargs["name"] = self._name_var.get().strip() or "tileset"
            kwargs["resize_mode"] = self._resize_var.get()
            kwargs["resample"] = self._resample_var.get()
            for attr, var in self._bool_vars.items():
                kwargs[attr] = bool(var.get())

            config = PackConfig(**kwargs)
            config.validate()
            return config

        # -- Export ----------------------------------------------------
        def _on_export(self):
            """Run packing with the current settings and report the result/errors."""
            from tilepacker.core.export import pack_from_files

            paths = list(self.file_list.get(0, "end"))
            if not paths:
                messagebox.showwarning(
                    "tilepacker", "Please add tile images first."
                )
                return

            out_path = self._out_var.get().strip()
            if not out_path:
                messagebox.showwarning(
                    "tilepacker", "Please specify the output PNG path first."
                )
                return

            try:
                config = self._collect_config()
            except ValueError as exc:
                messagebox.showerror("tilepacker", f"Setting error:\n{exc}")
                return

            try:
                result = pack_from_files(
                    paths,
                    config,
                    out_path,
                    write_tsx=bool(self._write_tsx_var.get()),
                    write_tsj=bool(self._write_tsj_var.get()),
                )
            except Exception as exc:  # noqa: BLE001 - report every exception to the user.
                messagebox.showerror(
                    "tilepacker", f"Export failed:\n{exc}"
                )
                self._status_var.set("Export failed.")
                return

            summary = (
                f"{result.tile_count} tiles, "
                f"{result.columns}x{result.rows} grid, "
                f"{result.width}x{result.height}px"
            )
            self._status_var.set(f"Exported: {summary}")
            self._show_preview(result.image_path)
            messagebox.showinfo(
                "tilepacker",
                "Export succeeded.\n"
                f"PNG: {result.image_path}\n"
                f"{summary}",
            )

        # -- Preview ---------------------------------------------------
        def _show_preview(self, png_path):
            """Display the saved PNG in the preview label.

            First, load the PNG directly with the built-in
            :class:`tkinter.PhotoImage`, shrinking it with ``subsample`` if it
            is too large. On failure, fall back to Pillow + ImageTk, and if even
            that is unavailable, just update the text hint (without raising an
            exception).

            Args:
                png_path: path to the PNG file to display.
            """
            max_side = 256
            try:
                photo = tk.PhotoImage(file=png_path)
                w, h = photo.width(), photo.height()
                factor = max(1, (max(w, h) + max_side - 1) // max_side)
                if factor > 1:
                    photo = photo.subsample(factor, factor)
                self._preview_photo = photo
                self._preview_label.configure(image=photo, text="")
                return
            except Exception:
                pass

            # Pillow + ImageTk fallback.
            try:
                from PIL import Image, ImageTk

                with Image.open(png_path) as opened:
                    img = opened.copy()
                img.thumbnail((max_side, max_side))
                photo = ImageTk.PhotoImage(img)
                self._preview_photo = photo
                self._preview_label.configure(image=photo, text="")
            except Exception:
                self._preview_label.configure(
                    image="", text="(preview unavailable)"
                )

    return App


def launch() -> int:
    """Open the tileset packing GUI.

    tkinter is imported lazily inside this function. If tkinter is not
    installed, print the platform-specific installation instructions and return
    ``1``. When the main loop ends normally, return ``0``.

    Returns:
        int: ``0`` on success, or ``1`` when it cannot run (e.g. tkinter is
        unavailable).
    """
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print(
            "tkinter is not installed, so the GUI cannot run.\n"
            "Installation:\n"
            "  * macOS (Homebrew): brew install python-tk\n"
            "  * Debian/Ubuntu:    sudo apt install python3-tk\n"
            "  * Fedora:           sudo dnf install python3-tkinter\n"
            "Try again after installing."
        )
        return 1

    # Fetch the mode sets used as combobox choices from the core config.
    try:
        from tilepacker.core.config import RESIZE_MODES, RESAMPLE_FILTERS
    except Exception:  # pragma: no cover - safe defaults when the core is absent.
        RESIZE_MODES = frozenset({"none", "stretch", "fit", "cover", "crop"})
        RESAMPLE_FILTERS = frozenset(
            {"nearest", "box", "bilinear", "hamming", "bicubic", "lanczos"}
        )

    root = tk.Tk()
    App = _make_app_class(tk, ttk, filedialog, messagebox)
    # Inject the combobox choices as class attributes so App instances can reference them.
    App._resize_modes = RESIZE_MODES
    App._resample_filters = RESAMPLE_FILTERS

    try:
        App(root)
        root.mainloop()
    except Exception as exc:  # noqa: BLE001 - report the exception at the top level and exit.
        try:
            messagebox.showerror("tilepacker", f"GUI error:\n{exc}")
        except Exception:
            print(f"GUI error: {exc}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - direct-run entry point.
    import sys

    sys.exit(launch())
