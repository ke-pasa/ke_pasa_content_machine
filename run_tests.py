import sys
import pytest
import io

if __name__ == "__main__":
    print("Running tests via pytest.main()...")
    
    # Capture stdout/stderr
    class Tee(io.StringIO):
        def write(self, s):
            sys.__stdout__.write(s)
            super().write(s)
            
    capture = Tee()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = capture
    sys.stderr = capture
    
    try:
        ret = pytest.main(["-vv", "tests/workers/test_article_generator.py"])
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        
    with open("test_output.txt", "w", encoding="utf-8") as f:
        f.write(capture.getvalue())
        
    print(f"pytest.main() returned: {ret}")
    sys.exit(ret)
