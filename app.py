#!/usr/bin/env python3
"""
Audio Concatenator
GUI for joining audio files into a single WAV with click markers between them.
"""

import re
import sys
from pathlib import Path
from typing import Optional

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from joiner import JoinWavsWorker

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".aif", ".aiff", ".ogg", ".m4a", ".mp4"}

SORT_FIELDS = [
    ("Name (alphabetical)", "name"),
    ("Name (numerical)",    "num"),
    ("Date created",        "ctime"),
    ("Date modified",       "mtime"),
    ("Date accessed",       "atime"),
]

SORT_DIRECTIONS = [
    ("Ascending",  False),
    ("Descending", True),
]

BIT_DEPTHS = [
    ("16-bit", 2),
    ("24-bit", 3),
    ("32-bit", 4),
]

REGEX_SORT_MODES = [
    ("Natural text", "natural"),
    ("Numeric",      "numeric"),
    ("Alphabetical", "alpha"),
]

_REGEX_TOOLTIP = (
    "Enter a Python regex with at least one capture group  ( ) .\n"
    "The text captured by the group is used as this layer's sort key.\n\n"
    "Examples:\n"
    "  ^(\\d+)              captures a leading number\n"
    "  -(\\w+-irt)\\.       captures a suffix like 'ynq-irt'\n"
    "  _(\\d{4}-\\d{2}-\\d{2})  captures a date like '2024-03-15'\n\n"
    "Tip: Not sure how to write a regex? Describe what you need to an\n"
    "AI assistant (e.g. Claude or ChatGPT) and ask it to generate the\n"
    "pattern for you."
)

# ---------------------------------------------------------------------------
# Sort helpers
# ---------------------------------------------------------------------------

def _natural_key(s: str) -> list:
    """Sort key that orders 'track2' before 'track10'."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", s)]


def _ctime(path: str) -> float:
    """Creation time: st_birthtime on macOS, st_ctime elsewhere."""
    stat = Path(path).stat()
    return getattr(stat, "st_birthtime", stat.st_ctime)


def _sorted_paths(paths: list[str], field: str, reverse: bool) -> list[str]:
    if field == "name":
        return sorted(paths, key=lambda p: Path(p).name.lower(), reverse=reverse)
    if field == "num":
        return sorted(paths, key=lambda p: _natural_key(Path(p).name), reverse=reverse)
    if field == "ctime":
        return sorted(paths, key=_ctime, reverse=reverse)
    if field == "mtime":
        return sorted(paths, key=lambda p: Path(p).stat().st_mtime, reverse=reverse)
    if field == "atime":
        return sorted(paths, key=lambda p: Path(p).stat().st_atime, reverse=reverse)
    return paths


def _apply_suffix_order(paths: list[str], patterns: list[str]) -> list[str]:
    """
    Group files by base name, sort groups by natural key, sort within each
    group by the pattern's rank in the user's list.

    This iterates over every base soundfile in the folder (0001, 0002, 0003…)
    and applies the same suffix ordering to each one.

    Longest patterns are tried first when matching so that a specific pattern
    like 'emph-ans-irt' is never shadowed by the shorter 'ans-irt', regardless
    of their position in the user's list.
    """
    if not patterns:
        return paths

    # Compile; auto-escape anything that isn't valid regex.
    compiled: list[tuple[int, int, re.Pattern]] = []
    for rank, pat in enumerate(patterns):
        try:
            rx = re.compile(pat)
        except re.error:
            rx = re.compile(re.escape(pat))
        compiled.append((rank, len(pat), rx))

    # For matching: try longest pattern string first.
    by_length = sorted(compiled, key=lambda x: x[1], reverse=True)

    def classify(stem: str) -> tuple[str, int]:
        """Return (base_name, suffix_rank) for a filename stem."""
        for rank, _, rx in by_length:
            m = rx.search(stem)
            if m:
                pre  = stem[:m.start()].rstrip("-_")
                post = stem[m.end():].lstrip("-_")
                base = pre + ("-" if pre and post else "") + post
                return base, rank
        # No pattern matched — use the full stem as the base key,
        # rank beyond all named patterns so it sorts last in its group.
        return stem, len(patterns)

    # Build one group per unique base, preserving first-seen insertion order
    # so that groups whose base didn't sort cleanly still behave predictably.
    groups: dict[str, list[tuple[int, str]]] = {}
    for path in paths:
        base, rank = classify(Path(path).stem)
        if base not in groups:
            groups[base] = []
        groups[base].append((rank, path))

    # Sort base names with the same natural key used for filenames
    # (so 0002 < 0010, not 0002 < 0003 < … via lexical order).
    sorted_bases = sorted(groups.keys(), key=_natural_key)

    # Within each group sort by suffix rank; ties keep original list order
    # because Python's sort is stable.
    result: list[str] = []
    for base in sorted_bases:
        result.extend(path for _, path in sorted(groups[base], key=lambda x: x[0]))
    return result


def _apply_single_regex_layer(paths: list[str], pattern: str, group: int,
                               mode: str, reverse: bool) -> list[str]:
    """Single-layer regex sort. Unmatched files sort after matched ones."""
    try:
        rx = re.compile(pattern)
    except re.error:
        return paths

    matched: list[tuple[str, str]] = []
    unmatched: list[str] = []
    for path in paths:
        m = rx.search(Path(path).name)
        if m:
            try:
                captured = m.group(group)
                matched.append((captured, path))
                continue
            except IndexError:
                pass
        unmatched.append(path)

    if mode == "numeric":
        def key(item: tuple[str, str]):
            try:
                return float(item[0])
            except (ValueError, TypeError):
                return 0.0
    elif mode == "natural":
        def key(item: tuple[str, str]):
            return _natural_key(item[0])
    else:  # alpha
        def key(item: tuple[str, str]):
            return item[0].lower()

    matched.sort(key=key, reverse=reverse)
    return [p for _, p in matched] + unmatched


def _apply_multilayer_regex_sort(paths: list[str], layers: list[dict]) -> list[str]:
    """
    Multi-level stable sort applied from least-significant to most-significant
    layer, so Layer 1 (top of the list) acts as the primary sort key.
    """
    result = list(paths)
    for layer in reversed(layers):
        pat = layer.get("pattern", "")
        if pat:
            result = _apply_single_regex_layer(
                result, pat, layer["group"], layer["mode"], layer["reverse"]
            )
    return result


# ---------------------------------------------------------------------------
# DraggableListWidget — shared by the file list and the suffix order list
# ---------------------------------------------------------------------------

class DraggableListWidget(QListWidget):
    """
    QListWidget with multi-select drag-and-drop reordering.

    Shift+Click extends contiguous selection.
    Ctrl/Cmd+Click toggles individual items.
    Drag a selection to a new position — relative order is preserved.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    def dropEvent(self, event):
        if event.source() is not self:
            event.ignore()
            return

        target_item = self.itemAt(event.position().toPoint())
        if target_item is None:
            target_row = self.count()
        else:
            target_row = self.row(target_item)
            if self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem:
                target_row += 1

        selected_rows = sorted(self.row(item) for item in self.selectedItems())
        if not selected_rows:
            event.ignore()
            return

        items_data = [
            (self.item(r).text(), self.item(r).data(Qt.ItemDataRole.UserRole))
            for r in selected_rows
        ]
        rows_above = sum(1 for r in selected_rows if r < target_row)
        adjusted = target_row - rows_above

        for row in reversed(selected_rows):
            self.takeItem(row)

        for offset, (text, data) in enumerate(items_data):
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.insertItem(adjusted + offset, item)

        self.clearSelection()
        for offset in range(len(items_data)):
            self.item(adjusted + offset).setSelected(True)

        event.accept()


# ---------------------------------------------------------------------------
# Simple (GUI) sort panel
# ---------------------------------------------------------------------------

class SuffixOrderWidget(QGroupBox):
    """Sub-sort by ordered suffix patterns — designed for Dekereke-style names."""

    _HELP = (
        "Add substrings or regex patterns that appear in your filenames.\n\n"
        "Files that share the same base name (the filename with the matched\n"
        "pattern removed) are grouped together and ordered by this list.\n\n"
        "MATCHING RULE — longer patterns are always tried first, regardless\n"
        "of their position in the list. This prevents a short pattern like\n"
        "'ans-irt' from accidentally matching inside 'emph-ans-irt'.\n\n"
        "Drag entries to reorder their priority within matched groups."
    )

    def __init__(self, parent=None):
        super().__init__("Suffix Order", parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self.pattern_list = DraggableListWidget()
        self.pattern_list.setMaximumHeight(110)
        layout.addWidget(self.pattern_list)

        row = QHBoxLayout()
        self.add_input = QLineEdit()
        self.add_input.setPlaceholderText("Substring or regex pattern…")
        self.add_input.returnPressed.connect(self._add)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._remove_selected)
        help_btn = QPushButton("?")
        help_btn.setFixedWidth(28)
        help_btn.setToolTip(self._HELP)
        help_btn.clicked.connect(
            lambda: QMessageBox.information(self, "Suffix Order Help", self._HELP)
        )
        row.addWidget(self.add_input, 1)
        row.addWidget(add_btn)
        row.addWidget(remove_btn)
        row.addWidget(help_btn)
        layout.addLayout(row)

        self.apply_btn = QPushButton("Apply Suffix Order")
        layout.addWidget(self.apply_btn)

    def patterns(self) -> list[str]:
        return [self.pattern_list.item(i).text() for i in range(self.pattern_list.count())]

    def set_patterns(self, patterns: list[str]):
        self.pattern_list.clear()
        for p in patterns:
            self.pattern_list.addItem(p)

    def _add(self):
        text = self.add_input.text().strip()
        if not text:
            return
        try:
            re.compile(text)
            display = text
        except re.error:
            escaped = re.escape(text)
            QMessageBox.information(
                self, "Auto-escaped",
                f"'{text}' is not a valid regex pattern.\n\n"
                f"It has been added as a literal string (auto-escaped to '{escaped}').",
            )
            display = escaped
        self.pattern_list.addItem(display)
        self.add_input.clear()

    def _remove_selected(self):
        for item in reversed(self.pattern_list.selectedItems()):
            self.pattern_list.takeItem(self.pattern_list.row(item))


class GuiSortPanel(QWidget):
    """The Simple sort panel: standard sort fields + optional suffix order."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel("Sort by:"))
        self.field_combo = QComboBox()
        for label, _ in SORT_FIELDS:
            self.field_combo.addItem(label)
        sort_row.addWidget(self.field_combo)
        self.dir_combo = QComboBox()
        for label, _ in SORT_DIRECTIONS:
            self.dir_combo.addItem(label)
        sort_row.addWidget(self.dir_combo)
        self.apply_sort_btn = QPushButton("Apply Sort")
        sort_row.addWidget(self.apply_sort_btn)
        sort_row.addStretch()
        layout.addLayout(sort_row)

        self.suffix_widget = SuffixOrderWidget()
        layout.addWidget(self.suffix_widget)

    @property
    def sort_field(self) -> str:
        return SORT_FIELDS[self.field_combo.currentIndex()][1]

    @property
    def sort_reverse(self) -> bool:
        return SORT_DIRECTIONS[self.dir_combo.currentIndex()][1]


# ---------------------------------------------------------------------------
# Advanced (Regex) sort panel
# ---------------------------------------------------------------------------

class RegexLayerWidget(QWidget):
    """One row in the Advanced sort panel representing a single sort layer."""

    remove_requested   = Signal()
    move_up_requested  = Signal()
    move_down_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)

        up_btn = QPushButton("▲")
        up_btn.setFixedWidth(26)
        up_btn.setToolTip("Move this layer up (higher priority)")
        up_btn.clicked.connect(self.move_up_requested)

        down_btn = QPushButton("▼")
        down_btn.setFixedWidth(26)
        down_btn.setToolTip("Move this layer down (lower priority)")
        down_btn.clicked.connect(self.move_down_requested)

        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText(
            "Regex with capture group, e.g.  ^(\\d+)  or  -(\\w+-irt)\\."
        )
        self.pattern_edit.setToolTip(_REGEX_TOOLTIP)
        self.pattern_edit.textChanged.connect(self._validate)

        self.status_lbl = QLabel()
        self.status_lbl.setFixedWidth(16)

        self.group_spin = QSpinBox()
        self.group_spin.setRange(1, 9)
        self.group_spin.setValue(1)
        self.group_spin.setFixedWidth(44)
        self.group_spin.setToolTip(
            "Which capture group to sort by.\n"
            "Group 1 = first  ( ),  group 2 = second  ( ),  etc."
        )

        self.mode_combo = QComboBox()
        for label, _ in REGEX_SORT_MODES:
            self.mode_combo.addItem(label)
        self.mode_combo.setToolTip(
            "Natural text:  '2' sorts before '10'  (recommended for most names)\n"
            "Numeric:       parse the captured text as a number\n"
            "Alphabetical:  plain A–Z string comparison"
        )

        self.dir_combo = QComboBox()
        for label, _ in SORT_DIRECTIONS:
            self.dir_combo.addItem(label)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedWidth(26)
        remove_btn.setToolTip("Remove this layer")
        remove_btn.clicked.connect(self.remove_requested)

        layout.addWidget(up_btn)
        layout.addWidget(down_btn)
        layout.addWidget(self.pattern_edit, 1)
        layout.addWidget(self.status_lbl)
        layout.addWidget(QLabel("Grp:"))
        layout.addWidget(self.group_spin)
        layout.addWidget(self.mode_combo)
        layout.addWidget(self.dir_combo)
        layout.addWidget(remove_btn)

    def _validate(self, text: str):
        if not text:
            self.status_lbl.setText("")
            self.status_lbl.setToolTip("")
            return
        try:
            re.compile(text)
            self.status_lbl.setText("✓")
            self.status_lbl.setStyleSheet("color: green; font-weight: bold;")
            self.status_lbl.setToolTip("Valid regex pattern")
        except re.error as exc:
            self.status_lbl.setText("✗")
            self.status_lbl.setStyleSheet("color: red; font-weight: bold;")
            self.status_lbl.setToolTip(f"Invalid pattern: {exc}")

    def layer_config(self) -> dict:
        return {
            "pattern": self.pattern_edit.text().strip(),
            "group":   self.group_spin.value(),
            "mode":    REGEX_SORT_MODES[self.mode_combo.currentIndex()][1],
            "reverse": SORT_DIRECTIONS[self.dir_combo.currentIndex()][1],
        }

    def set_config(self, config: dict):
        self.pattern_edit.setText(config.get("pattern", ""))
        self.group_spin.setValue(int(config.get("group", 1)))
        mode = config.get("mode", "natural")
        mode_idx = next((i for i, (_, v) in enumerate(REGEX_SORT_MODES) if v == mode), 0)
        self.mode_combo.setCurrentIndex(mode_idx)
        reverse = config.get("reverse", False)
        self.dir_combo.setCurrentIndex(1 if reverse else 0)


class RegexSortPanel(QWidget):
    """
    Advanced sort panel: an ordered stack of regex sort layers.

    Layer 1 (top) is the primary sort key; each subsequent layer breaks ties
    within groups that are equal under all higher-priority layers.
    """

    _HELP = (
        "LAYER PRIORITY\n"
        "Layer 1 (top) = primary sort.  Layer 2 breaks ties within equal\n"
        "Layer-1 groups.  Layer 3 breaks ties within equal Layer-2 groups,\n"
        "and so on.  Use ▲ / ▼ to reorder layers.\n\n"
        "UNMATCHED FILES\n"
        "Files that don't match a layer's pattern are sorted after all\n"
        "matching files for that layer, but remain grouped correctly by any\n"
        "higher-priority layers they did match.\n\n"
        "DEKEREKE EXAMPLE\n"
        "  Layer 1:  ^(\\d+)          Numeric    Asc\n"
        "            → groups files by their leading number (0001, 0002…)\n\n"
        "  Layer 2:  -(\\w+-irt)\\.   Natural    Asc\n"
        "            → orders the suffix variants within each number group\n\n"
        "AI TIP\n"
        "Not sure how to write a regex?  Paste a few example filenames into\n"
        "Claude, ChatGPT, or another AI assistant and ask it to write a\n"
        "Python regex that captures the part you want to sort by."
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # Header
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("<b>Sort layers</b> — Layer 1 is primary; lower layers break ties"))
        help_btn = QPushButton("?")
        help_btn.setFixedWidth(28)
        help_btn.setToolTip(self._HELP)
        help_btn.clicked.connect(
            lambda: QMessageBox.information(self, "Advanced Sort Help", self._HELP)
        )
        hdr.addStretch()
        hdr.addWidget(help_btn)
        root.addLayout(hdr)

        # Layers frame
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.layers_layout = QVBoxLayout(frame)
        self.layers_layout.setContentsMargins(4, 4, 4, 4)
        self.layers_layout.setSpacing(2)
        root.addWidget(frame)

        # Buttons
        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add Layer")
        add_btn.clicked.connect(self._add_layer)
        self.apply_btn = QPushButton("Apply Regex Sort")
        btn_row.addWidget(add_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.apply_btn)
        root.addLayout(btn_row)

        self._add_layer()  # always start with one layer

    def _add_layer(self):
        layer = RegexLayerWidget()
        layer.remove_requested.connect(lambda l=layer: self._remove_layer(l))
        layer.move_up_requested.connect(lambda l=layer: self._move_layer(l, -1))
        layer.move_down_requested.connect(lambda l=layer: self._move_layer(l, 1))
        self.layers_layout.addWidget(layer)

    def _remove_layer(self, layer: RegexLayerWidget):
        if self.layers_layout.count() <= 1:
            return  # always keep at least one row
        self.layers_layout.removeWidget(layer)
        layer.deleteLater()

    def _move_layer(self, layer: RegexLayerWidget, delta: int):
        idx = self.layers_layout.indexOf(layer)
        new_idx = idx + delta
        if 0 <= new_idx < self.layers_layout.count():
            self.layers_layout.removeWidget(layer)
            self.layers_layout.insertWidget(new_idx, layer)

    def get_layers(self) -> list[dict]:
        layers = []
        for i in range(self.layers_layout.count()):
            item = self.layers_layout.itemAt(i)
            if item and isinstance(item.widget(), RegexLayerWidget):
                layers.append(item.widget().layer_config())
        return layers

    def set_layers(self, layer_configs: list[dict]):
        # Remove all existing layers
        while self.layers_layout.count():
            item = self.layers_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        # Add new layers from config
        for cfg in layer_configs:
            layer = RegexLayerWidget()
            layer.remove_requested.connect(lambda l=layer: self._remove_layer(l))
            layer.move_up_requested.connect(lambda l=layer: self._move_layer(l, -1))
            layer.move_down_requested.connect(lambda l=layer: self._move_layer(l, 1))
            layer.set_config(cfg)
            self.layers_layout.addWidget(layer)
        # Always keep at least one layer
        if self.layers_layout.count() == 0:
            self._add_layer()


# ---------------------------------------------------------------------------
# Settings serialisation helpers
# ---------------------------------------------------------------------------

_VALID_SORT_MODES   = {"simple", "advanced"}
_VALID_SORT_FIELDS  = {v for _, v in SORT_FIELDS}
_VALID_DIRECTIONS   = {"ascending", "descending"}
_VALID_SORT_AS      = {"natural", "numeric", "alpha"}


def _ys(value) -> str:
    """
    Serialize a scalar to a YAML-safe inline string.

    Uses pyyaml to handle quoting automatically, then takes only the first
    output line — pyyaml sometimes appends a '...' document-end marker on a
    second line that would corrupt inline comments.
    """
    if not _HAS_YAML:
        return str(value)
    raw = _yaml.dump(value, default_flow_style=True, allow_unicode=True)
    return raw.splitlines()[0] if raw.strip() else ""


def _build_settings_yaml(settings: dict) -> str:
    """
    Build a human-readable YAML string with per-field inline comments
    explaining every valid option.  Values with a closed set of allowed
    options include the full option list in their comment.
    """
    # Controlled-vocabulary values don't need YAML quoting; write them directly
    # so the comment stays on the same line without quoting artefacts.
    mode      = settings["sort_mode"]
    field     = settings["sort_field"]
    direction = settings["sort_direction"]

    lines = [
        "# Audio Concatenator — sort settings",
        "# Edit freely with any text editor.",
        "",
        f"sort_mode: {mode}  # simple | advanced",
        f"sort_field: {field}  # name | num | ctime | mtime | atime",
        f"sort_direction: {direction}  # ascending | descending",
        "",
        "suffix_order:  # substrings or regex patterns that identify file suffixes;",
        "               # one pattern per line — delete all entries (or write []) to disable.",
        "               # Longer patterns are always tried first, so 'emph-ans-irt'",
        "               # is never shadowed by the shorter 'ans-irt' regardless of order.",
    ]

    suffix = settings.get("suffix_order") or []
    if suffix:
        for p in suffix:
            lines.append(f"  - {_ys(p)}")
    else:
        lines.append("  []")

    lines += [
        "",
        "regex_layers:  # Advanced sort only — list of sort layers.",
        "               # Layer 1 (top) is the primary sort key; lower layers break ties.",
        "               # Delete all entries (or write []) when using Simple (GUI) sort.",
    ]

    layers = settings.get("regex_layers") or []
    if layers:
        for layer in layers:
            lines += [
                f"  - pattern: {_ys(layer['pattern'])}"
                "  # Python regex — must contain at least one capture group  ( )",
                f"    group: {layer['group']}"
                "  # which capture group to sort by: 1, 2, 3, …",
                f"    sort_as: {layer['sort_as']}"
                "  # natural | numeric | alpha",
                f"    direction: {layer['direction']}"
                "  # ascending | descending",
            ]
    else:
        lines.append("  []")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Concatenator")
        self.setMinimumSize(740, 680)
        self._worker: Optional[JoinWavsWorker] = None
        self._thread: Optional[QThread] = None
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Folder row ──────────────────────────────────────────────────────
        folder_row = QHBoxLayout()
        self.load_btn = QPushButton("Load Folder…")
        self.load_btn.clicked.connect(self._on_load_folder)
        self.folder_label = QLabel("No folder loaded")
        self.folder_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        folder_row.addWidget(self.load_btn)
        folder_row.addWidget(self.folder_label, 1)
        root.addLayout(folder_row)

        # ── File list ────────────────────────────────────────────────────────
        self.file_list = DraggableListWidget()
        root.addWidget(self.file_list, 1)

        # ── Sort mode toggle ─────────────────────────────────────────────────
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Sort mode:"))
        self._mode_group = QButtonGroup(self)
        self._radio_simple = QRadioButton("Simple (GUI)")
        self._radio_adv    = QRadioButton("Advanced (Regex)")
        self._radio_simple.setChecked(True)
        self._mode_group.addButton(self._radio_simple, 0)
        self._mode_group.addButton(self._radio_adv,    1)
        self._mode_group.idToggled.connect(self._on_mode_toggle)
        mode_row.addWidget(self._radio_simple)
        mode_row.addWidget(self._radio_adv)
        mode_row.addStretch()
        load_settings_btn = QPushButton("Load Settings…")
        load_settings_btn.setToolTip("Load sort settings from a YAML file")
        load_settings_btn.clicked.connect(self._load_settings)
        save_settings_btn = QPushButton("Save Settings…")
        save_settings_btn.setToolTip("Save current sort settings to a YAML file")
        save_settings_btn.clicked.connect(self._save_settings)
        mode_row.addWidget(load_settings_btn)
        mode_row.addWidget(save_settings_btn)
        root.addLayout(mode_row)

        # ── Stacked sort panels ──────────────────────────────────────────────
        self._sort_stack = QStackedWidget()

        self.gui_panel = GuiSortPanel()
        self.gui_panel.apply_sort_btn.clicked.connect(self._on_apply_sort)
        self.gui_panel.suffix_widget.apply_btn.clicked.connect(self._on_apply_suffix_order)
        self._sort_stack.addWidget(self.gui_panel)   # index 0

        self.regex_panel = RegexSortPanel()
        self.regex_panel.apply_btn.clicked.connect(self._on_apply_regex_sort)
        self._sort_stack.addWidget(self.regex_panel)  # index 1

        root.addWidget(self._sort_stack)

        # ── Output row ───────────────────────────────────────────────────────
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output:"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose output file…")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse_output)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(browse_btn)
        root.addLayout(output_row)

        # ── Bit depth + Join row ─────────────────────────────────────────────
        join_row = QHBoxLayout()
        join_row.addWidget(QLabel("Bit depth:"))
        self.depth_combo = QComboBox()
        for label, _ in BIT_DEPTHS:
            self.depth_combo.addItem(label)
        join_row.addWidget(self.depth_combo)
        join_row.addStretch()
        self.join_btn = QPushButton("Join Files")
        self.join_btn.setDefault(True)
        self.join_btn.clicked.connect(self._on_join)
        join_row.addWidget(self.join_btn)
        root.addLayout(join_row)

        self.statusBar().showMessage("Ready")

        # Ctrl+Shift+F (⌘+Shift+F on macOS) → show ffmpeg diagnostic
        shortcut = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        shortcut.activated.connect(self._show_ffmpeg_info)

    # ── Sort settings save / load ────────────────────────────────────────────

    def _collect_settings(self) -> dict:
        """Collect current sort settings into a plain dict."""
        mode = "simple" if self._radio_simple.isChecked() else "advanced"
        field = self.gui_panel.sort_field
        direction = "descending" if self.gui_panel.sort_reverse else "ascending"
        suffix = self.gui_panel.suffix_widget.patterns()

        raw_layers = self.regex_panel.get_layers()
        layers_out = []
        for l in raw_layers:
            layers_out.append({
                "pattern":   l["pattern"],
                "group":     l["group"],
                "sort_as":   l["mode"],
                "direction": "descending" if l["reverse"] else "ascending",
            })

        return {
            "sort_mode":       mode,
            "sort_field":      field,
            "sort_direction":  direction,
            "suffix_order":    suffix,
            "regex_layers":    layers_out,
        }

    def _apply_settings(self, data: dict):
        """
        Apply a settings dict to the UI.

        Each field is applied independently.  Invalid values are skipped and
        collected into a warning shown at the end, so a single bad entry never
        prevents the rest of the file from loading.
        """
        warnings: list[str] = []

        # ── sort_mode ────────────────────────────────────────────────────────
        mode = data.get("sort_mode")
        if mode is not None:
            if mode in _VALID_SORT_MODES:
                if mode == "advanced":
                    self._radio_adv.setChecked(True)
                else:
                    self._radio_simple.setChecked(True)
            else:
                warnings.append(
                    f"sort_mode: '{mode}' is not valid — must be 'simple' or 'advanced'. Skipped."
                )

        # ── sort_field ───────────────────────────────────────────────────────
        field = data.get("sort_field")
        if field is not None:
            if field in _VALID_SORT_FIELDS:
                idx = next((i for i, (_, v) in enumerate(SORT_FIELDS) if v == field), None)
                if idx is not None:
                    self.gui_panel.field_combo.setCurrentIndex(idx)
            else:
                warnings.append(
                    f"sort_field: '{field}' is not valid — "
                    f"must be one of: {', '.join(v for _, v in SORT_FIELDS)}. Skipped."
                )

        # ── sort_direction ───────────────────────────────────────────────────
        direction = data.get("sort_direction")
        if direction is not None:
            if direction in _VALID_DIRECTIONS:
                self.gui_panel.dir_combo.setCurrentIndex(1 if direction == "descending" else 0)
            else:
                warnings.append(
                    f"sort_direction: '{direction}' is not valid — "
                    f"must be 'ascending' or 'descending'. Skipped."
                )

        # ── suffix_order ─────────────────────────────────────────────────────
        suffix = data.get("suffix_order")
        if suffix is not None:
            if isinstance(suffix, list):
                self.gui_panel.suffix_widget.set_patterns([str(p) for p in suffix])
            else:
                warnings.append(
                    f"suffix_order: expected a list of strings, got {type(suffix).__name__}. Skipped."
                )

        # ── regex_layers ─────────────────────────────────────────────────────
        layers = data.get("regex_layers")
        if layers is not None:
            if not isinstance(layers, list):
                warnings.append(
                    f"regex_layers: expected a list, got {type(layers).__name__}. Skipped."
                )
            else:
                converted: list[dict] = []
                for i, raw in enumerate(layers):
                    if not isinstance(raw, dict):
                        warnings.append(f"regex_layers[{i}]: expected a dict. Skipped.")
                        continue
                    cfg: dict = {}

                    # pattern — accept any string; warn if it won't compile
                    pat = raw.get("pattern", "")
                    pat = str(pat) if pat is not None else ""
                    try:
                        re.compile(pat)
                    except re.error as exc:
                        warnings.append(
                            f"regex_layers[{i}].pattern: '{pat}' is not a valid regex "
                            f"({exc}). Loaded anyway — fix before applying sort."
                        )
                    cfg["pattern"] = pat

                    # group — integer 1–9
                    raw_group = raw.get("group", 1)
                    try:
                        g = int(raw_group)
                        if not (1 <= g <= 9):
                            raise ValueError(f"out of range 1–9")
                        cfg["group"] = g
                    except (ValueError, TypeError):
                        warnings.append(
                            f"regex_layers[{i}].group: '{raw_group}' is not valid — "
                            f"must be an integer 1–9. Using 1."
                        )
                        cfg["group"] = 1

                    # sort_as
                    sort_as = str(raw.get("sort_as", "natural"))
                    if sort_as in _VALID_SORT_AS:
                        cfg["mode"] = sort_as
                    else:
                        warnings.append(
                            f"regex_layers[{i}].sort_as: '{sort_as}' is not valid — "
                            f"must be 'natural', 'numeric', or 'alpha'. Using 'natural'."
                        )
                        cfg["mode"] = "natural"

                    # direction
                    dir_val = str(raw.get("direction", "ascending"))
                    if dir_val in _VALID_DIRECTIONS:
                        cfg["reverse"] = dir_val == "descending"
                    else:
                        warnings.append(
                            f"regex_layers[{i}].direction: '{dir_val}' is not valid — "
                            f"must be 'ascending' or 'descending'. Using 'ascending'."
                        )
                        cfg["reverse"] = False

                    converted.append(cfg)

                if converted:
                    self.regex_panel.set_layers(converted)

        # ── report any problems ───────────────────────────────────────────────
        if warnings:
            QMessageBox.warning(
                self, "Settings loaded with warnings",
                "Some values were skipped or substituted:\n\n"
                + "\n".join(f"  \u2022 {w}" for w in warnings),
            )

    def _save_settings(self):
        if not _HAS_YAML:
            QMessageBox.warning(
                self, "PyYAML not installed",
                "Install pyyaml to save/load settings:\n\n  pip install pyyaml",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save sort settings", "sort_settings.yaml",
            "YAML files (*.yaml *.yml);;All files (*)",
        )
        if not path:
            return
        if not path.lower().endswith((".yaml", ".yml")):
            path += ".yaml"

        settings = self._collect_settings()
        try:
            Path(path).write_text(_build_settings_yaml(settings), encoding="utf-8")
            self.statusBar().showMessage(f"Settings saved: {path}")
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def _load_settings(self):
        if not _HAS_YAML:
            QMessageBox.warning(
                self, "PyYAML not installed",
                "Install pyyaml to save/load settings:\n\n  pip install pyyaml",
            )
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Load sort settings", "",
            "YAML files (*.yaml *.yml);;All files (*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            data = _yaml.safe_load(text)
        except (OSError, _yaml.YAMLError) as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return
        if not isinstance(data, dict):
            QMessageBox.warning(self, "Invalid file", "The file does not contain a valid settings dict.")
            return
        self._apply_settings(data)
        self.statusBar().showMessage(f"Settings loaded: {path}")

    # ── Slots ────────────────────────────────────────────────────────────────

    def _show_ffmpeg_info(self):
        """
        Ctrl+Shift+F — show which ffmpeg / ffprobe binaries the app is using
        and whether they came from the bundled bin/ directory or from PATH.
        """
        import shutil
        from ffmpeg_utils import find_binary, _app_root

        lines: list[str] = []

        frozen = getattr(sys, "frozen", False)
        lines.append(f"Frozen (PyInstaller):  {'yes' if frozen else 'no'}")
        lines.append(f"App root:  {_app_root()}")
        lines.append("")

        for name in ("ffmpeg", "ffprobe"):
            exe = name + (".exe" if sys.platform == "win32" else "")
            bundled_path = _app_root() / "bin" / exe
            found = find_binary(name)

            if found is None:
                source = "NOT FOUND"
                detail = "Install ffmpeg system-wide or place a binary in bin/"
            elif bundled_path.is_file() and Path(found).resolve() == bundled_path.resolve():
                source = "bundled (bin/)"
                detail = found
            else:
                source = "system PATH"
                detail = found

            lines.append(f"{name}:")
            lines.append(f"  source : {source}")
            lines.append(f"  path   : {detail}")
            lines.append("")

        QMessageBox.information(
            self,
            "FFmpeg diagnostic  (Ctrl+Shift+F)",
            "\n".join(lines).rstrip(),
        )

    def _on_mode_toggle(self, btn_id: int, checked: bool):
        if checked:
            self._sort_stack.setCurrentIndex(btn_id)

    def _current_paths(self) -> list[str]:
        return [
            self.file_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.file_list.count())
        ]

    def _set_paths(self, paths: list[str]):
        self.file_list.clear()
        for path in paths:
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.file_list.addItem(item)

    def _on_load_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder of audio files")
        if not folder:
            return
        self.folder_label.setText(folder)
        paths = [
            str(p) for p in Path(folder).iterdir()
            if p.suffix.lower() in AUDIO_EXTENSIONS
        ]
        self._set_paths(_sorted_paths(paths, "name", False))
        stem, parent = Path(folder).name, Path(folder).parent
        self.output_edit.setText(str(parent / f"{stem}_joined.wav"))
        self.statusBar().showMessage(
            f"Loaded {self.file_list.count()} file(s) from {folder}"
        )

    def _on_apply_sort(self):
        if self.file_list.count() == 0:
            return
        self._set_paths(
            _sorted_paths(
                self._current_paths(),
                self.gui_panel.sort_field,
                self.gui_panel.sort_reverse,
            )
        )

    def _on_apply_suffix_order(self):
        patterns = self.gui_panel.suffix_widget.patterns()
        if not patterns:
            QMessageBox.information(self, "No patterns", "Add at least one pattern first.")
            return
        if self.file_list.count() == 0:
            return
        self._set_paths(_apply_suffix_order(self._current_paths(), patterns))
        self.statusBar().showMessage("Suffix order applied.")

    def _on_apply_regex_sort(self):
        layers = self.regex_panel.get_layers()
        active = [l for l in layers if l["pattern"]]
        if not active:
            QMessageBox.warning(self, "No patterns", "Enter at least one regex pattern.")
            return
        for layer in active:
            try:
                re.compile(layer["pattern"])
            except re.error as exc:
                QMessageBox.critical(
                    self, "Invalid pattern",
                    f"Pattern: {layer['pattern']!r}\nError: {exc}",
                )
                return
        if self.file_list.count() == 0:
            return
        self._set_paths(_apply_multilayer_regex_sort(self._current_paths(), active))
        n = len(active)
        self.statusBar().showMessage(
            f"Regex sort applied ({n} layer{'s' if n != 1 else ''})."
        )

    def _on_browse_output(self):
        initial = self.output_edit.text() or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self, "Save joined file as", initial, "WAV files (*.wav)"
        )
        if path:
            if not path.lower().endswith(".wav"):
                path += ".wav"
            self.output_edit.setText(path)

    def _on_join(self):
        if self.file_list.count() == 0:
            QMessageBox.warning(self, "No files", "Load a folder with audio files first.")
            return
        output = self.output_edit.text().strip()
        if not output:
            QMessageBox.warning(self, "No output path", "Choose an output file path first.")
            return

        _, sample_width = BIT_DEPTHS[self.depth_combo.currentIndex()]
        self._worker = JoinWavsWorker(
            output_file=output,
            file_paths=self._current_paths(),
            sample_width=sample_width,
        )
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.success.connect(self._on_join_success)
        self._worker.error.connect(self._on_join_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_done)

        self.join_btn.setEnabled(False)
        self.load_btn.setEnabled(False)
        self.statusBar().showMessage("Joining files…")
        self._thread.start()

    def _on_join_success(self, output_file: str):
        QMessageBox.information(self, "Done", f"Saved:\n{output_file}")
        self.statusBar().showMessage(f"Saved: {output_file}")

    def _on_join_error(self, message: str):
        QMessageBox.critical(self, "Error", message)
        self.statusBar().showMessage("Error during join.")

    def _on_thread_done(self):
        self.join_btn.setEnabled(True)
        self.load_btn.setEnabled(True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    try:
        from ffmpeg_utils import configure_pydub
        configure_pydub()
    except RuntimeError as exc:
        _app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "ffmpeg not found", str(exc))
        sys.exit(1)

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
