"""Run the synthetic broker fixture inside the candidate's actual Linux image."""
import subprocess
import sys
from pathlib import Path


if __name__=='__main__':
    code=Path(__file__).with_name('gateway_native_fixture.py').read_text()
    result=subprocess.check_output(['docker','run','--rm','--interactive','--entrypoint','python',
        'cybergold-python-candidate:market-parity','-c',code],input=Path(sys.argv[1]).read_text(),text=True)
    print(result.strip())
