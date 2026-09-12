"""Runnable self-check for POST /screen — start the real server and hit it over HTTP,
using only the stdlib (no test-framework dependency for a single endpoint check).
Run: python test_main.py
"""
import io
import json
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from main import app

HOST, PORT = "127.0.0.1", 8901
# A real 4x4 PNG — decodable, so it must pass validation.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000004000000040802000000269309290"
    "000001349444154789c633c6164c400034c70165e0e003c320134191895090000000049454e44ae426082"
)


def _post_screen(documents_present: dict, files: dict) -> tuple[int, dict]:
    boundary = "----pramaan-test"
    body = io.BytesIO()

    def write_field(name: str, value: str) -> None:
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())

    write_field("uuid", "test-uuid-0000")
    write_field("documents_present", json.dumps(documents_present))
    for name, content in files.items():
        body.write(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}.png"\r\n'
            f"Content-Type: image/png\r\n\r\n".encode()
        )
        body.write(content)
        body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        f"http://{HOST}:{PORT}/screen",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main() -> None:
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)

    # A valid submission must return the API_CONTRACT.md response shape.
    status, result = _post_screen({"passport": True}, {"passport": TINY_PNG})
    assert status == 200, result
    assert isinstance(result["score"], (int, float))
    assert isinstance(result["hard_fail"], bool)
    assert isinstance(result["reason_codes"], list)

    # A file that isn't a real image must be rejected, not silently accepted.
    status, _ = _post_screen({"passport": True}, {"passport": b"not an image"})
    assert status == 400

    # documents_present claiming a file that wasn't actually sent must be rejected.
    status, _ = _post_screen({"passport": True}, {})
    assert status == 400

    server.should_exit = True
    print("OK:", result)


if __name__ == "__main__":
    main()
