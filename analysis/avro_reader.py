"""Minimalny czytnik plików Avro (Object Container File) w czystym Pythonie - bez dodatkowych bibliotek.

Obsługuje to, czego używa Empatica EmbracePlus: kodeki null i deflate, typy proste, record, enum,
array, map, union, fixed oraz odwołania do nazwanych typów. Specyfikacja: https://avro.apache.org/docs/
"""
import io, json, struct, zlib


class _Buf:
    __slots__ = ("b", "p")

    def __init__(self, b):
        self.b, self.p = b, 0

    def long(self):
        b, p, shift, n = self.b, self.p, 0, 0
        while True:
            c = b[p]; p += 1
            n |= (c & 0x7F) << shift
            if c < 0x80: break
            shift += 7
        self.p = p
        return (n >> 1) ^ -(n & 1)                     # zig-zag

    def read(self, n):
        s = self.b[self.p:self.p + n]; self.p += n
        return s

    def float(self):
        v = struct.unpack_from("<f", self.b, self.p)[0]; self.p += 4; return v

    def double(self):
        v = struct.unpack_from("<d", self.b, self.p)[0]; self.p += 8; return v


def _long_array(buf, n):
    """Szybkie dekodowanie n liczb int/long (zig-zag varint)."""
    b, p, out = buf.b, buf.p, [0] * n
    for i in range(n):
        shift = v = 0
        while True:
            c = b[p]; p += 1
            v |= (c & 0x7F) << shift
            if c < 0x80: break
            shift += 7
        out[i] = (v >> 1) ^ -(v & 1)
    buf.p = p
    return out


class _Decoder:
    def __init__(self, schema):
        self.named = {}
        self.root = self._resolve(schema, None)

    def _resolve(self, s, ns):
        """Zamienia schemat na postać z rozwiązanymi nazwami (dict / str prosty)."""
        if isinstance(s, str):
            if s in ("null", "boolean", "int", "long", "float", "double", "bytes", "string"):
                return s
            full = s if "." in s or not ns else f"{ns}.{s}"
            return self.named.get(full) or self.named[s]
        if isinstance(s, list):
            return {"type": "union", "branches": [self._resolve(x, ns) for x in s]}
        t = s["type"]
        if t in ("record", "error", "enum", "fixed"):
            name = s["name"]
            ns2 = name.rsplit(".", 1)[0] if "." in name else s.get("namespace", ns)   # przestrzeń nazw z pełnej nazwy
            full = name if "." in name or not ns2 else f"{ns2}.{name}"
            name = name.rsplit(".", 1)[-1]
            node = dict(s); self.named[full] = node; self.named[name] = node
            if t in ("record", "error"):
                node["_fields"] = [(f["name"], self._resolve(f["type"], ns2)) for f in s["fields"]]
            return node
        if t == "array":
            return {"type": "array", "items": self._resolve(s["items"], ns)}
        if t == "map":
            return {"type": "map", "values": self._resolve(s["values"], ns)}
        return self._resolve(t, ns)                   # {"type": "int"} itp.

    def read(self, buf, s):
        if isinstance(s, str):
            if s == "null": return None
            if s == "boolean": return buf.read(1) != b"\x00"
            if s in ("int", "long"): return buf.long()
            if s == "float": return buf.float()
            if s == "double": return buf.double()
            if s == "bytes": return buf.read(buf.long())
            if s == "string": return buf.read(buf.long()).decode("utf-8", "replace")
            raise ValueError(s)
        t = s["type"]
        if t in ("record", "error"):
            return {name: self.read(buf, fs) for name, fs in s["_fields"]}
        if t == "enum": return s["symbols"][buf.long()]
        if t == "fixed": return buf.read(s["size"])
        if t == "union": return self.read(buf, s["branches"][buf.long()])
        if t == "array":
            out, it = [], s["items"]
            while True:
                n = buf.long()
                if n == 0: break
                if n < 0: n = -n; buf.long()          # blok z rozmiarem w bajtach
                if it in ("int", "long"):
                    out.extend(_long_array(buf, n))
                elif it == "float":
                    out.extend(struct.unpack_from(f"<{n}f", buf.b, buf.p)); buf.p += 4 * n
                elif it == "double":
                    out.extend(struct.unpack_from(f"<{n}d", buf.b, buf.p)); buf.p += 8 * n
                else:
                    out.extend(self.read(buf, it) for _ in range(n))
            return out
        if t == "map":
            out = {}
            while True:
                n = buf.long()
                if n == 0: break
                if n < 0: n = -n; buf.long()
                for _ in range(n):
                    k = buf.read(buf.long()).decode(); out[k] = self.read(buf, s["values"])
            return out
        raise ValueError(f"nieobsługiwany typ Avro: {t}")


def read_avro(path):
    """Zwraca listę rekordów (dict) z pliku Avro."""
    data = open(path, "rb").read()
    if data[:4] != b"Obj\x01":
        raise ValueError(f"{path}: to nie jest plik Avro")
    buf = _Buf(data); buf.p = 4
    meta = _Decoder({"type": "map", "values": "bytes"}).read(buf, {"type": "map", "values": "bytes"})
    schema = json.loads(meta["avro.schema"].decode())
    codec = meta.get("avro.codec", b"null").decode()
    sync = buf.read(16)
    dec = _Decoder(schema); out = []
    while buf.p < len(data):
        count = buf.long(); size = buf.long()
        block = buf.read(size)
        if codec == "deflate": block = zlib.decompress(block, -15)
        elif codec != "null": raise ValueError(f"kodek Avro '{codec}' nieobsługiwany")
        bb = _Buf(block)
        for _ in range(count):
            out.append(dec.read(bb, dec.root))
        if buf.read(16) != sync:
            raise ValueError(f"{path}: uszkodzony plik (zły znacznik synchronizacji)")
    return out
