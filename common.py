"""Local configuration helpers; never transmit configuration values."""
import hashlib
import os
from pathlib import Path
import secrets
import tempfile

def read_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values

def private_write(path, text, mode=0o600):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as file:
            file.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

def set_env(path, values):
    path = Path(path)
    if any('\n' in v or '\r' in v or "'" in v for v in values.values()):
        raise ValueError('Configuration values cannot contain newlines or single quotes')
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [line for line in lines if line.split('=', 1)[0].strip() not in values]
    lines += [key+"='"+value+"'" for key, value in values.items()]
    private_write(path, '\n'.join(lines)+'\n')

def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return salt, digest
