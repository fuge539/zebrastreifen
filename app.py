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
OUT_MARGIN_TOP    = 15 * MM   # Rand oben
OUT_MARGIN_BOTTOM = 22 * MM   # Rand unten (Platz für Fusszeile)
OUT_MARGIN_LEFT   = 10 * MM   # Linker Rand bei benutzerdefiniertem linken Schnitt
OUT_GAP           =  8 * MM   # Abstand zwischen Streifen
EXPORT_DPI        = 300       # Auflösung für rotierte Streifen
EXPORT_SCALE      = EXPORT_DPI / 72


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
            ("Taktzahlen",      ""),
            ("Linksklick [N]",  "Taktzahl +1 (propagiert)"),
            ("Rechtsklick [N]", "Taktzahl −1 (propagiert)"),
            ("Checkbox",        "Taktzahlen ein-/ausblenden"),
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
        tk.Label(win, text="© 2026 zebrastreifen",
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
            # Abwechselnd: gerade = oben (rot), ungerade = unten (grün)
            color = "#e74c3c" if i % 2 == 0 else "#2ecc71"
            label = "oben" if i % 2 == 0 else "unten"
            w = int(self.doc[self.page_index].rect.width * self.scale)
            self.canvas.create_line(0, y_canvas, w, y_canvas,
                                    fill=color, width=2, tags=("line", f"line_{i}"))
            self.canvas.create_text(8, y_canvas - 8, text=f"{label} {i // 2 + 1}",
                                    fill=color, anchor=tk.W, tags="line")

        # Streifen farbig hinterlegen
        self._draw_strips()

        # Taktzahlen
        self._draw_takt_labels(page_height)

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
        """Zeichnet [N]-Labels oben links in jeden vollständigen Streifen."""
        if not self._show_takt.get():
            return
        strips = self._get_all_strips_with_takt()
        left_x_pdf = self.left_margin_per_page.get(self.page_index, 0)
        x_canvas = left_x_pdf * self.scale + 4

        for page_idx, local_idx, y_top, y_bot, takt in strips:
            if page_idx != self.page_index:
                continue
            y_canvas = self._pdf_to_canvas_y(y_top, page_height) + 4
            tag = f"takt_{page_idx}_{local_idx}"

            text_item = self.canvas.create_text(
                x_canvas, y_canvas,
                text=f"[{takt}]",
                fill="#ffffff", font=("Courier", 10, "bold"),
                anchor=tk.NW, tags=("line", "takt_label", tag)
            )
            bbox = self.canvas.bbox(text_item)
            if bbox:
                bg = self.canvas.create_rectangle(
                    bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2,
                    fill="#1a3a4a", outline="#3399ff", width=1,
                    tags=("line", "takt_label", tag)
                )
                self.canvas.tag_raise(text_item, bg)

            self.canvas.tag_bind(tag, "<ButtonPress-1>",
                                 lambda e, p=page_idx, l=local_idx: self._on_takt_left(p, l))
            self.canvas.tag_bind(tag, "<ButtonPress-3>",
                                 lambda e, p=page_idx, l=local_idx: self._on_takt_right(p, l))

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
        if self._drag_line_index is not None:
            return
        self._update_cursor(self.canvas.canvasx(event.x),
                            self.canvas.canvasy(event.y))

    def on_mouse_down(self, event):
        if self._takt_click_handled:
            self._takt_click_handled = False
            return
        if self.doc is None:
            return
        y_canvas = self.canvas.canvasy(event.y)
        idx = self._find_nearby_line(y_canvas)
        if idx is not None:
            # Drag-Modus: bestehende Linie verschieben
            self._drag_line_index = idx
            self._drag_start_y = y_canvas
            self.canvas.config(cursor="fleur")
        else:
            self._drag_line_index = None
            x_canvas = self.canvas.canvasx(event.x)
            y_pdf = self._canvas_to_pdf_y(y_canvas)
            page_height = self.doc[self.page_index].rect.height
            zone = self._strip_zone(x_canvas, y_canvas)

            # Klick links im Streifen → linken Rand setzen
            if zone == 'left':
                x_pdf = x_canvas / self.scale
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

    def on_drag(self, event):
        if self._drag_line_index is None or self.doc is None:
            return
        y_canvas = self.canvas.canvasy(event.y)
        y_pdf = self._canvas_to_pdf_y(y_canvas)
        page_height = self.doc[self.page_index].rect.height
        y_pdf = max(0, min(y_pdf, page_height))
        self.cuts_per_page[self.page_index][self._drag_line_index] = y_pdf
        self._draw_lines()

    def on_mouse_up(self, event):
        self._drag_line_index = None
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

        # 1. Nähe zu einer horizontalen Schnittlinie → löschen
        cuts = self.cuts_per_page.get(self.page_index, [])
        for i, y_pdf in enumerate(cuts):
            yc = self._pdf_to_canvas_y(y_pdf, page_height)
            if abs(yc - y_canvas) <= DRAG_TOLERANCE:
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

        # 3. Sonst: linken Rand an X-Position setzen
        x_pdf = x_canvas / self.scale
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

    def next_page(self):
        if self.doc is None or self.page_index >= self.page_count - 1:
            return
        prev = self.page_index
        self.page_index += 1
        self._transfer_cuts(prev, self.page_index)
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
        self.takt_manual = {(p, l) for p, l in self.takt_manual
                            if p != self.page_index}
        self._draw_lines()
        self.status.config(text="Alle Linien dieser Seite gelöscht.")

    # -------------------------------------------------------- PDF-Export ----

    def _add_footers(self, out_doc):
        total = len(out_doc)
        fname = os.path.basename(self.doc_path)
        gray      = (0.4, 0.4, 0.4)
        gray_light = (0.6, 0.6, 0.6)
        margin    = 5 * MM
        line_h    = 6 * MM   # Höhe pro Zeile (mind. 17pt für fontsize 9 in PyMuPDF 1.27+)
        foot_top  = A4_H - margin - 2 * line_h
        foot_bot  = A4_H - margin

        for i, page in enumerate(out_doc):
            # Seitennummer zentriert (obere Zeile)
            rect_center = fitz.Rect(0, foot_top, A4_W, foot_top + line_h)
            page.insert_textbox(rect_center, f"{i + 1} / {total}",
                                fontsize=9, color=gray, align=1)
            # Dateiname rechts (obere Zeile)
            rect_fname = fitz.Rect(A4_W / 2, foot_top, A4_W - margin, foot_top + line_h)
            page.insert_textbox(rect_fname, fname,
                                fontsize=7, color=gray_light, align=2)
            # zebrastreifen rechts (untere Zeile)
            rect_brand = fitz.Rect(A4_W / 2, foot_top + line_h, A4_W - margin, foot_bot)
            page.insert_textbox(rect_brand, "zebrastreifen",
                                fontsize=6, color=gray_light, align=2)

    def _collect_strips(self):
        """Gibt alle Streifen in Reihenfolge zurück: [(page_idx, y_top, y_bot, rotation_deg, takt), ...]"""
        strips = []
        for page_idx, local_idx, y_top, y_bot, takt in self._get_all_strips_with_takt():
            rotation = self.rotation_per_page.get(page_idx, 0.0)
            strips.append((page_idx, y_top, y_bot, rotation, takt))
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

        out_doc = fitz.open()
        cur_page = out_doc.new_page(width=A4_W, height=A4_H)
        cursor_y = OUT_MARGIN_TOP
        # Cache: volle gedrehte Seite bei EXPORT_SCALE (einmal pro Seite rendern)
        _render_cache: dict[int, Image.Image] = {}

        for i, (page_idx, y_top, y_bot, rotation, takt) in enumerate(strips):
            src_page = self.doc[page_idx]
            left_x = self.left_margin_per_page.get(page_idx, src_page.rect.x0)
            clip = fitz.Rect(left_x, y_top, src_page.rect.x1, y_bot)
            strip_w = src_page.rect.x1 - left_x
            has_custom_margin = page_idx in self.left_margin_per_page
            takt_label = f"[{takt}]" if self._show_takt.get() else None

            if rotation == 0:
                # Vektorgrafik – keine Qualitätseinbusse
                strip_h = abs(y_bot - y_top)
                if i > 0 and cursor_y + strip_h > A4_H - OUT_MARGIN_BOTTOM:
                    cur_page = out_doc.new_page(width=A4_W, height=A4_H)
                    cursor_y = OUT_MARGIN_TOP
                x_off = OUT_MARGIN_LEFT if has_custom_margin else (A4_W - strip_w) / 2
                dest = fitz.Rect(x_off, cursor_y, x_off + strip_w, cursor_y + strip_h)
                cur_page.show_pdf_page(dest, self.doc, page_idx, clip=clip)
                if takt_label:
                    # insert_text ist in PyMuPDF 1.27 defekt → insert_textbox verwenden
                    cur_page.insert_textbox(
                        fitz.Rect(x_off + 2, cursor_y + 2, x_off + 38, cursor_y + 16),
                        takt_label, fontsize=8, color=(0.15, 0.15, 0.15)
                    )
                cursor_y += strip_h + OUT_GAP

            else:
                # Beliebige Rotation: 300-DPI-Raster
                # WYSIWYG: volle Seite mit Rotation rendern, dann PIL-crop an
                # denselben Pixelpositionen wie im Canvas (y_top/y_bot * EXPORT_SCALE).
                # NICHT als PDF-clip verwenden – dort gelten Original-Koordinaten,
                # die nach Rotation nicht mit dem Canvas-View übereinstimmen.
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
                    px = int(8 * EXPORT_SCALE)  # 8pt in Pixel bei Export-DPI
                    draw.text((8, 8), takt_label, fill=(40, 40, 40), font_size=px)
                # Pixmap-Grösse zurück in Punkte umrechnen
                img_w_pt = img.width / EXPORT_SCALE
                img_h_pt = img.height / EXPORT_SCALE
                if i > 0 and cursor_y + img_h_pt > A4_H - OUT_MARGIN_BOTTOM:
                    cur_page = out_doc.new_page(width=A4_W, height=A4_H)
                    cursor_y = OUT_MARGIN_TOP
                x_off = OUT_MARGIN_LEFT if has_custom_margin else (A4_W - img_w_pt) / 2
                dest = fitz.Rect(x_off, cursor_y, x_off + img_w_pt, cursor_y + img_h_pt)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                cur_page.insert_image(dest, stream=buf.getvalue())
                cursor_y += img_h_pt + OUT_GAP

        self._add_footers(out_doc)
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
