"""Jaeger Studio pages — real, simple function for the tabs that were
wireframe stubs.  Each does something concrete: read live data, browse
the asset library, drive the avatar bus, edit an mscript, show config.

Kept self-contained (the GUI/logic-separation rule): a page reads from
the instance / trace / asset dirs and publishes to the bus it's handed;
it owns no core logic.  Everything is defensive — a missing model / file
degrades to a dash, never a crash.
"""

from __future__ import annotations

import pathlib
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from .theme import ACCENT, GOOD, INK, INK_DIM, _label


# ── shared helpers ──────────────────────────────────────────────────
def _stage(title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
    page = QFrame(); page.setObjectName("Stage")
    v = QVBoxLayout(page); v.setContentsMargins(28, 24, 28, 24); v.setSpacing(10)
    v.addWidget(_label(title, size=18, bold=True))
    if subtitle:
        s = _label(subtitle, color=INK_DIM, size=12); s.setWordWrap(True)
        v.addWidget(s)
    return page, v


def _row(label: str, value: str) -> QWidget:
    w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 4, 0, 4)
    h.addWidget(_label(label, color=INK_DIM, size=13))
    h.addStretch(1)
    h.addWidget(_label(str(value), color=INK, size=13, bold=True))
    return w


def _btn(text: str, slot, accent: bool = False) -> QPushButton:
    b = QPushButton(text); b.setObjectName("Accent" if accent else "Tab")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(lambda _=False: slot())
    return b


def _layout():
    from jaeger_os.core.instance.instance import (
        InstanceLayout, default_instance_name, resolve_instance_dir)
    return InstanceLayout(root=resolve_instance_dir(default_instance_name()))


def _active_character():
    try:
        from jaeger_os.personality.character import active_character
        return active_character(_layout().root)
    except Exception:  # noqa: BLE001
        return None


def _characters_root():
    from jaeger_os.personality.character import characters_root
    return characters_root()


def _pkg_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]  # …/jaeger_os


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3]


# ── Dashboard ───────────────────────────────────────────────────────
def dashboard_page(ctx: Any = None, agent_name: str = "Jaeger") -> QWidget:
    page, v = _stage("Dashboard", "Live overview of the agent + pipeline.")
    ch = _active_character()
    v.addWidget(_row("Active agent", getattr(ch, "name", None) or agent_name))
    v.addWidget(_row("Voice", getattr(ch, "voice_id", "") or "—"))
    try:
        from jaeger_os.agent.trace import baseline
        b = baseline(_layout().logs_dir / "trace.jsonl")
        v.addWidget(_row("Turns traced", b["turns"]))
        v.addWidget(_row("Avg turn", f'{b["total_s"]["avg"]}s'))
        v.addWidget(_row("Tool calls", b["tool_calls"]))
    except Exception:  # noqa: BLE001
        v.addWidget(_row("Turns traced", "—"))
    try:
        n = sum(1 for p in _characters_root().iterdir() if (p / "character.yaml").exists())
        v.addWidget(_row("Characters", n))
    except Exception:  # noqa: BLE001
        pass
    v.addStretch(1)
    return page


# ── Animation — trigger expressions on the live avatar ──────────────
def animation_page(ctx: Any = None) -> QWidget:
    page, v = _stage("Animation", "Trigger expressions on the avatar node.")
    status = _label("", color=INK_DIM, size=12)

    def trigger(emotion: str):
        try:
            from jaeger_os.agent.tools.avatar import set_avatar_state
            set_avatar_state(emotion)
            status.setText(f"sent: {emotion}")
        except Exception as exc:  # noqa: BLE001
            status.setText(f"no avatar node ({type(exc).__name__})")

    grid = QHBoxLayout(); grid.setSpacing(8)
    for emo in ("neutral", "happy", "sad", "thinking", "speaking", "listening"):
        grid.addWidget(_btn(emo, lambda e=emo: trigger(e)))
    grid.addStretch(1)
    gw = QWidget(); gw.setLayout(grid); v.addWidget(gw)
    v.addWidget(status)
    v.addSpacing(8)
    v.addWidget(_label("MSCRIPT SCENES", color=INK_DIM, size=10, bold=True))
    scenes = QListWidget(); scenes.setObjectName("Library")
    sdir = _pkg_root() / "nodes" / "animation_dev" / "mscript" / "scenes"
    for f in sorted(sdir.glob("*.py")) if sdir.exists() else []:
        scenes.addItem(f"◆  {f.stem}")
    v.addWidget(scenes, stretch=1)
    return page


# ── Editors — load / edit / save an mscript scene ───────────────────
def editors_page(ctx: Any = None) -> QWidget:
    page, v = _stage("Editors", "Edit an mscript animation scene.")
    sdir = _pkg_root() / "nodes" / "animation_dev" / "mscript" / "scenes"
    files = sorted(sdir.glob("*.py")) if sdir.exists() else []
    row = QHBoxLayout()
    picker = QListWidget(); picker.setObjectName("Library"); picker.setFixedWidth(220)
    for f in files:
        it = QListWidgetItem(f.stem); it.setData(Qt.ItemDataRole.UserRole, str(f))
        picker.addItem(it)
    editor = QPlainTextEdit(); editor.setPlaceholderText("Pick a scene to edit…")
    status = _label("", color=INK_DIM, size=12)
    cur = {"path": None}

    def load(item):
        p = item.data(Qt.ItemDataRole.UserRole); cur["path"] = p
        try:
            editor.setPlainText(pathlib.Path(p).read_text(encoding="utf-8"))
            status.setText(f"editing {pathlib.Path(p).name}")
        except Exception as exc:  # noqa: BLE001
            status.setText(f"read failed: {exc}")

    def save():
        if not cur["path"]:
            status.setText("nothing loaded"); return
        try:
            pathlib.Path(cur["path"]).write_text(editor.toPlainText(), encoding="utf-8")
            status.setText(f"saved {pathlib.Path(cur['path']).name}")
        except Exception as exc:  # noqa: BLE001
            status.setText(f"save failed: {exc}")

    picker.itemClicked.connect(load)
    row.addWidget(picker); row.addWidget(editor, stretch=1)
    rw = QWidget(); rw.setLayout(row); v.addWidget(rw, stretch=1)
    bar = QHBoxLayout(); bar.addWidget(status); bar.addStretch(1)
    bar.addWidget(_btn("Save", save, accent=True))
    bw = QWidget(); bw.setLayout(bar); v.addWidget(bw)
    return page


# ── Assets — browse + preview the asset library ─────────────────────
def assets_page(ctx: Any = None) -> QWidget:
    page, v = _stage("Assets", "Browse the asset library.")
    row = QHBoxLayout()
    lst = QListWidget(); lst.setObjectName("Library"); lst.setFixedWidth(300)
    preview = QLabel("select an asset"); preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    preview.setObjectName("CharView")

    roots = [
        ("icon", _pkg_root() / "assets"),
        ("card", _characters_root()),
        ("mscript", _pkg_root() / "nodes" / "animation_dev" / "mscript" / "scenes"),
    ]
    exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".py"}
    glyph = {".png": "🖼", ".jpg": "🖼", ".jpeg": "🖼", ".gif": "▶",
             ".bmp": "🖼", ".webp": "🖼", ".py": "◆"}
    count = 0
    for _kind, base in roots:
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if f.is_file() and f.suffix.lower() in exts:
                it = QListWidgetItem(f"{glyph.get(f.suffix.lower(), '•')}  {f.name}")
                it.setData(Qt.ItemDataRole.UserRole, str(f))
                lst.addItem(it); count += 1
                if count >= 400:
                    break

    def show(item):
        p = item.data(Qt.ItemDataRole.UserRole)
        if p and pathlib.Path(p).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
            pm = QPixmap(p)
            preview.setPixmap(pm.scaled(preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
        else:
            preview.setText(pathlib.Path(p).name if p else "—")

    lst.itemClicked.connect(show)
    v.addWidget(_label(f"{count} assets", color=INK_DIM, size=12))
    row.addWidget(lst); row.addWidget(preview, stretch=1)
    rw = QWidget(); rw.setLayout(row); v.addWidget(rw, stretch=1)
    return page


# ── Packs — the character roster as persona packs ───────────────────
def packs_page(ctx: Any = None) -> QWidget:
    page, v = _stage("Packs", "Persona packs — the character roster.")
    import yaml
    lst = QListWidget(); lst.setObjectName("Library")
    try:
        for p in sorted(_characters_root().iterdir()):
            y = p / "character.yaml"
            if not y.exists():
                continue
            try:
                d = yaml.safe_load(y.read_text(encoding="utf-8"))
                name = d.get("name", p.name)
                voice = (d.get("identity") or {}).get("voice_id", "")
                lst.addItem(f"●  {name:<18}  {voice}")
            except Exception:  # noqa: BLE001
                lst.addItem(f"●  {p.name}")
    except Exception:  # noqa: BLE001
        pass
    v.addWidget(_label(f"{lst.count()} packs", color=INK_DIM, size=12))
    v.addWidget(lst, stretch=1)
    return page


# ── Diagnostics — the pipeline trace baseline ───────────────────────
def diagnostics_page(ctx: Any = None) -> QWidget:
    page, v = _stage("Diagnostics", "Pipeline trace baseline (logs/trace.jsonl).")
    body = QVBoxLayout(); body.setSpacing(4)
    holder = QWidget(); holder.setLayout(body)

    def refresh():
        while body.count():
            it = body.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        try:
            from jaeger_os.agent.trace import baseline
            b = baseline(_layout().logs_dir / "trace.jsonl")
            body.addWidget(_row("Turns", b["turns"]))
            body.addWidget(_row("Avg / p50 / p95",
                                f'{b["total_s"]["avg"]} / {b["total_s"]["p50"]} / {b["total_s"]["p95"]} s'))
            body.addWidget(_row("Think avg", f'{b["think_s"]["avg"]} s'))
            body.addWidget(_row("Tool calls", b["tool_calls"]))
            if b["tools"]:
                body.addWidget(_label("PER TOOL", color=INK_DIM, size=10, bold=True))
                for name, t in b["tools"].items():
                    body.addWidget(_row(f"  {name}", f'×{t["calls"]}  avg {t["avg_s"]}s'))
            if not b["turns"]:
                body.addWidget(_label("No turns yet — talk to the agent, then refresh.",
                                      color=INK_DIM, size=12))
        except Exception as exc:  # noqa: BLE001
            body.addWidget(_label(f"trace unavailable: {exc}", color=INK_DIM, size=12))

    bar = QHBoxLayout(); bar.addStretch(1); bar.addWidget(_btn("↻ Refresh", refresh))
    bw = QWidget(); bw.setLayout(bar); v.addWidget(bw)
    v.addWidget(holder); v.addStretch(1)
    refresh()
    return page


# ── Learn — browse the migrated docs ────────────────────────────────
def learn_page(ctx: Any = None) -> QWidget:
    page, v = _stage("Learn", "Project docs + pipeline infographics.")
    row = QHBoxLayout()
    lst = QListWidget(); lst.setObjectName("Library"); lst.setFixedWidth(280)
    viewer = QPlainTextEdit(); viewer.setReadOnly(True)
    viewer.setPlaceholderText("Pick a doc…")
    docs = []
    for base in (_repo_root() / "docs", _repo_root() / "dev" / "docs"):
        if base.exists():
            docs += sorted(base.rglob("*.md"))
    for f in docs[:200]:
        it = QListWidgetItem(f.relative_to(_repo_root()).as_posix())
        it.setData(Qt.ItemDataRole.UserRole, str(f)); lst.addItem(it)

    def open_doc(item):
        try:
            viewer.setPlainText(pathlib.Path(item.data(Qt.ItemDataRole.UserRole))
                                .read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            viewer.setPlainText(f"read failed: {exc}")

    lst.itemClicked.connect(open_doc)
    v.addWidget(_label(f"{lst.count()} docs", color=INK_DIM, size=12))
    row.addWidget(lst); row.addWidget(viewer, stretch=1)
    rw = QWidget(); rw.setLayout(row); v.addWidget(rw, stretch=1)
    return page


# ── Settings — instance + config readout ────────────────────────────
def settings_page(ctx: Any = None, agent_name: str = "Jaeger") -> QWidget:
    page, v = _stage("Settings", "Instance + runtime configuration (read-only).")
    try:
        lay = _layout()
        v.addWidget(_row("Instance", lay.root.name))
        v.addWidget(_row("Instance path", str(lay.root)))
    except Exception:  # noqa: BLE001
        pass
    ch = _active_character()
    v.addWidget(_row("Active character", getattr(ch, "name", None) or agent_name))
    v.addWidget(_row("Voice", getattr(ch, "voice_id", "") or "—"))
    core = getattr(ctx, "core", None)
    model = getattr(core, "model_name", None) or getattr(core, "model", None) or "—"
    v.addWidget(_row("Model", model))
    v.addWidget(_label("Edit via the trait editor (Characters tab) or "
                       "per-instance config.yaml.", color=INK_DIM, size=11))

    # Messaging plugins — status + one-click in-process Activate. Reads the
    # token saved via set_credential; same path as the agent's activate_plugin
    # tool, the /plugins slash command, and boot auto-start.
    v.addWidget(_label("Messaging plugins", size=13, bold=True))
    plug_box = QVBoxLayout(); plug_box.setSpacing(2)
    plug_holder = QWidget(); plug_holder.setLayout(plug_box)

    def _refresh_plugins():
        while plug_box.count():
            it = plug_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        try:
            from jaeger_os.agent.tools.plugins import list_plugins
            from jaeger_os.plugins import list_bridges
            live = set(list_bridges())
            for p in (list_plugins().get("plugins") or []):
                nm = p.get("name", "")
                running = nm in live
                rw = QWidget(); h = QHBoxLayout(rw); h.setContentsMargins(0, 2, 0, 2)
                h.addWidget(_label(nm, color=INK, size=12, bold=True))
                h.addWidget(_label("live" if running else (p.get("status") or ""),
                                   color=GOOD if running else INK_DIM, size=11))
                h.addStretch(1)
                if not running:
                    h.addWidget(_btn("Activate", lambda n=nm: _activate(n)))
                plug_box.addWidget(rw)
        except Exception as exc:  # noqa: BLE001
            plug_box.addWidget(_label(f"plugins unavailable: {exc}", color=INK_DIM, size=11))

    def _activate(name: str):
        try:
            from jaeger_os.main import activate_plugin_inprocess
            activate_plugin_inprocess(name)
        except Exception:  # noqa: BLE001
            pass
        _refresh_plugins()

    v.addWidget(plug_holder)
    v.addWidget(_label("Activate reads the saved credential (set_credential). "
                       "Auto-start at boot via config.plugins.autostart.",
                       color=INK_DIM, size=10))
    _refresh_plugins()
    v.addStretch(1)
    return page
