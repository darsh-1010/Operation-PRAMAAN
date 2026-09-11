"""Runnable self-check for POST /screen — start the real server and hit it over HTTP,
using only the stdlib (no test-framework dependency for a single endpoint check).
Run: python test_main.py

Tests are split into two groups:
  1. Contract tests (from the original stub) — verify the API shape and input validation.
  2. Face pipeline tests — verify that face detection, quality, and matching integrate
     correctly through the /screen endpoint.
"""
import io
import json
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from main import app

HOST, PORT = "127.0.0.1", 8903
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
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}.bin"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode()
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _make_test_image(width: int = 100, height: int = 100) -> bytes:
    """Create a simple test image as PNG bytes using Pillow."""
    from PIL import Image as PILImage
    img = PILImage.new("RGB", (width, height), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)

    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  PASS: {name}")
        else:
            failed += 1
            print(f"  FAIL: {name} — {detail}")

    # ========================================================================
    # Group 1: Contract tests (preserved from original stub)
    # ========================================================================
    print("\n--- Contract tests ---")

    # 1. A valid submission (passport + selfie) must return the API_CONTRACT.md response shape.
    status, result = _post_screen({"passport": True, "selfie": True}, {"passport": TINY_PNG, "selfie": TINY_PNG})
    check("valid submission returns 200", status == 200, f"got {status}: {result}")
    check("response has score (number)", isinstance(result.get("score"), (int, float)), str(result))
    check("response has hard_fail (bool)", isinstance(result.get("hard_fail"), bool), str(result))
    check("response has reason_codes (list)", isinstance(result.get("reason_codes"), list), str(result))

    # 2. A selfie that isn't a decodable image is accepted (assumed video) — but not empty.
    status, result = _post_screen({"selfie": True}, {"selfie": b"not-a-real-video-but-not-empty-either"})
    check("non-image selfie accepted (assumed video)", status == 200, f"got {status}: {result}")

    # 3. A document photo that isn't a real image must be rejected, unlike the lenient selfie.
    status, _ = _post_screen({"passport": True}, {"passport": b"not an image"})
    check("non-image document rejected", status == 400, f"got {status}")

    # 4. documents_present claiming a file that wasn't actually sent must be rejected.
    status, _ = _post_screen({"selfie": True}, {})
    check("missing declared document rejected", status == 400, f"got {status}")

    # ========================================================================
    # Group 2: Face pipeline tests
    # ========================================================================
    print("\n--- Face pipeline tests ---")

    # 5. A plain gray image (no face) should still return 200 with FACE_NOT_DETECTED reason.
    no_face_img = _make_test_image(100, 100)
    status, result = _post_screen(
        {"passport": True, "selfie": True},
        {"passport": no_face_img, "selfie": no_face_img}
    )
    check("no-face image returns 200", status == 200, f"got {status}: {result}")
    check("no-face produces reason codes", len(result.get("reason_codes", [])) > 0, str(result))
    # Should mention FACE_NOT_DETECTED somewhere
    all_reasons = " ".join(result.get("reason_codes", []))
    check("no-face mentions detection failure",
          "FACE_NOT_DETECTED" in all_reasons or "no_face_matching" in all_reasons,
          all_reasons)
    check("no-face does NOT hard fail", result.get("hard_fail") is False, str(result))

    # 6. Score is within valid range (0-100).
    check("score is 0-100", 0 <= result.get("score", -1) <= 100, f"score={result.get('score')}")

    # 7. Empty documents_present with no files should return 200 (nothing to check).
    status, result = _post_screen({}, {})
    check("empty submission returns 200", status == 200, f"got {status}: {result}")
    check("empty submission score is valid", 0 <= result.get("score", -1) <= 100, str(result))

    # ========================================================================
    # Summary
    # ========================================================================
    server.should_exit = True
    print(f"\nResults: {passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
