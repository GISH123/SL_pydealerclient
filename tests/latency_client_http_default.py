from latency_client_mock import run_test
import sys

if __name__ == "__main__":
    # host 固定 127.0.0.1，HTTP only
    exit_code = run_test(host="127.0.0.1", test_https=False)

    # keep console open when double-clicked
    try:
        input("\n[HTTP TEST] Press Enter to close...")
    except EOFError:
        # just in case stdin is weird in some environments
        pass

    sys.exit(exit_code)
