"""
Noten-Streifen-Extraktor
Bedienung:
  - PDF öffnen via "Datei öffnen"
  - Klicken setzt abwechselnd Ober- und Untergrenze eines Streifens
  - Erster Klick = obere Abschneidemarke (was darüber ist, wird verworfen)
  - Zweiter Klick = unteres Ende des ersten Streifens
  - Dritter Klick = oberes Ende des zweiten Streifens
  - Vierter Klick = unteres Ende des zweiten Streifens
  - usw.
  - Linien sind per Drag & Drop verschiebbar
  - "Weiter" geht zur nächsten Seite (Schnitte werden übertragen)
  - "PDF exportieren" erzeugt das Ausgabe-PDF
"""

import io
import os
import tkinter as tk
from tkinter import filedialog, messagebox
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageTk

SCALE_DEFAULT = 1.5  # Standard-Zoom
SCALE_MIN = 0.5
SCALE_MAX = 4.0
SCALE_STEP = 0.2
DRAG_TOLERANCE = 6   # Pixel-Toleranz für Drag auf Linie
LEFT_ZONE_PX   = 50  # Pixel-Breite der linken Schnitt-Zone innerhalb eines Streifens

# A4-Ausgabe
MM = 72 / 25.4          # Punkte pro Millimeter
A4_W = 595.276          # A4 Breite in Punkten
A4_H = 841.890          # A4 Höhe in Punkten
EXPORT_DPI        = 300       # Auflösung für rotierte Streifen
EXPORT_SCALE      = EXPORT_DPI / 72

NP_ZONE_FRAC  = 0.40          # linke 40 % der Seitenbreite = Nullpunkt-Zone
NP_MARGIN_TOP = 8 * MM        # Abstand oberhalb Nullpunkt (Punkte)
NP_MARGIN_BOT = 30 * MM       # Abstand unterhalb Nullpunkt (Punkte)
NP_BOTTOM_GAP = 4 * MM        # Zusätzliche Lücke zwischen Streifen (Untergrenze = nächster NP − 12 mm)

# Export-Presets (page_w, page_h, margin_top, margin_bottom, margin_left, gap)
EXPORT_PRESETS = {
    "komprimiert": (A4_W, A4_H,  8*MM, 18*MM,  5*MM,  3*MM),
    "tablet":      (A4_H, A4_W, 10*MM, 20*MM,  8*MM,  5*MM),  # A4 quer
    "print":       (A4_W, A4_H, 15*MM, 22*MM, 10*MM,  8*MM),
}
# Fallback-Konstanten (werden zur Laufzeit aus Preset überschrieben)
OUT_MARGIN_TOP    = 15 * MM
OUT_MARGIN_BOTTOM = 22 * MM
OUT_MARGIN_LEFT   = 10 * MM
OUT_GAP           =  8 * MM


class StripApp:
    def __init__(self, root):
        self.root = root
        self.root.title("zebrastreifen")

        self.doc = None
        self.doc_path = ""
        self.page_index = 0
        self.page_count = 0
        self.scale = SCALE_DEFAULT

        # Pro Seite: Liste von y-Positionen in PDF-Punkten (abwechselnd oben/unten)
        self.cuts_per_page: dict[int, list] = {}

        # Pro Seite: Rotation in Grad (wird von übernächster Seite geerbt)
        self.rotation_per_page: dict[int, float] = {}

        # Pro Seite: linker Rand in PDF-Punkten (None = kein benutzerdefinierter Rand)
        self.left_margin_per_page: dict[int, float] = {}

        # Aktuell angezeigte Seite als PhotoImage (muss als Referenz gehalten werden)
        self._photo = None
        self._page_img = None         # PIL-Kopie für Staff-Snap
        self._snap_y: float | None = None   # aktueller Y-Snap (canvas-Koordinaten)
        self._snap_x: float | None = None   # aktueller X-Snap (canvas-Koordinaten)

        # Pro Seite: Taktzahlen je Streifen (Index = sortierte Streifen-Position)
        self.takt_per_page: dict[int, list[int]] = {}
        # Manuell gesetzte Taktzahlen: (page_idx, local_idx) → nicht überschreiben
        self.takt_manual: set[tuple[int, int]] = set()

        # Drag-State
        self._drag_line_index = None
        self._drag_start_y = None

        # Taktzahl-Klick-Flag (verhindert Doppel-Event canvas + tag)
        self._takt_click_handled = False

        # Taktzahlen anzeigen?
        self._show_takt = tk.BooleanVar(value=True)

        # Export-Preset
        self._export_preset = tk.StringVar(value="print")

        # Seitenwechsel-Marker: (page_idx, local_idx) → neue Seite erzwingen
        self.pagebreak_set: set[tuple[int, int]] = set()

        # Nullpunkte (Anfang Notensystem): pro Seite Liste von (x_pdf, y_pdf, orig_top)
        # orig_top = erzeugter top-Schnitt-Wert (dient als Anker beim Drag)
        self._np_points: dict[int, list[tuple[float, float, float]]] = {}
        self._drag_np_index: int | None = None      # NP-Raute wird gezogen
        self._drag_np_top_idx: int | None = None    # NP-Oberkante (rote Linie) wird gezogen
        self._drag_np_bot_idx: int | None = None    # NP-Untergrenze (grüne Linie) wird gezogen
        # Gesetzte NP-Obergrenzen: (page_idx, np_idx) → nicht überschreiben
        self._np_manual: set[tuple[int, int]] = set()
        # Gesetzte NP-Untergrenzen: (page_idx, np_idx) → nicht von _update_prev_np_bottom überschreiben
        self._np_manual_bot: set[tuple[int, int]] = set()

        self._build_ui()
        self._set_icon()

    # --------------------------------------------------------------- About ---

    def show_about(self):
        win = tk.Toplevel(self.root)
        win.title("über zebrastreifen")
        win.resizable(False, False)
        win.grab_set()

        pad = dict(padx=20, pady=4)

        tk.Label(win, text="zebrastreifen", font=("Helvetica", 18, "bold")).pack(pady=(20, 2))
        tk.Label(win, text="Chor-Streifen aus Noten-PDFs extrahieren",
                 font=("Helvetica", 10)).pack(**pad)
        tk.Frame(win, height=1, bg="#ccc").pack(fill=tk.X, padx=20, pady=10)

        shortcuts = [
            ("Navigation",      ""),
            ("Q / ←",           "Vorherige Seite"),
            ("E / →",           "Nächste Seite"),
            ("Page Up/Down",    "Vorherige / Nächste Seite"),
            ("",                ""),
            ("Schnitte",        ""),
            ("Linksklick",      "Schnittlinie setzen"),
            ("Drag",            "Linie verschieben"),
            ("Rechtsklick",     "Linie löschen / linken Rand setzen"),
            ("Delete / ←",      "Letzte Linie entfernen"),
            ("",                ""),
            ("Nullpunkte (NP)",  ""),
            ("← Klick (NP-Zone)","Nullpunkt + Streifen setzen"),
            ("Drag ◆",          "Nullpunkt verschieben"),
            ("Rechtsklick ◆",   "Nullpunkt entfernen"),
            ("⟳ NP füllen",    "Seite füllen (≥2 NP nötig)"),
            ("⟳ Alle Seiten",  "Alle leeren Seiten füllen"),
            ("",                ""),
            ("Streifen-Zonen",   ""),
            ("↓ Klick (Mitte)",  "Unterkante verschieben"),
            ("← Klick (links)",  "Linken Rand setzen"),
            ("",                ""),
            ("Taktzahlen",      ""),
            ("Linksklick [N]",  "Taktzahl +1 (propagiert)"),
            ("Rechtsklick [N]", "Taktzahl −1 (propagiert)"),
            ("Ctrl+Klick [N]",  "Seitenwechsel vor Streifen (Toggle)"),
            ("Checkbox",        "Taktzahlen ein-/ausblenden"),
            ("",                ""),
            ("Export",          ""),
            ("Kompakt / Tablet / Print", "Ausgabe-Format wählen"),
            ("Layout-Anzeige",  "Seiten- und Streifenverteilung (live)"),
            ("",                ""),
            ("Rotation",        ""),
            ("A",               "−0.5° (Gegenuhrzeigersinn)"),
            ("S / Ctrl+0",      "Rotation auf 0°"),
            ("D",               "+0.5° (Uhrzeigersinn)"),
            ("",                ""),
            ("Zoom",            ""),
            ("+ / −",           "Zoom rein / raus"),
            ("Ctrl + Mausrad",  "Zoom"),
            ("",                ""),
            ("Datei",           ""),
            ("Ctrl+O",          "PDF öffnen"),
            ("Ctrl+S",          "PDF exportieren"),
        ]

        frame = tk.Frame(win)
        frame.pack(padx=20, pady=4)
        for key, desc in shortcuts:
            if desc == "":
                # Kategorie-Header oder Leerzeile
                if key:
                    tk.Label(frame, text=key, font=("Helvetica", 9, "bold"),
                             anchor=tk.W).grid(row=frame.grid_size()[1], column=0,
                                               columnspan=2, sticky=tk.W, pady=(8, 1))
            else:
                row = frame.grid_size()[1]
                tk.Label(frame, text=key, font=("Courier", 9),
                         anchor=tk.W, width=18).grid(row=row, column=0, sticky=tk.W)
                tk.Label(frame, text=desc, font=("Helvetica", 9),
                         anchor=tk.W).grid(row=row, column=1, sticky=tk.W)

        tk.Frame(win, height=1, bg="#ccc").pack(fill=tk.X, padx=20, pady=10)
        tk.Label(win, text="Version 0.1  ·  © 2026 zebrastreifen",
                 font=("Helvetica", 8), fg="#888").pack(pady=(0, 16))
        tk.Button(win, text="Schliessen", command=win.destroy).pack(pady=(0, 16))

    # ----------------------------------------------------------------- Icon --

    def _set_icon(self):
        try:
            size = 64
            img = Image.new("RGB", (size, size), (255, 255, 255))
            draw = ImageDraw.Draw(img)
            stripe_w = 9
            # Diagonale Zebrastreifen (45°)
            for i in range(-2, 12):
                x0 = i * stripe_w * 2
                pts = [
                    (x0,          0),
                    (x0 + stripe_w, 0),
                    (x0 + stripe_w + size, size),
                    (x0 + size,   size),
                ]
                draw.polygon(pts, fill=(24, 24, 24))
            # Icon als PhotoImage halten (sonst garbage-collected)
            self._icon = ImageTk.PhotoImage(img)
            self.root.iconphoto(True, self._icon)
        except Exception:
            pass  # Icon ist optional

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        toolbar = tk.Frame(self.root, bd=1, relief=tk.RAISED)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        # Zeile 1: Navigation, Schnitte, Zoom, Export
        tk.Button(toolbar, text="PDF öffnen", command=self.open_pdf).pack(side=tk.LEFT, padx=4, pady=2)
        tk.Button(toolbar, text="← Zurück", command=self.prev_page).pack(side=tk.LEFT, padx=4, pady=2)
        tk.Button(toolbar, text="Weiter →", command=self.next_page).pack(side=tk.LEFT, padx=4, pady=2)
        self.page_label = tk.Label(toolbar, text="Keine Datei")
        self.page_label.pack(side=tk.LEFT, padx=8)
        tk.Button(toolbar, text="Letzte Linie entfernen", command=self.remove_last_line).pack(side=tk.LEFT, padx=4, pady=2)
        tk.Button(toolbar, text="Seite leeren", command=self.clear_lines).pack(side=tk.LEFT, padx=4, pady=2)
        tk.Button(toolbar, text="⟳ NP füllen", command=self.np_fill_page).pack(side=tk.LEFT, padx=4, pady=2)
        tk.Button(toolbar, text="⟳ Alle Seiten", command=self.np_fill_all_pages).pack(side=tk.LEFT, padx=4, pady=2)
        tk.Label(toolbar, text="  Zoom:").pack(side=tk.LEFT)
        tk.Button(toolbar, text="−", width=2, command=self.zoom_out).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(toolbar, text="+", width=2, command=self.zoom_in).pack(side=tk.LEFT, padx=2, pady=2)
        self.zoom_label = tk.Label(toolbar, text="150%", width=5)
        self.zoom_label.pack(side=tk.LEFT)
        tk.Button(toolbar, text="?", width=2, command=self.show_about).pack(side=tk.RIGHT, padx=4, pady=2)
        self._open_after_export = tk.BooleanVar(value=True)
        tk.Checkbutton(toolbar, text="PDF öffnen", variable=self._open_after_export).pack(side=tk.RIGHT, padx=2, pady=2)
        tk.Button(toolbar, text="PDF exportieren", command=self.export_pdf).pack(side=tk.RIGHT, padx=4, pady=2)

        # Zeile 2: Rotation
        toolbar2 = tk.Frame(self.root, bd=1, relief=tk.RAISED)
        toolbar2.pack(side=tk.TOP, fill=tk.X)
        tk.Label(toolbar2, text="Rotation:").pack(side=tk.LEFT, padx=4)
        self._rotation_var = tk.DoubleVar(value=0.0)
        self.rotation_slider = tk.Scale(
            toolbar2, variable=self._rotation_var,
            from_=-10, to=10, resolution=0.5, orient=tk.HORIZONTAL,
            length=220, showvalue=False,
            command=self._on_rotation_changed
        )
        self.rotation_slider.pack(side=tk.LEFT)
        self.rotation_label = tk.Label(toolbar2, text="0.0°", width=6)
        self.rotation_label.pack(side=tk.LEFT)
        tk.Button(toolbar2, text="Reset (Ctrl+0)", command=self.reset_rotation).pack(side=tk.LEFT, padx=4)
        tk.Checkbutton(toolbar2, text="Taktzahlen", variable=self._show_takt,
                       command=self._draw_lines).pack(side=tk.LEFT, padx=8)

        tk.Frame(toolbar2, width=1, bg="#aaa").pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)
        tk.Label(toolbar2, text="Export:").pack(side=tk.LEFT)
        for val, label in (("komprimiert", "Kompakt"), ("tablet", "Tablet"), ("print", "Print")):
            tk.Radiobutton(toolbar2, text=label, variable=self._export_preset,
                           value=val,
                           command=self._draw_lines).pack(side=tk.LEFT, padx=2)

        tk.Frame(toolbar2, width=1, bg="#aaa").pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)
        self.layout_label = tk.Label(toolbar2, text="", fg="#555", font=("Helvetica", 8))
        self.layout_label.pack(side=tk.LEFT, padx=4)

        # Scrollbarer Canvas-Bereich
        frame = tk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(frame, bg="#888", cursor="crosshair")
        vsb = tk.Scrollbar(frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas.bind("<ButtonPress-3>", self.on_right_click)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)          # Windows
        self.canvas.bind("<Button-4>", self.on_mousewheel)            # Linux scroll up
        self.canvas.bind("<Button-5>", self.on_mousewheel)            # Linux scroll down

        # Tastaturshortcuts
        self.root.bind("<Right>", lambda e: self.next_page())
        self.root.bind("<Left>", lambda e: self.prev_page())
        self.root.bind("<Next>", lambda e: self.next_page())      # Page Down
        self.root.bind("<Prior>", lambda e: self.prev_page())     # Page Up
        self.root.bind("<Delete>", lambda e: self.remove_last_line())
        self.root.bind("<BackSpace>", lambda e: self.remove_last_line())
        self.root.bind("<plus>", lambda e: self.zoom_in())
        self.root.bind("<minus>", lambda e: self.zoom_out())
        self.root.bind("<Control-plus>", lambda e: self.zoom_in())
        self.root.bind("<Control-minus>", lambda e: self.zoom_out())
        self.root.bind("<Control-o>", lambda e: self.open_pdf())
        self.root.bind("<Control-s>", lambda e: self.export_pdf())
        self.root.bind("<Control-0>", lambda e: self.reset_rotation())
        self.root.bind("a", lambda e: self.rotate_step(-0.5))
        self.root.bind("s", lambda e: self.reset_rotation())
        self.root.bind("d", lambda e: self.rotate_step(+0.5))
        self.root.bind("q", lambda e: self.prev_page())
        self.root.bind("e", lambda e: self.next_page())

        # Statuszeile
        self.status = tk.Label(self.root, text="Bitte PDF öffnen.", anchor=tk.W, relief=tk.SUNKEN)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    # ------------------------------------------------------------ PDF laden --

    def open_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF-Dateien", "*.pdf")])
        if not path:
            return
        self.doc = fitz.open(path)
        self.doc_path = path
        self.page_count = len(self.doc)
        self.page_index = 0
        self.cuts_per_page = {}
        self.rotation_per_page = {}
        self.left_margin_per_page = {}
        self.takt_per_page = {}
        self.takt_manual = set()
        self.pagebreak_set = set()
        self._np_points = {}
        self._np_manual = set()
        self._np_manual_bot = set()
        self._update_rotation_ui()
        self.render_page()
        self.status.config(text=f"Geöffnet: {path}")

    # --------------------------------------------------------- Seite rendern --

    def render_page(self):
        if self.doc is None:
            return
        page = self.doc[self.page_index]
        rotation = self.rotation_per_page.get(self.page_index, 0.0)
        mat = fitz.Matrix(self.scale, self.scale).prerotate(rotation)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self._page_img = img          # PIL-Kopie für Staff-Snap behalten
        self._photo = ImageTk.PhotoImage(img)

        self.canvas.delete("all")
        self.canvas.config(scrollregion=(0, 0, pix.width, pix.height))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)

        self.page_label.config(text=f"Seite {self.page_index + 1} / {self.page_count}")
        self._draw_lines()

    def _draw_lines(self):
        """Zeichnet alle Schnittlinien der aktuellen Seite."""
        self.canvas.delete("line")
        cuts = self.cuts_per_page.get(self.page_index, [])
        page_height = self.doc[self.page_index].rect.height

        for i, y_pdf in enumerate(cuts):
            y_canvas = self._pdf_to_canvas_y(y_pdf, page_height)
            color = "#e74c3c" if i % 2 == 0 else "#2ecc71"
            label = "oben" if i % 2 == 0 else "unten"
            w = int(self.doc[self.page_index].rect.width * self.scale)
            # Gestrichelt = auto (NP), durchgezogen = manuell
            ref_top = cuts[i] if i % 2 == 0 else (cuts[i - 1] if i > 0 else None)
            np_idx = self._find_np_by_top(ref_top) if ref_top is not None else None
            auto = np_idx is not None and (self.page_index, np_idx) not in self._np_manual
            dash = (6, 4) if auto else ()
            self.canvas.create_line(0, y_canvas, w, y_canvas,
                                    fill=color, width=2, dash=dash,
                                    tags=("line", f"line_{i}"))
            self.canvas.create_text(8, y_canvas - 8, text=f"{label} {i // 2 + 1}",
                                    fill=color, anchor=tk.W, tags="line")

        # Streifen farbig hinterlegen
        self._draw_strips()

        # Nullpunkt-Marker
        self._draw_np_markers(page_height)

        # Seitenwechsel-Marker
        self._draw_pagebreak_markers(page_height)

        # Taktzahlen
        self._draw_takt_labels(page_height)

        # Layout-Vorschau aktualisieren
        self._update_layout_label()

    def _draw_strips(self):
        """Graut alle Bereiche aus, die NICHT behalten werden (Negativ-Darstellung)."""
        cuts = self.cuts_per_page.get(self.page_index, [])
        page = self.doc[self.page_index]
        page_height = page.rect.height
        h = int(page_height * self.scale)
        w = int(page.rect.width * self.scale)
        gray = "#555555"

        def gray_rect(y1, y2):
            if y2 > y1:
                self.canvas.create_rectangle(0, y1, w, y2,
                                             fill=gray, stipple="gray50",
                                             outline="", tags="line")

        # Vollständige Paare sortiert nach Oberkante
        complete_pairs = sorted(zip(cuts[::2], cuts[1::2]), key=lambda p: p[0])

        # Offene Oberkante (ungerader letzter Klick)
        open_top = cuts[-1] if len(cuts) % 2 == 1 else None

        if not complete_pairs and open_top is None:
            # Noch gar nichts: alles grau
            gray_rect(0, h)
            return

        # Alle "freien" Bereiche (Streifen + offener Anfang) in eine sortierte Liste
        # Jeder Eintrag: (y_start, y_end) in Canvas-Koordinaten — clear (nicht grau)
        clear_zones = [(self._pdf_to_canvas_y(t, page_height),
                        self._pdf_to_canvas_y(b, page_height))
                       for t, b in complete_pairs]
        if open_top is not None:
            clear_zones.append((self._pdf_to_canvas_y(open_top, page_height), h))
        clear_zones.sort()

        # Grau zwischen den freien Zonen
        cursor = 0
        for y1, y2 in clear_zones:
            gray_rect(cursor, y1)
            cursor = max(cursor, y2)
        gray_rect(cursor, h)

        # Linker Rand: vertikaler grauer Bereich + blaue Linie
        left_x_pdf = self.left_margin_per_page.get(self.page_index)
        if left_x_pdf is not None:
            x_canvas = left_x_pdf * self.scale
            self.canvas.create_rectangle(0, 0, x_canvas, h,
                                         fill="#335599", stipple="gray50",
                                         outline="", tags="line")
            self.canvas.create_line(x_canvas, 0, x_canvas, h,
                                    fill="#3399ff", width=2, dash=(6, 4),
                                    tags=("line", "left_margin"))

    # ------------------------------------------------- Nullpunkte ------------

    def _is_np_zone(self, x_canvas):
        """True wenn x_canvas in der linken NP_ZONE_FRAC der Seitenbreite liegt."""
        if self.doc is None:
            return False
        page_w = self.doc[self.page_index].rect.width * self.scale
        return x_canvas < page_w * NP_ZONE_FRAC

    def _update_prev_np_bottom(self, new_y_top):
        """Setzt die Untergrenze des zuletzt gesetzten NP-Streifens (mit Lücke).
        Überspringt wenn die Untergrenze bereits manuell/per Propagation gesetzt wurde."""
        points = self._np_points.get(self.page_index, [])
        if len(points) == 0:
            return
        prev_idx = len(points) - 1
        if (self.page_index, prev_idx) in self._np_manual_bot:
            return
        _, _, prev_orig_top = points[prev_idx]
        cuts = self.cuts_per_page.get(self.page_index, [])
        for j in range(0, len(cuts) - 1, 2):
            if abs(cuts[j] - prev_orig_top) < 1.0:
                cuts[j + 1] = new_y_top - NP_BOTTOM_GAP
                break

    def _add_nullpunkt(self, x_canvas, y_canvas):
        """Setzt einen Nullpunkt sortiert nach Y und erzeugt das zugehörige Streifen-Paar.
        Y snapt auf erkannte Notenlinie; X wird auf Scan-Offset gesetzt (nach Klammern)."""
        if self._snap_y is not None:
            y_canvas = self._snap_y
        # X auf Scan-Position setzen (30px rechts = nach Klammern/Vorzeichen)
        x_canvas = min(x_canvas + 30,
                       self.doc[self.page_index].rect.width * self.scale - 1)
        x_pdf = x_canvas / self.scale
        y_pdf = y_canvas / self.scale
        page_height = self.doc[self.page_index].rect.height
        points = self._np_points.setdefault(self.page_index, [])
        cuts = self.cuts_per_page.setdefault(self.page_index, [])

        y_top = max(0.0, y_pdf - NP_MARGIN_TOP)

        # Einfügeposition nach Y bestimmen
        insert_pos = next((i for i, (_, yp, _) in enumerate(points) if yp > y_pdf),
                          len(points))
        prev = points[insert_pos - 1] if insert_pos > 0 else None
        nxt  = points[insert_pos]     if insert_pos < len(points) else None

        # Untergrenze: Abstand zum Vorgänger oder Nachfolger ableiten
        if prev is not None:
            _, _, prev_top = prev
            strip_h = y_top - prev_top
            y_bot = min(page_height, y_top + max(strip_h, NP_MARGIN_BOT))
        elif nxt is not None:
            _, _, nxt_top = nxt
            strip_h = nxt_top - y_top
            y_bot = min(page_height, y_top + max(strip_h, NP_MARGIN_BOT))
        else:
            y_bot = min(page_height, y_pdf + NP_MARGIN_BOT)

        # _np_manual-Indizes für Nachfolger verschieben (top und bot)
        self._np_manual = {
            (p, k) if p != self.page_index or k < insert_pos else (p, k + 1)
            for p, k in self._np_manual
        }
        self._np_manual_bot = {
            (p, k) if p != self.page_index or k < insert_pos else (p, k + 1)
            for p, k in self._np_manual_bot
        }

        # NP einfügen
        points.insert(insert_pos, (x_pdf, y_pdf, y_top))

        # Cuts einfügen: Position im cuts-Array = insert_pos * 2
        cuts.insert(insert_pos * 2, y_top)
        cuts.insert(insert_pos * 2 + 1, y_bot)

        # Untergrenze des Vorgängers anpassen — nur wenn nicht manuell gesetzt
        prev_np_idx = insert_pos - 1
        if prev is not None and (self.page_index, prev_np_idx) not in self._np_manual_bot:
            _, _, prev_top = prev
            for j in range(0, len(cuts) - 1, 2):
                if abs(cuts[j] - prev_top) < 1.0:
                    cuts[j + 1] = y_top - NP_BOTTOM_GAP
                    break

        # Obergrenze des Nachfolgers anpassen (Streifenhöhe beibehalten)
        if nxt is not None:
            _, _, nxt_top = nxt
            cuts[insert_pos * 2 + 1] = nxt_top - NP_BOTTOM_GAP

        n = len(points)
        self.status.config(
            text=f"Nullpunkt {insert_pos + 1}/{n} gesetzt (y={y_pdf:.0f} pt)")
        self._draw_lines()

    def _draw_np_markers(self, page_height):
        """Zeichnet NP-Zonengrenze und Rauten an Nullpunkt-Positionen."""
        page_w = self.doc[self.page_index].rect.width * self.scale
        h = page_height * self.scale
        x_zone = page_w * NP_ZONE_FRAC
        self.canvas.create_line(x_zone, 0, x_zone, h,
                                fill="#00bb44", width=1, dash=(3, 9),
                                tags="line")
        for x_pdf, y_pdf, _ in self._np_points.get(self.page_index, []):
            xc = x_pdf * self.scale
            yc = y_pdf * self.scale
            r = 6
            self.canvas.create_polygon(
                xc, yc - r, xc + r, yc, xc, yc + r, xc - r, yc,
                fill="#00cc44", outline="#ffffff", width=1,
                tags=("line", "np_marker")
            )

    def _snap_to_staff(self, x_canvas, y_canvas, search_px=60):
        """Sucht die oberste Notenlinie im Suchfenster.
        Notenlinie = dunkle Zeile mit niedriger Varianz (horizontal durchgehend).
        Senkrechte Linien/Klammern haben hohe Varianz → werden ignoriert.
        Startet 30px rechts vom Cursor um Klammern/Taktstriche zu überspringen."""
        if self._page_img is None:
            return None
        img = self._page_img
        # 30px Offset rechts: Klammern/Taktstriche überspringen
        x0 = max(0, int(x_canvas) + 30)
        x1 = min(img.width, x0 + 80)
        y0 = max(0, int(y_canvas) - search_px)
        y1 = min(img.height, int(y_canvas) + 15)
        if x1 <= x0 or y1 <= y0:
            return None
        region = img.crop((x0, y0, x1, y1)).convert('L')
        w, h = region.size
        if w < 10 or h == 0:
            return None
        data = region.tobytes()   # bytes, direkt slicebar, kein getdata()
        rows = [data[r * w:(r + 1) * w] for r in range(h)]
        row_avgs = [sum(r) / w for r in rows]
        avg_all = sum(row_avgs) / len(row_avgs)
        threshold = min(200, avg_all * 0.80)

        candidates = []
        for i, (avg, row) in enumerate(zip(row_avgs, rows)):
            if avg >= threshold:
                continue
            # Varianz der Zeile: Notenlinie hat niedrige Varianz (gleichmässig dunkel)
            variance = sum((v - avg) ** 2 for v in row) / w
            if variance < 1200:   # niedrige Varianz = horizontale Linie
                candidates.append(i)

        if not candidates:
            return None
        # Nächste dunkle Zeile zum Cursor (nicht die oberste der ganzen Region)
        cursor_rel = int(y_canvas) - y0
        best = min(candidates, key=lambda r: abs(r - cursor_rel))
        # Nur snappen wenn nah genug (max 25px)
        if abs(best - cursor_rel) > 25:
            return None
        return float(y0 + best)

    def _snap_to_vertical(self, x_canvas, y_canvas, search_px=60):
        """Sucht die nächste senkrechte Linie links/rechts vom Cursor.
        Senkrechte Linie = dunkle Spalte mit niedriger Zeilen-Varianz."""
        if self._page_img is None:
            return None
        img = self._page_img
        x0 = max(0, int(x_canvas) - search_px)
        x1 = min(img.width, int(x_canvas) + search_px)
        y0 = max(0, int(y_canvas) - 20)
        y1 = min(img.height, int(y_canvas) + 20)
        if x1 <= x0 or y1 <= y0:
            return None
        region = img.crop((x0, y0, x1, y1)).convert('L')
        w, h = region.size
        if w < 4 or h < 4:
            return None
        data = region.tobytes()   # bytes, direkt indexierbar, kein getdata()
        cols = [[data[r * w + c] for r in range(h)] for c in range(w)]
        col_avgs = [sum(c) / h for c in cols]
        avg_all = sum(col_avgs) / len(col_avgs)
        threshold = min(200, avg_all * 0.80)
        candidates = []
        for i, (avg, col) in enumerate(zip(col_avgs, cols)):
            if avg >= threshold:
                continue
            variance = sum((v - avg) ** 2 for v in col) / h
            if variance < 1200:
                candidates.append(i)
        if not candidates:
            return None
        # Nächste Spalte zum Cursor
        cursor_rel = int(x_canvas) - x0
        best = min(candidates, key=lambda c: abs(c - cursor_rel))
        return float(x0 + best)

    def _draw_snap_indicator(self, y_canvas):
        """Zeichnet Y-Snap-Indikator in der NP-Zone."""
        self.canvas.delete("snap_indicator")
        if y_canvas is None:
            return
        x_zone = (self.doc[self.page_index].rect.width * self.scale * NP_ZONE_FRAC
                  if self.doc else 60)
        r = 7
        xc = x_zone / 2
        self.canvas.create_oval(xc - r, y_canvas - r, xc + r, y_canvas + r,
                                outline="#00ff66", width=2,
                                tags="snap_indicator")
        self.canvas.create_line(0, y_canvas, x_zone, y_canvas,
                                fill="#00ff66", width=1, dash=(2, 4),
                                tags="snap_indicator")

    def _draw_snap_x_indicator(self, x_canvas):
        """Zeichnet X-Snap-Indikator (senkrechte Linie)."""
        self.canvas.delete("snap_x_indicator")
        if x_canvas is None or self.doc is None:
            return
        h = self.doc[self.page_index].rect.height * self.scale
        self.canvas.create_line(x_canvas, 0, x_canvas, h,
                                fill="#00ccff", width=1, dash=(3, 5),
                                tags="snap_x_indicator")
        r = 6
        self.canvas.create_oval(x_canvas - r, 0, x_canvas + r, r * 2,
                                outline="#00ccff", width=2,
                                tags="snap_x_indicator")

    def _find_np_by_top(self, y_val):
        """Gibt den NP-Index zurück, dessen orig_top mit y_val übereinstimmt, sonst None."""
        if y_val is None:
            return None
        for i, (_, _, orig_top) in enumerate(self._np_points.get(self.page_index, [])):
            if abs(orig_top - y_val) < 1.0:
                return i
        return None

    def _propagate_np_top(self, np_idx, new_top):
        """Propagiert geänderten Top-Offset zu allen folgenden nicht-manuellen NPs."""
        points = self._np_points.get(self.page_index, [])
        if np_idx >= len(points):
            return
        x_np, y_np, _ = points[np_idx]
        new_offset = y_np - new_top
        points[np_idx] = (x_np, y_np, new_top)
        cuts = self.cuts_per_page.get(self.page_index, [])
        for k in range(np_idx + 1, len(points)):
            if (self.page_index, k) in self._np_manual:
                break
            xk, yk, old_top_k = points[k]
            new_top_k = yk - new_offset
            for j in range(0, len(cuts) - 1, 2):
                if abs(cuts[j] - old_top_k) < 1.0:
                    cuts[j] = new_top_k
                    break
            points[k] = (xk, yk, new_top_k)

    def _propagate_np_bot(self, np_idx, new_bot):
        """Propagiert geänderte Untergrenze zu allen folgenden nicht-manuellen NP-Untergrenzen."""
        points = self._np_points.get(self.page_index, [])
        cuts = self.cuts_per_page.get(self.page_index, [])
        if np_idx >= len(points):
            return
        _, _, orig_top = points[np_idx]
        # Offset berechnen: neuer Abstand von top zu bot
        for j in range(0, len(cuts) - 1, 2):
            if abs(cuts[j] - orig_top) < 1.0:
                old_bot = cuts[j + 1]
                delta = new_bot - old_bot
                cuts[j + 1] = new_bot
                break
        else:
            return
        # Alle folgenden auto-Untergrenzen um delta verschieben
        for k in range(np_idx + 1, len(points)):
            if (self.page_index, k) in self._np_manual_bot:
                break
            _, _, top_k = points[k]
            for j in range(0, len(cuts) - 1, 2):
                if abs(cuts[j] - top_k) < 1.0:
                    cuts[j + 1] = cuts[j + 1] + delta
                    break
            # Diese Untergrenze als gesetzt markieren (von Propagation)
            self._np_manual_bot.add((self.page_index, k))
        # Auch diesen NP als gesetzt markieren
        self._np_manual_bot.add((self.page_index, np_idx))

    def _delete_np_and_strip(self, np_idx):
        """Löscht einen Nullpunkt und das zugehörige Streifen-Paar."""
        points = self._np_points.get(self.page_index, [])
        if np_idx >= len(points):
            return
        _, _, orig_top = points[np_idx]
        cuts = self.cuts_per_page.get(self.page_index, [])
        for j in range(0, len(cuts) - 1, 2):
            if abs(cuts[j] - orig_top) < 1.0:
                del cuts[j:j + 2]
                break
        points.pop(np_idx)
        new_manual = set()
        for p, k in self._np_manual:
            if p != self.page_index:
                new_manual.add((p, k))
            elif k < np_idx:
                new_manual.add((p, k))
            elif k > np_idx:
                new_manual.add((p, k - 1))
        self._np_manual = new_manual
        self._draw_lines()
        self.status.config(text="Nullpunkt und Streifen gelöscht.")

    # ------------------------------------------------- Taktzahlen ------------

    def _get_sorted_pairs(self, page_idx):
        """Sortierte (y_top, y_bot)-Paare für eine Seite."""
        cuts = self.cuts_per_page.get(page_idx, [])
        return sorted(zip(cuts[::2], cuts[1::2]), key=lambda p: p[0])

    def _get_all_strips_with_takt(self):
        """
        Alle vollständigen Streifen global geordnet, mit Taktzahlen.
        Fehlende Werte werden nach dem Delta-Schema berechnet und gespeichert.
        Gibt [[page_idx, local_idx, y_top, y_bot, takt], ...] zurück.
        """
        result = []
        for page_idx in sorted(self.cuts_per_page.keys()):
            for local_idx, (y_top, y_bot) in enumerate(self._get_sorted_pairs(page_idx)):
                stored = self.takt_per_page.get(page_idx, [])
                t = stored[local_idx] if local_idx < len(stored) else None
                result.append([page_idx, local_idx, y_top, y_bot, t])

        # Fehlende Taktzahlen auffüllen
        for n, entry in enumerate(result):
            if entry[4] is None:
                if n == 0:
                    t = 1
                elif n == 1:
                    t = result[0][4] + 4
                else:
                    step = result[n - 1][4] - result[n - 2][4]
                    t = result[n - 1][4] + max(1, step)
                entry[4] = t
                self._store_takt(entry[0], entry[1], t)
        return result

    def _store_takt(self, page_idx, local_idx, value):
        """Speichert Taktzahl für Streifen (page_idx, local_sorted_idx)."""
        if page_idx not in self.takt_per_page:
            self.takt_per_page[page_idx] = []
        lst = self.takt_per_page[page_idx]
        while len(lst) <= local_idx:
            lst.append(None)
        lst[local_idx] = value

    def _change_takt(self, page_idx, local_idx, delta):
        """Ändert Taktzahl um delta. Manuell gesetzte Folgestreifen bleiben unberührt."""
        strips = self._get_all_strips_with_takt()
        global_n = next((i for i, s in enumerate(strips)
                         if s[0] == page_idx and s[1] == local_idx), None)
        if global_n is None:
            return

        old_t = strips[global_n][4]
        new_t = max(0, old_t + delta)   # 0 erlaubt (Titel-Streifen)
        strips[global_n][4] = new_t
        self._store_takt(page_idx, local_idx, new_t)
        self.takt_manual.add((page_idx, local_idx))

        # Schritt für Propagation
        if global_n == 0:
            step = (strips[1][4] - old_t) if len(strips) > 1 else 4
        else:
            step = new_t - strips[global_n - 1][4]
        step = max(1, step)

        # Nur auto-berechnete Folgestreifen aktualisieren
        for k in range(global_n + 1, len(strips)):
            p, l = strips[k][0], strips[k][1]
            if (p, l) in self.takt_manual:
                break   # ab hier alles manuell → stopp
            t = strips[k - 1][4] + step
            strips[k][4] = t
            self._store_takt(p, l, t)

        self._draw_lines()

    def _on_takt_left(self, page_idx, local_idx):
        self._takt_click_handled = True
        self._change_takt(page_idx, local_idx, +1)

    def _on_takt_right(self, page_idx, local_idx):
        self._takt_click_handled = True
        self._change_takt(page_idx, local_idx, -1)

    def _draw_takt_labels(self, page_height):
        """Zeichnet [N]-Labels (oder [ ] wenn ausgeblendet) oben links in jeden Streifen."""
        show = self._show_takt.get()
        strips = self._get_all_strips_with_takt()
        left_x_pdf = self.left_margin_per_page.get(self.page_index, 0)
        x_canvas = left_x_pdf * self.scale + 4

        for page_idx, local_idx, y_top, y_bot, takt in strips:
            if page_idx != self.page_index:
                continue
            y_canvas = self._pdf_to_canvas_y(y_top, page_height) + 4
            tag = f"takt_{page_idx}_{local_idx}"

            has_break = (page_idx, local_idx) in self.pagebreak_set
            bg_color  = "#994400" if has_break else "#1a3a4a"
            bd_color  = "#ff8800" if has_break else "#3399ff"
            label_text = f"[{takt}]" if show else "[ ]"

            text_item = self.canvas.create_text(
                x_canvas, y_canvas,
                text=label_text,
                fill="#ffffff", font=("Courier", 10, "bold"),
                anchor=tk.NW, tags=("line", "takt_label", tag)
            )
            bbox = self.canvas.bbox(text_item)
            if bbox:
                bg = self.canvas.create_rectangle(
                    bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2,
                    fill=bg_color, outline=bd_color, width=1,
                    tags=("line", "takt_label", tag)
                )
                self.canvas.tag_raise(text_item, bg)

            self.canvas.tag_bind(tag, "<ButtonPress-1>",
                                 lambda e, p=page_idx, l=local_idx:
                                     self._on_takt_toggle_break(p, l)
                                     if (e.state & 0x4) else self._on_takt_left(p, l))
            self.canvas.tag_bind(tag, "<ButtonPress-3>",
                                 lambda e, p=page_idx, l=local_idx: self._on_takt_right(p, l))

    # ----------------------------------------- Seitenwechsel-Marker ----------

    def _on_takt_toggle_break(self, page_idx, local_idx):
        self._takt_click_handled = True
        key = (page_idx, local_idx)
        if key in self.pagebreak_set:
            self.pagebreak_set.discard(key)
            self.status.config(text="Seitenwechsel entfernt.")
        else:
            self.pagebreak_set.add(key)
            self.status.config(text="Seitenwechsel gesetzt.")
        self._draw_lines()

    def _draw_pagebreak_markers(self, page_height):
        """Orangefarbene gestrichelte Linie + Beschriftung für Seitenwechsel-Marker."""
        strips = self._get_all_strips_with_takt()
        for page_idx, local_idx, y_top, y_bot, takt in strips:
            if page_idx != self.page_index:
                continue
            if (page_idx, local_idx) not in self.pagebreak_set:
                continue
            y_c = self._pdf_to_canvas_y(y_top, page_height)
            w = int(self.doc[self.page_index].rect.width * self.scale)
            self.canvas.create_line(0, y_c - 3, w, y_c - 3,
                                    fill="#ff8800", width=3, dash=(8, 4),
                                    tags="line")
            self.canvas.create_text(w - 4, y_c - 10, text="↵ neue Seite",
                                    fill="#ff8800", font=("Helvetica", 8, "bold"),
                                    anchor=tk.E, tags="line")

    # ---------------------------------------- Layout-Vorschau ---------------

    def _simulate_layout(self):
        """Berechnet die Seitenverteilung ohne PDF zu erzeugen.
        Gibt Liste von Strip-Counts je Ausgabe-Seite zurück."""
        strips = self._collect_strips()
        if not strips:
            return []
        pg_w, pg_h, mg_top, mg_bot, mg_left, gap = \
            EXPORT_PRESETS[self._export_preset.get()]
        pages, cursor_y, count = [], mg_top, 0
        for i, (*_, rotation, takt, forced_break) in enumerate(strips):
            # Streifen-Höhe approximieren (y_top/y_bot stecken in strips[i])
            y_top_s = strips[i][1]
            y_bot_s = strips[i][2]
            strip_h = abs(y_bot_s - y_top_s)
            if i > 0 and (forced_break or cursor_y + strip_h > pg_h - mg_bot):
                pages.append(count)
                cursor_y, count = mg_top, 0
            cursor_y += strip_h + gap
            count += 1
        if count:
            pages.append(count)
        return pages

    def _update_layout_label(self):
        if not self.doc:
            self.layout_label.config(text="")
            return
        pages = self._simulate_layout()
        if not pages:
            self.layout_label.config(text="")
            return
        n = len(pages)
        dist = "/".join(str(c) for c in pages)
        total = sum(pages)
        self.layout_label.config(
            text=f"→  {n} {'Seite' if n == 1 else 'Seiten'}  |  {total} Str.  ({dist})")

    # ------------------------------------------- Koordinaten-Umrechnung -----

    def _pdf_to_canvas_y(self, y_pdf, page_height):
        return y_pdf * self.scale

    def _canvas_to_pdf_y(self, y_canvas):
        return y_canvas / self.scale

    # --------------------------------------------------------- Maus-Events --

    def _find_strip_at(self, y_canvas):
        """
        Gibt den Einfüge-Index k zurück, falls y_canvas innerhalb des k-ten
        Streifen-Paares liegt (zwischen Ober- und Unterkante).
        Gibt None zurück wenn ausserhalb aller Streifen (grauer Bereich).
        """
        cuts = self.cuts_per_page.get(self.page_index, [])
        page_height = self.doc[self.page_index].rect.height
        n_pairs = len(cuts) // 2
        for k in range(n_pairs):
            y_top_c = self._pdf_to_canvas_y(cuts[2 * k],     page_height)
            y_bot_c = self._pdf_to_canvas_y(cuts[2 * k + 1], page_height)
            lo, hi = min(y_top_c, y_bot_c), max(y_top_c, y_bot_c)
            if lo < y_canvas < hi:
                return k
        return None

    def _strip_zone(self, x_canvas, y_canvas):
        """
        Gibt 'left', 'bottom' oder None zurück je nach Position relativ zu Streifen.
        'left'   → linker Bereich eines Streifens (Klick setzt linken Rand)
        'bottom' → Rest eines Streifens (Klick verschiebt Unterkante)
        None     → grauer Bereich (Klick setzt neuen Schnitt)
        """
        k = self._find_strip_at(y_canvas)
        if k is None:
            return None
        left_x_pdf = self.left_margin_per_page.get(self.page_index, 0)
        if x_canvas < left_x_pdf * self.scale + LEFT_ZONE_PX:
            return 'left'
        return 'bottom'

    def _find_nearby_line(self, y_canvas):
        """Gibt den Index der nächsten Linie zurück, falls nah genug."""
        cuts = self.cuts_per_page.get(self.page_index, [])
        page_height = self.doc[self.page_index].rect.height
        for i, y_pdf in enumerate(cuts):
            yc = self._pdf_to_canvas_y(y_pdf, page_height)
            if abs(yc - y_canvas) <= DRAG_TOLERANCE:
                return i
        return None

    def _update_cursor(self, x_canvas, y_canvas):
        """Setzt den Cursor je nach Nähe zu einer Linie."""
        if self.doc is None:
            return
        # NP-Zone: linke X% der Seite
        if self._is_np_zone(x_canvas):
            for xp, yp, _ in self._np_points.get(self.page_index, []):
                if abs(xp * self.scale - x_canvas) <= 12 and abs(yp * self.scale - y_canvas) <= 12:
                    self.canvas.config(cursor="fleur")
                    return
            self.canvas.config(cursor="tcross")
            return
        # Über Taktzahl-Label?
        items = self.canvas.find_overlapping(x_canvas - 1, y_canvas - 1,
                                             x_canvas + 1, y_canvas + 1)
        for item in items:
            if "takt_label" in self.canvas.gettags(item):
                self.canvas.config(cursor="hand2")
                return
        # Nähe zu horizontaler Schnittlinie?
        cuts = self.cuts_per_page.get(self.page_index, [])
        page_height = self.doc[self.page_index].rect.height
        for y_pdf in cuts:
            yc = self._pdf_to_canvas_y(y_pdf, page_height)
            if abs(yc - y_canvas) <= DRAG_TOLERANCE:
                self.canvas.config(cursor="sb_v_double_arrow")
                return
        # Nähe zur vertikalen Randlinie?
        left_x_pdf = self.left_margin_per_page.get(self.page_index)
        if left_x_pdf is not None:
            xc = left_x_pdf * self.scale
            if abs(xc - x_canvas) <= DRAG_TOLERANCE:
                self.canvas.config(cursor="sb_h_double_arrow")
                return
        # Innerhalb eines Streifens → Zone bestimmt Cursor
        zone = self._strip_zone(x_canvas, y_canvas)
        if zone == 'left':
            self.canvas.config(cursor="left_side")
            return
        if zone == 'bottom':
            self.canvas.config(cursor="bottom_side")
            return
        self.canvas.config(cursor="crosshair")

    def on_mouse_move(self, event):
        x_canvas = self.canvas.canvasx(event.x)
        y_canvas = self.canvas.canvasy(event.y)
        in_np_zone = self._is_np_zone(x_canvas) and self.doc is not None
        # Y-Snap in NP-Zone
        if in_np_zone:
            self._snap_y = self._snap_to_staff(x_canvas, y_canvas)
            self._draw_snap_indicator(self._snap_y)
        else:
            self._snap_y = None
            self.canvas.delete("snap_indicator")
        # X-Snap überall (für linken Rand)
        if self.doc is not None:
            self._snap_x = self._snap_to_vertical(x_canvas, y_canvas)
            self._draw_snap_x_indicator(self._snap_x)
        else:
            self._snap_x = None
            self.canvas.delete("snap_x_indicator")
        if self._drag_line_index is not None or self._drag_np_index is not None:
            return
        self._update_cursor(x_canvas, y_canvas)

    def on_mouse_down(self, event):
        if self._takt_click_handled:
            self._takt_click_handled = False
            return
        if self.doc is None:
            return
        y_canvas = self.canvas.canvasy(event.y)
        x_canvas = self.canvas.canvasx(event.x)

        # NP-Rauten haben Priorität: immer zuerst prüfen (vor _find_nearby_line)
        if self._is_np_zone(x_canvas):
            points = self._np_points.get(self.page_index, [])
            for i, (xp, yp, _) in enumerate(points):
                if abs(xp * self.scale - x_canvas) <= 12 and abs(yp * self.scale - y_canvas) <= 12:
                    self._drag_np_index = i
                    self._drag_line_index = None
                    self._drag_np_top_idx = None
                    self.canvas.config(cursor="fleur")
                    return

        idx = self._find_nearby_line(y_canvas)
        if idx is not None:
            # Drag-Modus: bestehende Linie verschieben
            self._drag_line_index = idx
            self._drag_start_y = y_canvas
            self.canvas.config(cursor="fleur")
            # Erkennen ob NP-Ober- oder Untergrenze gezogen wird
            self._drag_np_top_idx = None
            self._drag_np_bot_idx = None
            cuts_now = self.cuts_per_page.get(self.page_index, [])
            if idx % 2 == 0 and idx < len(cuts_now):
                self._drag_np_top_idx = self._find_np_by_top(cuts_now[idx])
            elif idx % 2 == 1 and idx - 1 < len(cuts_now):
                self._drag_np_bot_idx = self._find_np_by_top(cuts_now[idx - 1])
        else:
            self._drag_line_index = None

            # Nullpunkt-Zone: neuen NP setzen
            if self._is_np_zone(x_canvas):
                # NP nur in grauen Bereichen erlauben (nicht innerhalb Streifen)
                if self._find_strip_at(y_canvas) is not None:
                    self.status.config(text="Nullpunkt nur ausserhalb bestehender Streifen setzen.")
                    return
                self._add_nullpunkt(x_canvas, y_canvas)
                return

            y_pdf = self._canvas_to_pdf_y(y_canvas)
            page_height = self.doc[self.page_index].rect.height
            zone = self._strip_zone(x_canvas, y_canvas)

            # Klick links im Streifen → linken Rand setzen
            if zone == 'left':
                x_eff = self._snap_x if self._snap_x is not None else x_canvas
                x_pdf = x_eff / self.scale
                self.left_margin_per_page[self.page_index] = x_pdf
                self._draw_lines()
                self.status.config(text=f"Linker Rand gesetzt: x={x_pdf:.1f} pt")
                return

            # Klick im Streifen (Rest) → Unterkante (grüne Linie) verschieben
            k = self._find_strip_at(y_canvas)
            if k is not None:
                cuts = self.cuts_per_page[self.page_index]
                cuts[2 * k + 1] = y_pdf
                pairs = sorted(zip(range(len(cuts) // 2),
                                   zip(cuts[::2], cuts[1::2])),
                               key=lambda x: x[1][0])
                strip_nr = next(i + 1 for i, (ki, _) in enumerate(pairs) if ki == k)
                self.status.config(
                    text=f"Streifen {strip_nr}: Unterkante → y={y_pdf:.1f} pt")
                self._draw_lines()
                return

            # Neuen Schnitt setzen (grauer Bereich)
            if self.page_index not in self.cuts_per_page:
                self.cuts_per_page[self.page_index] = []
            self.cuts_per_page[self.page_index].append(y_pdf)
            n = len(self.cuts_per_page[self.page_index])
            kind = "Oberkante" if n % 2 == 1 else "Unterkante"
            self.status.config(text=f"Seite {self.page_index + 1}: {kind} Streifen {(n + 1) // 2} gesetzt (y={y_pdf:.1f} pt)")
            self._draw_lines()

    def _drag_np(self, np_idx, x_canvas, y_canvas):
        """Verschiebt einen Nullpunkt. Y snapt auf Notenlinie; X ist frei anpassbar."""
        points = self._np_points.get(self.page_index, [])
        if np_idx >= len(points):
            return
        # Y: snap wenn verfügbar, sonst freie Bewegung
        if self._snap_y is not None:
            y_canvas = self._snap_y
        x_pdf = x_canvas / self.scale
        y_pdf = y_canvas / self.scale
        _, y_old, orig_top = points[np_idx]
        page_height = self.doc[self.page_index].rect.height
        # NP-Reihenfolge erzwingen
        if np_idx > 0:
            y_pdf = max(y_pdf, points[np_idx - 1][1] + 1)
        # Nachfolger werden mitgezogen → kein clamp nach unten nötig
        delta_y = y_pdf - y_old
        cuts = self.cuts_per_page.get(self.page_index, [])

        # Diesen NP verschieben
        new_top = max(0.0, y_pdf - NP_MARGIN_TOP)
        for j in range(0, len(cuts) - 1, 2):
            if abs(cuts[j] - orig_top) < 1.0:
                old_height = cuts[j + 1] - cuts[j]
                cuts[j]     = new_top
                cuts[j + 1] = min(page_height, new_top + old_height)
                break
        points[np_idx] = (x_pdf, y_pdf, new_top)

        # Untergrenze des Vorgänger-Streifens mitziehen
        if np_idx > 0:
            _, _, prev_orig_top = points[np_idx - 1]
            for j in range(0, len(cuts) - 1, 2):
                if abs(cuts[j] - prev_orig_top) < 1.0:
                    cuts[j + 1] = new_top - NP_BOTTOM_GAP
                    break

        # Alle folgenden auto-NPs um delta_y verschieben
        for k in range(np_idx + 1, len(points)):
            if (self.page_index, k) in self._np_manual:
                break
            xk, yk, top_k = points[k]
            new_yk = yk + delta_y
            new_top_k = max(0.0, top_k + delta_y)
            new_yk = max(new_yk, points[k - 1][1] + 1)
            new_top_k = max(0.0, new_yk - NP_MARGIN_TOP)
            for j in range(0, len(cuts) - 1, 2):
                if abs(cuts[j] - top_k) < 1.0:
                    old_h = cuts[j + 1] - cuts[j]
                    cuts[j]     = new_top_k
                    cuts[j + 1] = min(page_height, new_top_k + old_h)
                    break
            # Untergrenze von NP[k-1] anpassen
            _, _, prev_top_k = points[k - 1]
            for j in range(0, len(cuts) - 1, 2):
                if abs(cuts[j] - prev_top_k) < 1.0:
                    cuts[j + 1] = new_top_k - NP_BOTTOM_GAP
                    break
            points[k] = (xk, new_yk, new_top_k)

        self._draw_lines()

    def _add_np_to_page(self, page_idx, x_pdf, y_pdf):
        """NP ans Ende einer Seite anhängen (fill-Funktionen, immer aufsteigend)."""
        page = self.doc[page_idx]
        page_height = page.rect.height
        y_top = max(0.0, y_pdf - NP_MARGIN_TOP)
        points = self._np_points.setdefault(page_idx, [])
        cuts = self.cuts_per_page.setdefault(page_idx, [])
        if points:
            _, _, prev_top = points[-1]
            strip_h = y_top - prev_top
            y_bot = min(page_height, y_top + max(strip_h, NP_MARGIN_BOT))
            for j in range(0, len(cuts) - 1, 2):
                if abs(cuts[j] - prev_top) < 1.0:
                    cuts[j + 1] = y_top - NP_BOTTOM_GAP
                    break
        else:
            y_bot = min(page_height, y_pdf + NP_MARGIN_BOT)
        points.append((x_pdf, y_pdf, y_top))
        cuts.extend([y_top, y_bot])

    def _np_calibration(self, page_idx):
        """Gibt (dy, dx, x_base, einzug_dx) zurück, oder None.
        x_base  = x-Position der regulären Systeme (ohne Einzug)
        einzug_dx = Einzug von NP[0] relativ zu x_base (0 wenn kein Einzug)
        """
        points = self._np_points.get(page_idx, [])
        if len(points) < 2:
            return None
        dys = [points[i+1][1] - points[i][1] for i in range(len(points)-1)]
        dy = sum(dys) / len(dys)
        if dy <= 0:
            return None
        # x-Basis aus NP[1..n] (ohne NP[0], falls Einzug)
        xs = [p[0] for p in points[1:]] if len(points) > 1 else [points[0][0]]
        x_base = sum(xs) / len(xs)
        dx = 0.0  # reguläre Systeme haben keinen x-Drift (Annahme)
        # Einzug erkennen: NP[0].x > x_base + 10pt
        einzug_dx = points[0][0] - x_base if points[0][0] > x_base + 10 else 0.0
        return (dy, dx, x_base, einzug_dx)

    def np_fill_page(self):
        """Füllt die aktuelle Seite mit NPs basierend auf dem Abstand der letzten zwei NPs."""
        if self.doc is None:
            return
        cal = self._np_calibration(self.page_index)
        if cal is None:
            self.status.config(text="Mindestens 2 Nullpunkte nötig zum Füllen.")
            return
        dy, dx, x_base, _ = cal
        points = self._np_points[self.page_index]
        _, y_last, _ = points[-1]
        page_height = self.doc[self.page_index].rect.height
        page_w = self.doc[self.page_index].rect.width
        added = 0
        y_next = y_last + dy
        while y_next < page_height - NP_MARGIN_TOP:
            self._add_np_to_page(self.page_index,
                                 max(0.0, min(x_base, page_w)), y_next)
            y_next += dy
            added += 1
        self._draw_lines()
        self.status.config(text=f"{added} Nullpunkt(e) ergänzt.")

    def np_fill_all_pages(self):
        """Füllt alle Seiten ohne NPs anhand der Kalibrierung der aktuellen Seite."""
        if self.doc is None:
            return
        cal = self._np_calibration(self.page_index)
        if cal is None:
            self.status.config(text="Mindestens 2 Nullpunkte auf aktueller Seite nötig.")
            return
        dy, dx, x_base, einzug_dx = cal
        src_points = self._np_points[self.page_index]
        y_start = src_points[0][1]
        filled = 0
        for page_idx in range(self.page_count):
            if self._np_points.get(page_idx):
                continue   # bereits NPs vorhanden
            page = self.doc[page_idx]
            page_h = page.rect.height
            page_w = page.rect.width
            y_cur = y_start
            first = True
            while y_cur < page_h - NP_MARGIN_TOP:
                x_cur = x_base + (einzug_dx if first else 0.0)
                self._add_np_to_page(page_idx,
                                     max(0.0, min(x_cur, page_w)), y_cur)
                y_cur += dy
                first = False
            filled += 1
        self._draw_lines()
        self.status.config(text=f"{filled} Seite(n) mit NPs gefüllt.")

    def on_drag(self, event):
        if self._drag_np_index is not None and self.doc is not None:
            self._drag_np(self._drag_np_index,
                          self.canvas.canvasx(event.x),
                          self.canvas.canvasy(event.y))
            return
        if self._drag_line_index is None or self.doc is None:
            return
        y_canvas = self.canvas.canvasy(event.y)
        y_pdf = self._canvas_to_pdf_y(y_canvas)
        page_height = self.doc[self.page_index].rect.height
        y_pdf = max(0, min(y_pdf, page_height))
        self.cuts_per_page[self.page_index][self._drag_line_index] = y_pdf
        # NP-Oberkante: Offset zu allen folgenden auto-NPs propagieren
        if self._drag_np_top_idx is not None:
            self._propagate_np_top(self._drag_np_top_idx, y_pdf)
        # NP-Untergrenze: delta zu allen folgenden auto-Untergrenzen propagieren
        if self._drag_np_bot_idx is not None:
            self._propagate_np_bot(self._drag_np_bot_idx, y_pdf)
        self._draw_lines()

    def on_mouse_up(self, event):
        self._drag_line_index = None
        self._drag_np_index = None
        self.canvas.delete("snap_indicator")
        if self._drag_np_top_idx is not None:
            self._np_manual.add((self.page_index, self._drag_np_top_idx))
            self._drag_np_top_idx = None
        if self._drag_np_bot_idx is not None:
            self._drag_np_bot_idx = None
        x_canvas = self.canvas.canvasx(event.x)
        y_canvas = self.canvas.canvasy(event.y)
        self._update_cursor(x_canvas, y_canvas)

    def on_right_click(self, event):
        if self._takt_click_handled:
            self._takt_click_handled = False
            return
        if self.doc is None:
            return
        x_canvas = self.canvas.canvasx(event.x)
        y_canvas = self.canvas.canvasy(event.y)
        page_height = self.doc[self.page_index].rect.height

        # 0. NP-Zone: Rechtsklick auf Raute → Nullpunkt entfernen
        if self._is_np_zone(x_canvas):
            points = self._np_points.get(self.page_index, [])
            for i, (xp, yp, _) in enumerate(points):
                if abs(xp * self.scale - x_canvas) <= 12 and abs(yp * self.scale - y_canvas) <= 12:
                    points.pop(i)
                    self.status.config(text="Nullpunkt entfernt (Schnittlinien bleiben).")
                    self._draw_lines()
                    return
            return  # Kein Treffer: kein Standardverhalten in NP-Zone

        # 1. Nähe zu einer horizontalen Schnittlinie → smartes Löschen
        cuts = self.cuts_per_page.get(self.page_index, [])
        for i, y_pdf_cut in enumerate(cuts):
            yc = self._pdf_to_canvas_y(y_pdf_cut, page_height)
            if abs(yc - y_canvas) <= DRAG_TOLERANCE:
                if i % 2 == 0:  # Oberkante (rot)
                    np_idx = self._find_np_by_top(y_pdf_cut)
                    if np_idx is not None:
                        if (self.page_index, np_idx) in self._np_manual:
                            # Durchgezogen → gestrichelt (Manual-Flag entfernen)
                            self._np_manual.discard((self.page_index, np_idx))
                            self._draw_lines()
                            self.status.config(text="Manuelle Korrektur zurückgesetzt (NP aktiv).")
                        else:
                            # Gestrichelt → NP + Streifen löschen
                            self._delete_np_and_strip(np_idx)
                        return
                cuts.pop(i)
                self._draw_lines()
                self.status.config(text="Linie gelöscht.")
                return

        # 2. Nähe zur vertikalen Randlinie → löschen
        left_x_pdf = self.left_margin_per_page.get(self.page_index)
        if left_x_pdf is not None:
            xc = left_x_pdf * self.scale
            if abs(xc - x_canvas) <= DRAG_TOLERANCE:
                del self.left_margin_per_page[self.page_index]
                self._draw_lines()
                self.status.config(text="Linker Rand entfernt.")
                return

        # 3. Sonst: linken Rand an X-Position setzen (mit X-Snap)
        x_eff = self._snap_x if self._snap_x is not None else x_canvas
        x_pdf = x_eff / self.scale
        self.left_margin_per_page[self.page_index] = x_pdf
        self._draw_lines()
        self.status.config(text=f"Linker Rand gesetzt: x={x_pdf:.1f} pt")

    # ------------------------------------------------ Seiten-Navigation -----

    def _transfer_cuts(self, from_page, to_page):
        """Überträgt Schnitte von from_page auf to_page (falls to_page noch keine hat)."""
        if to_page not in self.cuts_per_page and from_page in self.cuts_per_page:
            self.cuts_per_page[to_page] = list(self.cuts_per_page[from_page])

    def _transfer_rotation(self, to_page):
        """Erbt Rotation von Seite to_page-2 (gleiche Scan-Seite)."""
        if to_page not in self.rotation_per_page:
            inherited = self.rotation_per_page.get(to_page - 2, 0.0)
            self.rotation_per_page[to_page] = inherited

    def _transfer_left_margin(self, to_page):
        """Erbt linken Rand von Seite to_page-2."""
        if to_page not in self.left_margin_per_page:
            inherited = self.left_margin_per_page.get(to_page - 2)
            if inherited is not None:
                self.left_margin_per_page[to_page] = inherited

    def _transfer_np_points(self, to_page):
        """Erbt Nullpunkte: zuerst von to_page-2 (Scan-Seite), sonst von to_page-1."""
        if to_page not in self._np_points:
            inherited = self._np_points.get(to_page - 2) or self._np_points.get(to_page - 1)
            if inherited:
                self._np_points[to_page] = list(inherited)

    def next_page(self):
        if self.doc is None or self.page_index >= self.page_count - 1:
            return
        prev = self.page_index
        self.page_index += 1
        self._transfer_cuts(prev, self.page_index)
        self._transfer_np_points(self.page_index)
        self._transfer_rotation(self.page_index)
        self._transfer_left_margin(self.page_index)
        self._update_rotation_ui()
        self.render_page()

    def prev_page(self):
        if self.doc is None or self.page_index <= 0:
            return
        self.page_index -= 1
        self._update_rotation_ui()
        self.render_page()

    # ------------------------------------------------------------ Zoom -------

    def zoom_in(self):
        if self.scale < SCALE_MAX:
            self.scale = round(min(self.scale + SCALE_STEP, SCALE_MAX), 2)
            self._update_zoom_label()
            self.render_page()

    def zoom_out(self):
        if self.scale > SCALE_MIN:
            self.scale = round(max(self.scale - SCALE_STEP, SCALE_MIN), 2)
            self._update_zoom_label()
            self.render_page()

    def _update_zoom_label(self):
        self.zoom_label.config(text=f"{int(self.scale * 100)}%")

    # --------------------------------------------------------- Rotation ------

    def _on_rotation_changed(self, _=None):
        val = round(self._rotation_var.get(), 1)
        self.rotation_per_page[self.page_index] = val
        self.rotation_label.config(text=f"{val:+.1f}°" if val != 0 else "0.0°")
        self.render_page()

    def reset_rotation(self):
        self.rotation_per_page[self.page_index] = 0.0
        self._rotation_var.set(0.0)
        self.rotation_label.config(text="0.0°")
        self.render_page()

    def rotate_step(self, delta):
        cur = self.rotation_per_page.get(self.page_index, 0.0)
        new_val = round(max(-10.0, min(10.0, cur + delta)), 1)
        self.rotation_per_page[self.page_index] = new_val
        self._rotation_var.set(new_val)
        self._on_rotation_changed()

    def _update_rotation_ui(self):
        val = self.rotation_per_page.get(self.page_index, 0.0)
        self._rotation_var.set(val)
        self.rotation_label.config(text=f"{val:+.1f}°" if val != 0 else "0.0°")

    def on_mousewheel(self, event):
        # Ctrl + Mausrad = Zoom
        if event.state & 0x4:
            if event.num == 4 or event.delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
        else:
            # Normales Scrollen
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")
            else:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------- Linien bearbeiten ----

    def remove_last_line(self):
        cuts = self.cuts_per_page.get(self.page_index)
        if cuts:
            n_before = len(cuts) // 2
            cuts.pop()
            n_after = len(cuts) // 2
            if n_after < n_before:
                takts = self.takt_per_page.get(self.page_index, [])
                if len(takts) > n_after:
                    del takts[n_after:]
                self.takt_manual = {(p, l) for p, l in self.takt_manual
                                    if not (p == self.page_index and l >= n_after)}
            self._draw_lines()
            self.status.config(text="Letzte Linie entfernt.")

    def clear_lines(self):
        self.cuts_per_page[self.page_index] = []
        self.takt_per_page[self.page_index] = []
        self._np_points[self.page_index] = []
        self._np_manual = {(p, k) for p, k in self._np_manual if p != self.page_index}
        self._np_manual_bot = {(p, k) for p, k in self._np_manual_bot if p != self.page_index}
        self.takt_manual = {(p, l) for p, l in self.takt_manual
                            if p != self.page_index}
        self.pagebreak_set = {(p, l) for p, l in self.pagebreak_set
                              if p != self.page_index}
        self._draw_lines()
        self.status.config(text="Alle Linien und Nullpunkte dieser Seite gelöscht.")

    # -------------------------------------------------------- PDF-Export ----

    def _add_footers(self, out_doc, pg_w=A4_W, pg_h=A4_H):
        total = len(out_doc)
        fname = os.path.basename(self.doc_path)
        gray      = (0.4, 0.4, 0.4)
        gray_light = (0.6, 0.6, 0.6)
        margin    = 5 * MM
        line_h    = 6 * MM   # Höhe pro Zeile (mind. 17pt für fontsize 9 in PyMuPDF 1.27+)
        foot_top  = pg_h - margin - 2 * line_h
        foot_bot  = pg_h - margin

        for i, page in enumerate(out_doc):
            # Seitennummer zentriert (obere Zeile)
            rect_center = fitz.Rect(0, foot_top, pg_w, foot_top + line_h)
            page.insert_textbox(rect_center, f"{i + 1} / {total}",
                                fontsize=9, color=gray, align=1)
            rect_fname = fitz.Rect(pg_w / 2, foot_top, pg_w - margin, foot_top + line_h)
            page.insert_textbox(rect_fname, fname,
                                fontsize=7, color=gray_light, align=2)
            rect_brand = fitz.Rect(pg_w / 2, foot_top + line_h, pg_w - margin, foot_bot)
            page.insert_textbox(rect_brand, "zebrastreifen",
                                fontsize=6, color=gray_light, align=2)

    def _collect_strips(self):
        """Gibt alle Streifen zurück: [(page_idx, y_top, y_bot, rotation, takt, forced_break), ...]"""
        strips = []
        for page_idx, local_idx, y_top, y_bot, takt in self._get_all_strips_with_takt():
            rotation = self.rotation_per_page.get(page_idx, 0.0)
            forced_break = (page_idx, local_idx) in self.pagebreak_set
            strips.append((page_idx, y_top, y_bot, rotation, takt, forced_break))
        return strips

    def export_pdf(self):
        if not self.doc:
            messagebox.showwarning("Kein PDF", "Bitte zuerst ein PDF öffnen.")
            return

        strips = self._collect_strips()
        if not strips:
            messagebox.showwarning("Keine Streifen", "Bitte erst Streifen definieren.")
            return

        out_path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF-Dateien", "*.pdf")],
            title="Ausgabe-PDF speichern"
        )
        if not out_path:
            return

        pg_w, pg_h, mg_top, mg_bot, mg_left, gap = \
            EXPORT_PRESETS[self._export_preset.get()]

        out_doc = fitz.open()
        cur_page = out_doc.new_page(width=pg_w, height=pg_h)
        cursor_y = mg_top
        # Cache: volle gedrehte Seite bei EXPORT_SCALE (einmal pro Seite rendern)
        _render_cache: dict[int, Image.Image] = {}

        for i, (page_idx, y_top, y_bot, rotation, takt, forced_break) in enumerate(strips):
            src_page = self.doc[page_idx]
            left_x = self.left_margin_per_page.get(page_idx, src_page.rect.x0)
            clip = fitz.Rect(left_x, y_top, src_page.rect.x1, y_bot)
            strip_w = src_page.rect.x1 - left_x
            has_custom_margin = page_idx in self.left_margin_per_page
            takt_label = f"[{takt}]" if self._show_takt.get() else None

            if rotation == 0:
                # Vektorgrafik – keine Qualitätseinbusse
                strip_h = abs(y_bot - y_top)
                if i > 0 and (forced_break or cursor_y + strip_h > pg_h - mg_bot):
                    cur_page = out_doc.new_page(width=pg_w, height=pg_h)
                    cursor_y = mg_top
                x_off = mg_left if has_custom_margin else (pg_w - strip_w) / 2
                dest = fitz.Rect(x_off, cursor_y, x_off + strip_w, cursor_y + strip_h)
                cur_page.show_pdf_page(dest, self.doc, page_idx, clip=clip)
                if takt_label:
                    cur_page.insert_textbox(
                        fitz.Rect(x_off + 2, cursor_y + 2, x_off + 38, cursor_y + 16),
                        takt_label, fontsize=8, color=(0.15, 0.15, 0.15)
                    )
                cursor_y += strip_h + gap

            else:
                # Beliebige Rotation: 300-DPI-Raster (WYSIWYG, per-page cache)
                if page_idx not in _render_cache:
                    mat = fitz.Matrix(EXPORT_SCALE, EXPORT_SCALE).prerotate(rotation)
                    pix = src_page.get_pixmap(matrix=mat)
                    _render_cache[page_idx] = Image.frombytes(
                        "RGB", [pix.width, pix.height], pix.samples)
                full_img = _render_cache[page_idx]
                crop_y1 = int(y_top * EXPORT_SCALE)
                crop_y2 = int(y_bot * EXPORT_SCALE)
                img = full_img.crop((0, crop_y1, full_img.width, crop_y2))
                if has_custom_margin:
                    crop_x = int(left_x * EXPORT_SCALE)
                    img = img.crop((crop_x, 0, img.width, img.height))
                if takt_label:
                    draw = ImageDraw.Draw(img)
                    px = int(8 * EXPORT_SCALE)
                    draw.text((8, 8), takt_label, fill=(40, 40, 40), font_size=px)
                img_w_pt = img.width / EXPORT_SCALE
                img_h_pt = img.height / EXPORT_SCALE
                if i > 0 and (forced_break or cursor_y + img_h_pt > pg_h - mg_bot):
                    cur_page = out_doc.new_page(width=pg_w, height=pg_h)
                    cursor_y = mg_top
                x_off = mg_left if has_custom_margin else (pg_w - img_w_pt) / 2
                dest = fitz.Rect(x_off, cursor_y, x_off + img_w_pt, cursor_y + img_h_pt)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                cur_page.insert_image(dest, stream=buf.getvalue())
                cursor_y += img_h_pt + gap

        self._add_footers(out_doc, pg_w, pg_h)
        out_doc.save(out_path)
        out_doc.close()
        self.status.config(text=f"Exportiert: {out_path}")
        if self._open_after_export.get():
            import subprocess
            if os.name == "nt":
                os.startfile(out_path)
            else:
                subprocess.Popen(["xdg-open", out_path])
        else:
            messagebox.showinfo("Fertig", f"PDF gespeichert:\n{out_path}")


# ------------------------------------------------------------------ Main ----

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1000x800")
    app = StripApp(root)
    root.mainloop()
