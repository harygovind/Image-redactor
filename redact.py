#!/usr/bin/env python3
"""
redact_image.py - GUI tool to blur / pixelate / black-out parts of a screenshot
before putting it in a pentest report.

Requirements:  pip install pillow      (Tkinter ships with Python;
                                        on Debian/Kali: sudo apt install python3-tk)

Usage:  python3 redact_image.py
        1. Pick the image in the file dialog (opens in the current directory).
        2. Drag with the mouse to draw rectangles over sensitive data.
        3. Choose the method + strength in the toolbar (live preview).
        4. Click "Save As..." (dialog opens in the current directory, you type the filename).

Controls:
  Drag on empty area         draw a new region
  Click inside a region      select it (handles appear)
  Drag inside selected       move it
  Drag a handle              resize it
  Delete / Backspace         delete the selected region (or "Delete selected" button)
  Shift + drag               force drawing a new region even over an existing one
  Esc                        deselect
  Ctrl+Z / Undo              undo
  Ctrl+Y or Ctrl+Shift+Z     redo
  Ctrl + mouse wheel         zoom in/out (also + / - buttons)
  Mouse wheel                scroll vertically, Shift+wheel scrolls horizontally
  Ctrl+S                     save
"""
import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageFilter, ImageOps, ImageDraw, ImageTk
except ImportError:
    sys.exit("Pillow is required:  pip install pillow")

METHODS = ["Gaussian blur", "Pixelate", "Solid black box"]
MIN_REGION = 3       # px (image coordinates); smaller regions are ignored / not allowed
HANDLE_SIZE = 5      # half-size of a resize handle square, in canvas px
HANDLE_TOL = 8       # hit tolerance around a handle, in canvas px
HISTORY_DEPTH = 10
UI_SCALE = 1.0       # set at startup from the screen DPI (HiDPI displays)


def enable_hidpi():
    """Must run BEFORE tk.Tk(). Without it Windows bitmap-stretches the whole
    window on scaled displays (125%/150%...), which is what makes the UI look blurry."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def setup_look(root):
    """Pick up the real screen DPI, use a native-looking theme and a crisp default font."""
    global UI_SCALE
    try:
        UI_SCALE = min(3.0, max(1.0, root.winfo_fpixels("1i") / 96.0))
    except Exception:
        UI_SCALE = 1.0
    style = ttk.Style(root)
    wanted = "vista" if sys.platform.startswith("win") else \
             "aqua" if sys.platform == "darwin" else "clam"
    if wanted in style.theme_names():
        style.theme_use(wanted)
    if sys.platform.startswith("win"):
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family="Segoe UI", size=10)
            except Exception:
                pass
    style.configure("TButton", padding=(8, 3))


def line_width():
    return max(2, int(round(2 * UI_SCALE)))


HANDLE_CURSORS = {
    "nw": "top_left_corner", "se": "bottom_right_corner",
    "ne": "top_right_corner", "sw": "bottom_left_corner",
    "n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
    "e": "sb_h_double_arrow", "w": "sb_h_double_arrow",
}


# ---------------------------------------------------------------- pure logic
class History:
    """Snapshot-based undo/redo of the region list."""

    def __init__(self, depth=HISTORY_DEPTH):
        self.depth = depth
        self.undo_stack = []
        self.redo_stack = []

    def record(self, regions):
        """Call with the regions as they were BEFORE a change is applied."""
        self.undo_stack.append(list(regions))
        del self.undo_stack[:-self.depth]
        self.redo_stack.clear()

    def undo(self, current):
        if not self.undo_stack:
            return None
        self.redo_stack.append(list(current))
        del self.redo_stack[:-self.depth]
        return self.undo_stack.pop()

    def redo(self, current):
        if not self.redo_stack:
            return None
        self.undo_stack.append(list(current))
        del self.undo_stack[:-self.depth]
        return self.redo_stack.pop()


def handle_points(region, scale):
    """Canvas-space centres of the 8 resize handles for a region (image coords)."""
    x0, y0, x1, y1 = [v * scale for v in region]
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    return {"nw": (x0, y0), "n": (xm, y0), "ne": (x1, y0),
            "e": (x1, ym), "se": (x1, y1), "s": (xm, y1),
            "sw": (x0, y1), "w": (x0, ym)}


def hit_test(regions, selected, cx, cy, scale):
    """Return (kind, index, handle). kind is 'handle', 'inside' or None. cx,cy in canvas px."""
    if selected is not None and 0 <= selected < len(regions):
        for name, (hx, hy) in handle_points(regions[selected], scale).items():
            tol = HANDLE_TOL * UI_SCALE
            if abs(cx - hx) <= tol and abs(cy - hy) <= tol:
                return "handle", selected, name
    for i in range(len(regions) - 1, -1, -1):   # topmost (latest) first
        x0, y0, x1, y1 = regions[i]
        if x0 * scale <= cx <= x1 * scale and y0 * scale <= cy <= y1 * scale:
            return "inside", i, None
    return None, None, None


def move_region(orig, dx, dy, W, H):
    x0, y0, x1, y1 = orig
    w, h = x1 - x0, y1 - y0
    nx0 = int(round(max(0, min(W - w, x0 + dx))))
    ny0 = int(round(max(0, min(H - h, y0 + dy))))
    return (nx0, ny0, nx0 + w, ny0 + h)


def resize_region(orig, handle, ix, iy, W, H):
    x0, y0, x1, y1 = orig
    ix = int(round(max(0, min(W, ix))))
    iy = int(round(max(0, min(H, iy))))
    if "w" in handle:
        x0 = min(ix, x1 - MIN_REGION)
    if "e" in handle:
        x1 = max(ix, x0 + MIN_REGION)
    if "n" in handle:
        y0 = min(iy, y1 - MIN_REGION)
    if "s" in handle:
        y1 = max(iy, y0 + MIN_REGION)
    return (x0, y0, x1, y1)


def apply_redactions(base, regions, method, strength):
    """Return a copy of `base` with every region obscured. Regions are (x0,y0,x1,y1) in image px."""
    out = base.copy()
    for x0, y0, x1, y1 in regions:
        box = (x0, y0, x1, y1)
        w, h = x1 - x0, y1 - y0
        if method == "Solid black box":
            ImageDraw.Draw(out).rectangle([x0, y0, x1 - 1, y1 - 1], fill=(0, 0, 0))
            continue
        crop = out.crop(box)
        if method == "Gaussian blur":
            # strength 0-100 -> radius relative to region size so it stays effective
            radius = max(1.0, (strength / 100.0) * max(w, h) * 0.15)
            crop = crop.filter(ImageFilter.GaussianBlur(radius))
        else:  # Pixelate
            block = max(2, int((strength / 100.0) * max(w, h) / 3))
            small = crop.resize((max(1, w // block), max(1, h // block)), Image.BILINEAR)
            crop = small.resize((w, h), Image.NEAREST)
        out.paste(crop, box)
    return out


# ----------------------------------------------------------------------- GUI
class RedactorApp:
    def __init__(self, root, path):
        self.root = root
        self.path = path
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)  # respect camera/phone orientation
        self.orig = img.convert("RGB")
        self.W, self.H = self.orig.size

        self.regions = []        # list of (x0,y0,x1,y1) in image coordinates
        self.history = History()
        self.selected = None     # index into self.regions
        self.scale = 1.0
        self.processed = self.orig
        self.tk_img = None
        self._after_id = None

        # interaction state
        self.mode = None         # 'draw' | 'move' | 'resize'
        self.press_canvas = None
        self.press_snapshot = None   # regions before the current gesture
        self.press_region = None
        self.press_handle = None
        self.drag_item = None

        root.title(f"Redactor - {os.path.basename(path)}")
        self._build_ui()
        self._fit_to_window()
        self._bind_events()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(6, 6, 6, 0))
        top.pack(side=tk.TOP, fill=tk.X)
        bar = ttk.Frame(self.root, padding=6)
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Method:").pack(side=tk.LEFT)
        self.method_var = tk.StringVar(value=METHODS[0])
        cb = ttk.Combobox(top, textvariable=self.method_var, values=METHODS,
                          state="readonly", width=16)
        cb.pack(side=tk.LEFT, padx=(4, 12))
        cb.bind("<<ComboboxSelected>>", lambda e: self._schedule_refresh())

        ttk.Label(top, text="Strength:").pack(side=tk.LEFT)
        self.strength_var = tk.IntVar(value=80)
        self.strength_lbl = ttk.Label(top, text="80%", width=5)
        scale = ttk.Scale(top, from_=1, to=100, orient=tk.HORIZONTAL, length=int(220 * UI_SCALE),
                          command=self._on_strength)
        scale.set(80)
        scale.pack(side=tk.LEFT, padx=4)
        self.strength_lbl.pack(side=tk.LEFT, padx=(0, 12))
        ttk.Button(top, text="Save As...", command=self.save).pack(side=tk.RIGHT, padx=2)

        ttk.Button(bar, text="Undo", command=self.undo).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Redo", command=self.redo).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Delete selected", command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Reset", command=self.reset).pack(side=tk.LEFT, padx=2)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(bar, text="−", width=3, command=lambda: self.zoom(1 / 1.25)).pack(side=tk.LEFT)
        self.zoom_lbl = ttk.Label(bar, text="100%", width=6, anchor="center")
        self.zoom_lbl.pack(side=tk.LEFT)
        ttk.Button(bar, text="+", width=3, command=lambda: self.zoom(1.25)).pack(side=tk.LEFT)
        ttk.Button(bar, text="Fit", command=self._fit_to_window).pack(side=tk.LEFT, padx=2)

        self.status = ttk.Label(self.root, anchor="w", relief=tk.SUNKEN, padding=(6, 2))
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        frame = ttk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(frame, bg="#2b2b2b", highlightthickness=0, cursor="crosshair")
        vs = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.canvas.yview)
        hs = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=hs.set, yscrollcommand=vs.set)
        vs.pack(side=tk.RIGHT, fill=tk.Y)
        hs.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(fill=tk.BOTH, expand=True)

    def _bind_events(self):
        c = self.canvas
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._drag)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Motion>", self._hover)
        # wheel: Windows/macOS use <MouseWheel>; Linux uses Button-4/5
        c.bind("<MouseWheel>", self._wheel)
        c.bind("<Button-4>", lambda e: self._wheel(e, 1))
        c.bind("<Button-5>", lambda e: self._wheel(e, -1))
        r = self.root
        r.bind("<Control-z>", lambda e: self.undo())
        r.bind("<Control-y>", lambda e: self.redo())
        r.bind("<Control-Z>", lambda e: self.redo())
        r.bind("<Control-Y>", lambda e: self.redo())
        r.bind("<Control-s>", lambda e: self.save())
        r.bind("<Delete>", lambda e: self.delete_selected())
        r.bind("<BackSpace>", lambda e: self.delete_selected())
        r.bind("<Escape>", lambda e: self.deselect())
        r.bind("<Control-plus>", lambda e: self.zoom(1.25))
        r.bind("<Control-equal>", lambda e: self.zoom(1.25))
        r.bind("<Control-minus>", lambda e: self.zoom(1 / 1.25))

    # ------------------------------------------------------------ rendering
    def _on_strength(self, val):
        v = int(float(val))
        self.strength_var.set(v)
        self.strength_lbl.config(text=f"{v}%")
        self._schedule_refresh()

    def _schedule_refresh(self):
        # debounce so dragging the slider stays responsive on big images
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(60, self._refresh)

    def _refresh(self):
        self._after_id = None
        self.processed = apply_redactions(
            self.orig, self.regions, self.method_var.get(), self.strength_var.get())
        self._draw()

    def _draw(self):
        dw, dh = max(1, int(self.W * self.scale)), max(1, int(self.H * self.scale))
        resample = Image.NEAREST if self.scale >= 2 else Image.LANCZOS
        shown = self.processed.resize((dw, dh), resample) if (dw, dh) != (self.W, self.H) else self.processed
        self.tk_img = ImageTk.PhotoImage(shown)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img, tags="img")
        self.canvas.configure(scrollregion=(0, 0, dw, dh))
        self._draw_overlay()
        self.zoom_lbl.config(text=f"{int(self.scale * 100)}%")

    def _draw_overlay(self):
        c = self.canvas
        c.delete("ov")
        lw = line_width()
        hs = HANDLE_SIZE * UI_SCALE
        for i, reg in enumerate(self.regions):
            x0, y0, x1, y1 = [v * self.scale for v in reg]
            if i == self.selected:
                c.create_rectangle(x0, y0, x1, y1, outline="#00d1ff", width=lw, tags="ov")
            else:
                c.create_rectangle(x0, y0, x1, y1, outline="#ff3b30", width=lw,
                                   dash=(4, 3), tags="ov")
        if self.selected is not None and 0 <= self.selected < len(self.regions):
            for hx, hy in handle_points(self.regions[self.selected], self.scale).values():
                c.create_rectangle(hx - hs, hy - hs, hx + hs, hy + hs,
                                   fill="#ffffff", outline="#00d1ff", width=1, tags="ov")
        self._update_status()

    def _update_status(self):
        sel = ""
        if self.selected is not None and 0 <= self.selected < len(self.regions):
            x0, y0, x1, y1 = self.regions[self.selected]
            sel = f"  |  selected: {x1 - x0}x{y1 - y0} at ({x0},{y0})  -  drag to move, handles to resize, Del to remove"
        self.status.config(
            text=f"{self.W}x{self.H}px  |  {len(self.regions)} region(s){sel}  |  "
                 f"drag = new region, click region = select, Ctrl+Z / Ctrl+Y undo/redo")

    # ----------------------------------------------------------------- zoom
    def _fit_to_window(self):
        self.root.update_idletasks()
        cw = max(self.canvas.winfo_width(), 200)
        ch = max(self.canvas.winfo_height(), 200)
        self.scale = min(1.0, cw / self.W, ch / self.H)
        self._refresh()

    def zoom(self, factor, anchor=None):
        new = min(8.0, max(0.05, self.scale * factor))
        if new == self.scale:
            return
        # keep the point under the cursor (or view center) stable
        if anchor is None:
            anchor = (self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)
        ix = self.canvas.canvasx(anchor[0]) / self.scale
        iy = self.canvas.canvasy(anchor[1]) / self.scale
        self.scale = new
        self._draw()
        dw, dh = self.W * self.scale, self.H * self.scale
        self.canvas.xview_moveto(max(0, (ix * self.scale - anchor[0]) / dw))
        self.canvas.yview_moveto(max(0, (iy * self.scale - anchor[1]) / dh))

    def _wheel(self, event, direction=None):
        if direction is None:
            direction = 1 if event.delta > 0 else -1
        ctrl = event.state & 0x4
        shift = event.state & 0x1
        if ctrl:
            self.zoom(1.15 if direction > 0 else 1 / 1.15, anchor=(event.x, event.y))
        elif shift:
            self.canvas.xview_scroll(-direction * 3, "units")
        else:
            self.canvas.yview_scroll(-direction * 3, "units")

    # ------------------------------------------------------------ selection
    def _canvas_xy(self, e):
        return self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)

    def _hover(self, e):
        if self.mode:
            return
        cx, cy = self._canvas_xy(e)
        if e.state & 0x1:  # Shift held -> will draw
            self.canvas.config(cursor="crosshair")
            return
        kind, _, handle = hit_test(self.regions, self.selected, cx, cy, self.scale)
        if kind == "handle":
            self.canvas.config(cursor=HANDLE_CURSORS[handle])
        elif kind == "inside":
            self.canvas.config(cursor="fleur")
        else:
            self.canvas.config(cursor="crosshair")

    def _press(self, e):
        cx, cy = self._canvas_xy(e)
        self.press_canvas = (cx, cy)
        self.press_snapshot = list(self.regions)
        force_draw = bool(e.state & 0x1)
        kind, idx, handle = (None, None, None) if force_draw else \
            hit_test(self.regions, self.selected, cx, cy, self.scale)

        if kind == "handle":
            self.mode = "resize"
            self.press_handle = handle
            self.press_region = self.regions[idx]
        elif kind == "inside":
            self.selected = idx
            self.mode = "move"
            self.press_region = self.regions[idx]
            self._draw_overlay()
        else:
            self.selected = None
            self.mode = "draw"
            self.drag_item = self.canvas.create_rectangle(
                cx, cy, cx, cy, outline="#ffcc00", width=line_width(), tags="tmp")
            self._draw_overlay()

    def _drag(self, e):
        if not self.mode:
            return
        cx, cy = self._canvas_xy(e)
        sx, sy = self.press_canvas
        if self.mode == "draw":
            self.canvas.coords(self.drag_item, sx, sy, cx, cy)
        elif self.mode == "move":
            dx, dy = (cx - sx) / self.scale, (cy - sy) / self.scale
            self.regions[self.selected] = move_region(self.press_region, dx, dy, self.W, self.H)
            self._draw_overlay()
        elif self.mode == "resize":
            self.regions[self.selected] = resize_region(
                self.press_region, self.press_handle,
                cx / self.scale, cy / self.scale, self.W, self.H)
            self._draw_overlay()

    def _release(self, e):
        if not self.mode:
            return
        mode, self.mode = self.mode, None
        cx, cy = self._canvas_xy(e)
        sx, sy = self.press_canvas

        if mode == "draw":
            self.canvas.delete("tmp")
            x0, x1 = sorted((sx, cx))
            y0, y1 = sorted((sy, cy))
            ix0 = max(0, min(self.W, int(round(x0 / self.scale))))
            ix1 = max(0, min(self.W, int(round(x1 / self.scale))))
            iy0 = max(0, min(self.H, int(round(y0 / self.scale))))
            iy1 = max(0, min(self.H, int(round(y1 / self.scale))))
            if ix1 - ix0 < MIN_REGION or iy1 - iy0 < MIN_REGION:
                self._draw_overlay()
                return
            self.history.record(self.press_snapshot)
            self.regions.append((ix0, iy0, ix1, iy1))
            self.selected = len(self.regions) - 1
        else:
            # move / resize: record only if something actually changed
            if self.regions != self.press_snapshot:
                self.history.record(self.press_snapshot)
        self._refresh()

    # ------------------------------------------------------- edit operations
    def _apply_snapshot(self, snap):
        self.regions = list(snap)
        self.selected = None
        self._refresh()

    def undo(self):
        snap = self.history.undo(self.regions)
        if snap is not None:
            self._apply_snapshot(snap)

    def redo(self):
        snap = self.history.redo(self.regions)
        if snap is not None:
            self._apply_snapshot(snap)

    def deselect(self):
        if self.selected is not None:
            self.selected = None
            self._draw_overlay()

    def delete_selected(self):
        if self.selected is None or not (0 <= self.selected < len(self.regions)):
            return
        self.history.record(self.regions)
        del self.regions[self.selected]
        self.selected = None
        self._refresh()

    def reset(self):
        if self.regions and messagebox.askyesno("Reset", "Remove all selected regions?"):
            self.history.record(self.regions)
            self.regions = []
            self.selected = None
            self._refresh()

    # ----------------------------------------------------------------- save
    def save(self):
        if not self.regions:
            if not messagebox.askyesno("No regions", "No regions selected. Save unmodified image anyway?"):
                return
        stem, ext = os.path.splitext(os.path.basename(self.path))
        out_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save redacted image",
            initialdir=os.getcwd(),
            initialfile=f"{stem}_redacted.png",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg"), ("All files", "*.*")])
        if not out_path:
            return
        if os.path.abspath(out_path) == os.path.abspath(self.path):
            if not messagebox.askyesno("Overwrite original?",
                                       "This will overwrite the ORIGINAL image. Continue?"):
                return
        final = apply_redactions(self.orig, self.regions,
                                 self.method_var.get(), self.strength_var.get())
        try:
            # Saving from a fresh RGB image drops EXIF/metadata from the original.
            if out_path.lower().endswith((".jpg", ".jpeg")):
                final.save(out_path, quality=95)
            else:
                final.save(out_path)
        except Exception as ex:
            messagebox.showerror("Save failed", str(ex))
            return
        messagebox.showinfo("Saved", f"Saved to:\n{out_path}")


def main():
    enable_hidpi()          # before the Tk root exists, otherwise the UI is blurry
    root = tk.Tk()
    root.withdraw()
    setup_look(root)
    path = filedialog.askopenfilename(
        title="Select the image to redact",
        initialdir=os.getcwd(),
        filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"),
                   ("All files", "*.*")])
    if not path:
        return
    try:
        root.deiconify()
        w = min(int(1200 * UI_SCALE), int(root.winfo_screenwidth() * 0.92))
        h = min(int(850 * UI_SCALE), int(root.winfo_screenheight() * 0.88))
        root.geometry(f"{w}x{h}")
        RedactorApp(root, path)
    except Exception as ex:
        messagebox.showerror("Cannot open image", str(ex))
        return
    root.mainloop()


if __name__ == "__main__":
    main()
