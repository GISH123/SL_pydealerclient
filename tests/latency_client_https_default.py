from latency_client_mock import run_test
import sys

if __name__ == "__main__":
    # host 固定 127.0.0.1，HTTP + HTTPS
    exit_code = run_test(host="127.0.0.1", test_https=True)

    # keep console open when double-clicked
    try:
        input("\n[HTTP+HTTPS TEST] Press Enter to close...")
    except EOFError:
        pass

    sys.exit(exit_code)
