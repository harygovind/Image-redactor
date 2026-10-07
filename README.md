# Redactor

A small desktop GUI tool for redacting sensitive parts of screenshots and images, built for **pentest, bug bounty and security-report PoCs** where you can't disclose everything in the evidence (credentials, tokens, session IDs, emails, IPs, user data, etc.).

Open an image, drag rectangles over the sensitive areas, choose how to obscure them, preview the result live, and save a clean copy. The original file is never modified.

---

## Features

- **Rectangle selection** directly on the image in a GUI window (no CLI prompts for settings)
- **Three redaction methods**, switchable from a dropdown:
  - Gaussian blur
  - Pixelate
  - Solid black box
- **Strength slider (1-100%)** inside the window, with **live preview**
- **Multiple regions** on one image
- **Edit individual regions**: click a region to select it, then move, resize or delete it
- **Multi-level undo and redo**
- **Zoom and scroll** for precise selection on large screenshots
- **Save As dialog** that opens in your current directory so you just type the filename
- **Metadata stripped on save**: the output is written as a fresh image, so EXIF/GPS/device info from the original is not carried over
- **HiDPI aware**: crisp UI on scaled displays (Windows 125%/150%+)
- Respects EXIF orientation of phone screenshots/photos

---

## Requirements

- Python 3.8+
- [Pillow](https://pypi.org/project/pillow/)
- Tkinter (bundled with Python on Windows and macOS)

### Installing dependencies

```bash
pip install pillow
```

On Debian / Ubuntu / Kali, Tkinter is a separate package:

```bash
sudo apt install python3-tk
```

---

## Usage

```bash
python3 redact_image.py
```

1. Choose the image in the file dialog (it opens in your current directory).
2. Drag on the image to draw a rectangle over each sensitive area.
3. Pick the **Method** and adjust **Strength**. The preview updates live.
4. Click **Save As...** (or press `Ctrl+S`), type a filename and save.

Supported input formats: PNG, JPG/JPEG, BMP, GIF, TIFF, WebP.
Output formats: PNG (default) or JPEG.

---

## Controls

| Action | How |
|---|---|
| Draw a new region | Drag on an empty area |
| Select a region | Click inside it |
| Move a region | Drag inside the selected region |
| Resize a region | Drag one of its 8 handles |
| Delete selected region | `Delete` / `Backspace` or the **Delete selected** button |
| Draw over an existing region | Hold `Shift` while dragging |
| Deselect | `Esc` or click an empty area |
| Undo | `Ctrl+Z` or the **Undo** button |
| Redo | `Ctrl+Y` / `Ctrl+Shift+Z` or the **Redo** button |
| Remove all regions | **Reset** button (can be undone) |
| Zoom | `Ctrl` + mouse wheel, the **+** / **-** buttons, or **Fit** |
| Scroll | Mouse wheel (vertical), `Shift` + wheel (horizontal) |
| Save | `Ctrl+S` or **Save As...** |

---

## Choosing a redaction method

| Method | Use it for | Notes |
|---|---|---|
| **Solid black box** | Passwords, API keys, tokens, session cookies, anything that must never be recoverable | Safest. Nothing of the original remains. |
| **Pixelate** | Names, emails, IDs, IPs where you still want the layout to look natural | Use a high strength so characters are not legible. |
| **Gaussian blur** | Faces, logos, non-critical visual content | Low strength on large text can be partly reversed or read. |

> **Tip:** For anything secret, use **Solid black box**, or blur/pixelate at a very high strength, and always zoom into the saved result to confirm the data is unreadable before adding it to a report.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'tkinter'`**
Install the Tk package for your OS (`sudo apt install python3-tk` on Debian/Ubuntu/Kali, or reinstall Python with the "tcl/tk" option on Windows).

**`Pillow is required`**
Run `pip install pillow`.

**The window looks blurry on a high-resolution display**
The script enables DPI awareness automatically on Windows. Make sure you are running the latest version of the script. If you still see blur, please open an issue with your OS and display scaling.

**No window appears over SSH / headless server**
This is a GUI tool. Run it on a machine with a display (or use X forwarding).

---

## Notes and limitations

- Regions are rectangles only.
- Edits happen on a copy in memory; the original image is never changed unless you explicitly choose the same filename in the Save dialog (you will be asked to confirm).
- The blur/pixelate preview refreshes when you release the mouse after moving or resizing a region.

---

## Disclaimer

This tool only helps obscure parts of images. You are responsible for verifying that no sensitive information remains visible in the saved output before sharing it, and for handling the original evidence in line with your engagement rules and applicable law.
