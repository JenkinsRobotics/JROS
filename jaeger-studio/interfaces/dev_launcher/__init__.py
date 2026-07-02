"""Dev Launcher — a floating, always-on-top window that opens every JROS Qt
surface from one place. A *dev tool* (not a shipped surface): the windows are
still separate apps, and until they're unified this is the single launchpad to
open + evaluate them. `./launch --dev-gui` (dev instance) pops it; or run it
standalone with `python -m jaeger_os.interfaces.dev_launcher`."""

from .window import DevLauncher, run

__all__ = ["DevLauncher", "run"]
