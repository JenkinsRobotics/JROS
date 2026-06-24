"""``python -m jaeger_os.plugins.whisper_stt`` -> the STT method bench."""

import sys

from .bench import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
