"""Load PuTTY .ppk private keys (formats v2 and v3) into paramiko keys.

Supports ssh-rsa, ssh-ed25519 and ecdsa-sha2-nistp{256,384,521}, both
unencrypted and aes256-cbc encrypted. Encrypted v3 keys need argon2-cffi.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import struct
from pathlib import Path

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class PPKError(Exception):
    pass


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def string(self) -> bytes:
        if self.pos + 4 > len(self.data):
            raise PPKError("truncated key blob")
        (n,) = struct.unpack(">I", self.data[self.pos : self.pos + 4])
        self.pos += 4
        if self.pos + n > len(self.data):
            raise PPKError("truncated key blob")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def mpint(self) -> int:
        return int.from_bytes(self.string(), "big", signed=True)


def _parse_file(text: str) -> tuple[int, dict[str, str], bytes, bytes]:
    lines = text.replace("\r\n", "\n").split("\n")
    fields: dict[str, str] = {}
    version = 0
    public = private = b""
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip():
            continue
        if ":" not in line:
            raise PPKError(f"unexpected line in ppk file: {line[:40]!r}")
        key, value = line.split(":", 1)
        value = value.strip()
        if key.startswith("PuTTY-User-Key-File-"):
            version = int(key.rsplit("-", 1)[1])
            fields["Algorithm"] = value
        elif key in ("Public-Lines", "Private-Lines"):
            n = int(value)
            blob = base64.b64decode("".join(lines[i : i + n]))
            i += n
            if key == "Public-Lines":
                public = blob
            else:
                private = blob
        else:
            fields[key] = value
    if version not in (2, 3):
        raise PPKError("not a PuTTY v2/v3 private key file")
    return version, fields, public, private


def _derive_v3(passphrase: bytes, fields: dict[str, str]) -> tuple[bytes, bytes, bytes]:
    try:
        from argon2.low_level import Type, hash_secret_raw
    except ImportError as e:  # pragma: no cover - depends on optional dep
        raise PPKError("encrypted PPK v3 keys need the 'argon2-cffi' package") from e
    kdf = {"Argon2id": Type.ID, "Argon2i": Type.I, "Argon2d": Type.D}[fields["Key-Derivation"]]
    out = hash_secret_raw(
        secret=passphrase,
        salt=bytes.fromhex(fields["Argon2-Salt"]),
        time_cost=int(fields["Argon2-Passes"]),
        memory_cost=int(fields["Argon2-Memory"]),
        parallelism=int(fields["Argon2-Parallelism"]),
        hash_len=80,
        type=kdf,
    )
    return out[:32], out[32:48], out[48:]


def _mac_data(fields: dict[str, str], public: bytes, private: bytes) -> bytes:
    parts = [
        fields["Algorithm"].encode(),
        fields.get("Encryption", "none").encode(),
        fields.get("Comment", "").encode(),
        public,
        private,
    ]
    return b"".join(struct.pack(">I", len(p)) + p for p in parts)


def _decrypt(version: int, fields: dict[str, str], public: bytes, private: bytes, passphrase: str | None) -> bytes:
    enc = fields.get("Encryption", "none")
    pw = (passphrase or "").encode()
    if enc == "none":
        cipher_key = iv = None
        mac_key = hashlib.sha1(b"putty-private-key-file-mac-key").digest() if version == 2 else b""
    elif enc == "aes256-cbc":
        if passphrase is None:
            raise PPKError("key is encrypted; a passphrase is required")
        if version == 2:
            cipher_key = (hashlib.sha1(b"\0\0\0\0" + pw).digest() + hashlib.sha1(b"\0\0\0\1" + pw).digest())[:32]
            iv = b"\0" * 16
            mac_key = hashlib.sha1(b"putty-private-key-file-mac-key" + pw).digest()
        else:
            cipher_key, iv, mac_key = _derive_v3(pw, fields)
    else:
        raise PPKError(f"unsupported ppk encryption: {enc}")

    if cipher_key is not None:
        d = Cipher(algorithms.AES(cipher_key), modes.CBC(iv)).decryptor()
        private = d.update(private) + d.finalize()

    digest = hashlib.sha1 if version == 2 else hashlib.sha256
    expected = hmac.new(mac_key, _mac_data(fields, public, private), digest).hexdigest()
    if not hmac.compare_digest(expected, fields.get("Private-MAC", "").lower()):
        raise PPKError("MAC check failed: wrong passphrase or corrupted key")
    return private


_CURVES = {
    "nistp256": ec.SECP256R1(),
    "nistp384": ec.SECP384R1(),
    "nistp521": ec.SECP521R1(),
}


def _to_crypto_key(algo: str, public: bytes, private: bytes):
    pub = _Reader(public)
    priv = _Reader(private)
    if pub.string().decode() != algo:
        raise PPKError("public blob algorithm mismatch")
    if algo == "ssh-rsa":
        e, n = pub.mpint(), pub.mpint()
        d, p, q, iqmp = priv.mpint(), priv.mpint(), priv.mpint(), priv.mpint()
        return rsa.RSAPrivateNumbers(
            p=p, q=q, d=d,
            dmp1=d % (p - 1), dmq1=d % (q - 1), iqmp=iqmp,
            public_numbers=rsa.RSAPublicNumbers(e, n),
        ).private_key()
    if algo == "ssh-ed25519":
        return ed25519.Ed25519PrivateKey.from_private_bytes(priv.string()[:32])
    if algo.startswith("ecdsa-sha2-"):
        curve = _CURVES.get(pub.string().decode())
        if curve is None:
            raise PPKError(f"unsupported curve in {algo}")
        return ec.derive_private_key(priv.mpint(), curve)
    raise PPKError(f"unsupported key type: {algo}")


def load_ppk(path: str | Path, passphrase: str | None = None) -> paramiko.PKey:
    """Load a .ppk file and return a paramiko private key."""
    version, fields, public, private = _parse_file(Path(path).read_text())
    private = _decrypt(version, fields, public, private, passphrase)
    key = _to_crypto_key(fields["Algorithm"], public, private)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()
    return load_private_key_text(pem)


def load_private_key_text(text: str, passphrase: str | None = None) -> paramiko.PKey:
    last: Exception | None = None
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key(io.StringIO(text), password=passphrase)
        except (paramiko.SSHException, ValueError) as e:
            last = e
    raise PPKError(f"could not load private key: {last}")


def load_any_key(path: str | Path, passphrase: str | None = None) -> paramiko.PKey:
    """Load a .ppk or OpenSSH/PEM private key file."""
    path = Path(path).expanduser()
    text = path.read_text()
    if text.startswith("PuTTY-User-Key-File-"):
        return load_ppk(path, passphrase)
    return load_private_key_text(text, passphrase)
