from __future__ import annotations

import os

from .api import create_server


def main() -> None:
    host = os.getenv("SMART_MAGATZEM_HOST", "127.0.0.1")
    port = int(os.getenv("SMART_MAGATZEM_PORT", "8000"))
    server = create_server(host, port)
    print(f"Backend local en http://{host}:{port}")
    print("Ctrl+C para detenerlo")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
