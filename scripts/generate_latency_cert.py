# scripts/generate_latency_cert.py
from __future__ import annotations
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # project root
CERT_DIR = ROOT / "certs"
KEY_PATH = CERT_DIR / "latency_server.key"
CRT_PATH = CERT_DIR / "latency_server.crt"
CSR_CONF = CERT_DIR / "latency_csr.conf"


def ensure_latency_cert():
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_PATH.exists() and CRT_PATH.exists():
        print("[generate_latency_cert] cert/key already exist, skipping.")
        return

    print("[generate_latency_cert] generating self-signed latency cert via openssl...")

    # 1) private key
    subprocess.check_call(
        ["openssl", "genrsa", "-out", str(KEY_PATH), "2048"]
    )

    # 2) CSR config with SAN for localhost + 127.0.0.1
    csr_conf_text = f"""[ req ]
default_bits       = 2048
prompt             = no
default_md         = sha256
req_extensions     = req_ext
distinguished_name = dn

[ dn ]
C  = TW
ST = Taipei
L  = Taipei
O  = SL
OU = pydealerclient
CN = pydealer-latency.local

[ req_ext ]
subjectAltName = @alt_names

[ alt_names ]
DNS.1 = localhost
IP.1  = 127.0.0.1
"""
    CSR_CONF.write_text(csr_conf_text, encoding="utf-8")

    # 3) self-signed cert
    subprocess.check_call(
        [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-key",
            str(KEY_PATH),
            "-out",
            str(CRT_PATH),
            "-days",
            "365",
            "-config",
            str(CSR_CONF),
        ]
    )

    print("[generate_latency_cert] generated:")
    print("  key :", KEY_PATH)
    print("  cert:", CRT_PATH)


if __name__ == "__main__":
    ensure_latency_cert()
