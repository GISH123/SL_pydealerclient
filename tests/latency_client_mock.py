# latency_client_mock.py
import argparse
import json
import ssl
import sys
import urllib.request
from typing import Dict, Any


EXPECTED_KEYS = [
    "now",
    "gmcode",
    "start_t0",
    "stop_t1",
    "inference_latency_s",
    "dealer_latency_s",
    "latency_Ndelta_s",
]


def _fetch(url: str, use_https: bool) -> Dict[str, Any]:
    if use_https:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        resp = urllib.request.urlopen(url, context=ctx, timeout=5.0)
    else:
        resp = urllib.request.urlopen(url, timeout=5.0)

    body = resp.read().decode("utf-8", errors="replace")
    print("Status:", resp.status)
    print("Headers:")
    for k, v in resp.headers.items():
        print(f"  {k}: {v.strip()}")
    print("Body:")
    print(body)

    if not body.strip():
        raise RuntimeError("Empty body")

    data = json.loads(body)
    if not isinstance(data, dict):
        raise RuntimeError("JSON is not an object")

    return data


def _check_structure(data: Dict[str, Any]) -> None:
    missing = [k for k in EXPECTED_KEYS if k not in data]
    if missing:
        raise RuntimeError(f"Missing keys: {missing}")

    for num_key in ("inference_latency_s", "dealer_latency_s", "latency_Ndelta_s"):
        v = data[num_key]
        try:
            float(v)
        except Exception:
            raise RuntimeError(f"Key {num_key} is not numeric: {v!r}")


def run_test(host: str, test_https: bool) -> int:
    """
    Functional test.
    - Always tests HTTP on port 8880
    - If test_https is True and HTTPS server exists, also tests HTTPS on 8881
    Returns exit code: 0 = all good, 1 = some failure.
    """
    ok = True
    base_http = f"http://{host}:8880/latency"
    base_https = f"https://{host}:8881/latency"

    print(f"=== HTTP test to {base_http} ===")
    try:
        data_http = _fetch(base_http, use_https=False)
        _check_structure(data_http)
        print("[HTTP] OK")
    except Exception as e:
        print(f"[HTTP] FAILED: {e}")
        ok = False

    if test_https:
        print("\n=== HTTPS test to {base_https} ===")
        try:
            data_https = _fetch(base_https, use_https=True)
            _check_structure(data_https)
            print("[HTTPS] OK")
        except Exception as e:
            print(f"[HTTPS] FAILED: {e}")
            ok = False

    return 0 if ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", help="pydealerclient host (default: 127.0.0.1)")
    parser.add_argument("--https", action="store_true", help="also test HTTPS on port 8881")
    args = parser.parse_args(argv)

    return run_test(host=args.host, test_https=args.https)


if __name__ == "__main__":
    raise SystemExit(main())
