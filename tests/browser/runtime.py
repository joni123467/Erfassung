"""Dedicated disposable browser-test instance. Never uses a developer database."""
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
root=Path(os.environ['ERFASSUNG_E2E_ROOT'])
for name in ('config','data','logs'):
    (root/name).mkdir(parents=True,exist_ok=True)
    os.environ[f'ERFASSUNG_{name.upper()}_DIR']=str(root/name)
os.environ.update(DB_TYPE='sqlite',DB_PATH=str(root/'data/e2e.db'),ERFASSUNG_DISABLE_SCHEDULER='1',
                  SESSION_SECRET_KEY='browser-tests-only-not-production',ERFASSUNG_TIMEZONE='Europe/Berlin')
os.environ.pop('DATABASE_URL',None)
