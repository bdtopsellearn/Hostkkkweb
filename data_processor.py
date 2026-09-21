import base64
import hashlib
import uuid
import re
import zlib
import gzip
import marshal
import types
from typing import List, Optional, Tuple, Any

def _get_key():
    try:
        return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()
    except Exception:
        return "CIPHER_DEFAULT_KEY"

def _x(d, k):
    try:
        x = base64.b64decode(d).decode()
        return "".join(chr(ord(c) ^ ord(k[i % len(k)])) for i, c in enumerate(x))
    except Exception:
        return ""

_K = _get_key()

class DataProcessor:
    """
    Internal system data processing engine.
    Used for multi-level decoding and signature detection in security scans.
    """
    def __init__(self, depth: int = 50):
        self.d = depth
        self.s = set()

    def process(self, data: str) -> Tuple[str, List[str]]:
        """Main processing entry point for recursive decoding."""
        c = data
        m = []
        d = 0
        while d < self.d:
            # 1. Standard Buffer Unpack
            b = self._b(c)
            if b:
                c = b
                m.append("BUF_1")
                d += 1
                continue
            # 2. Stream Decompress
            s = self._s(c)
            if s:
                c = s
                m.append("STR_2")
                d += 1
                continue
            # 3. Hex Map Unpack
            h = self._h(c)
            if h:
                c = h
                m.append("HEX_3")
                d += 1
                continue
            # 4. Binary Object Extraction
            o = self._o(c)
            if o:
                c = o
                m.append("OBJ_4")
                d += 1
                continue
            break
        return c, list(dict.fromkeys(m))

    def _b(self, s: str) -> Optional[str]:
        # Base64 logic
        p = [
            r'base64\.b64decode\s*\(\s*["\']([A-Za-z0-9+/=]{20,})["\']\s*\)',
            r'b64decode\s*\(\s*["\']([A-Za-z0-9+/=]{20,})["\']\s*\)',
            r'["\']([A-Za-z0-9+/=]{80,})["\']',
            r'eval\s*\(\s*base64\.b64decode\s*\(\s*b?["\']([A-Za-z0-9+/=]{20,})["\']\s*\)\.decode\(\)\s*\)'
        ]
        for x in p:
            ms = re.findall(x, s)
            for m in ms:
                try:
                    r = base64.b64decode(m)
                    try:
                        d = r.decode('utf-8')
                        if any(k in d for k in ["import", "exec", "eval", "os", "sys", "requests"]):
                            return d
                    except Exception: pass
                    try:
                        d = zlib.decompress(r).decode('utf-8', errors='ignore')
                        return d
                    except Exception: pass
                except Exception: continue
        return None

    def _s(self, s: str) -> Optional[str]:
        # Decompression logic
        if any(k in s for k in ["zlib", "decompress", "\\x78\\x9c"]):
            bs = re.findall(r'b?["\']((?:\\x[0-9a-fA-F]{2})+)["\']', s)
            for b in bs:
                try:
                    r = bytes.fromhex(b.replace("\\x", ""))
                    try: 
                        res = zlib.decompress(r).decode('utf-8', errors='ignore')
                        if len(res) > 10: return res
                    except Exception: pass
                    try: 
                        res = gzip.decompress(r).decode('utf-8', errors='ignore')
                        if len(res) > 10: return res
                    except Exception: pass
                except Exception: continue
        return None

    def _h(self, s: str) -> Optional[str]:
        # Hex logic
        hp = r'((?:\\x[0-9a-fA-F]{2}){20,})'
        ms = re.findall(hp, s)
        for m in ms:
            try:
                h = m.replace("\\x", "")
                d = bytes.fromhex(h).decode('utf-8', errors='ignore')
                if len(d) > 10: return d
            except Exception: continue
        return None

    def _o(self, s: str) -> Optional[str]:
        # Marshal logic
        if "marshal" in s and "loads" in s:
            bs = re.findall(r'marshal\.loads\s*\(\s*b["\']((?:\\x[0-9a-fA-F]{2})+)["\']\s*\)', s)
            for b in bs:
                try:
                    r = bytes.fromhex(b.replace("\\x", ""))
                    obj = marshal.loads(r)
                    if isinstance(obj, types.CodeType):
                        strs = [str(c) for c in obj.co_consts if isinstance(c, (str, bytes))]
                        return "\n".join(strs)
                except Exception: continue
        return None

    def detect(self, s: str) -> bool:
        """Signature detection for known obfuscators."""
        sigs = [
            r'__PHOBOS__', r'phobo_version', 
            r'getattr\(.*[\'"]\x73\x79\x73\x74\x65\x6d[\'"]\)',
            r'eval\(compile\(.*[\'"]<string>[\'"]'
        ]
        return any(re.search(sig, s) for sig in sigs)
