"""pgshim.py - PENGGANTI TES untuk psycopg2: menjalankan SQL sungguhan di PostgreSQL lewat proses `psql` yang persisten.
Hanya untuk sandbox tanpa driver psycopg2. Bukan bagian aplikasi. Mendukung: execute(sql, params) dengan %s, fetchone/fetchall,
transaksi (BEGIN/COMMIT/ROLLBACK), execute_values, dan Json. Hasil SELECT/WITH dibungkus row_to_json (tipe dasar JSON)."""
import json
import re
import subprocess
from datetime import date, datetime
from contextlib import contextmanager

_ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?([+-]\d\d(:\d\d)?)$")


class JsonLit:
    def __init__(self, obj):
        self.obj = obj


def lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return "'NaN'::float8" if v != v else repr(v)
    if isinstance(v, datetime):
        assert v.tzinfo is not None, "datetime tanpa zona tidak dipakai di jalur DB"
        return "'" + v.isoformat() + "'::timestamptz"
    if isinstance(v, JsonLit):
        return "'" + json.dumps(v.obj, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    if isinstance(v, dict):
        return lit(JsonLit(v))
    if isinstance(v, (list, tuple, set, frozenset)):
        return "ARRAY[" + ",".join(lit(x) for x in v) + "]" if v else "'{}'"
    return "'" + str(v).replace("'", "''") + "'"


def _fill(sql, params):
    parts = sql.split("%s")
    assert len(parts) - 1 == len(params), f"jumlah %s ({len(parts) - 1}) != parameter ({len(params)})"
    return parts[0] + "".join(lit(p) + parts[i + 1] for i, p in enumerate(params))


def _decode(x):
    if isinstance(x, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", x):
        return date.fromisoformat(x)
    if isinstance(x, str) and _ISO.match(x):
        return datetime.fromisoformat(x if len(x) < 26 or x[-3] == ":" else x)
    if isinstance(x, dict):
        return {k: _decode(v) if not isinstance(v, (dict, list)) else v for k, v in x.items()}
    return x


class Psql:
    def __init__(self, args):
        self.p = subprocess.Popen(["psql", *args, "-X", "-q", "-At"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1)

    def run(self, sql: str) -> str:
        self.p.stdin.write(sql.rstrip().rstrip(";") + ";\n\\echo __END__\n")
        self.p.stdin.flush()
        out = []
        while True:
            line = self.p.stdout.readline()
            if line == "" or line.strip() == "__END__":
                break
            out.append(line.rstrip("\n"))
        text = "\n".join(out)
        if re.search(r"^(psql:.*)?ERROR:", text, re.M):
            raise RuntimeError(text)
        return text

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


class Cursor:
    def __init__(self, ps):
        self.ps, self.rows = ps, []
        self.description = None

    def execute(self, sql, params=()):
        s = _fill(sql, tuple(params))
        if re.match(r"\s*(SELECT|WITH)\b", s, re.I):
            out = self.ps.run("SELECT coalesce(json_agg(row_to_json(t)), '[]'::json) FROM (" + s.rstrip().rstrip(";") + ") t")
            self.rows = [{k: _decode(v) for k, v in r.items()} for r in json.loads(out)]
            self.description = True
        elif re.search(r"\bRETURNING\b", s, re.I):
            cols = [c.strip().split(" ")[-1] for c in re.search(r"RETURNING\s+(.+?);?\s*$", s, re.I | re.S).group(1).split(",")]
            text = self.ps.run(s)
            conv = lambda v: int(v) if re.fullmatch(r"-?\d+", v) else (float(v) if re.fullmatch(r"-?\d+\.\d+", v) else v)
            self.rows = [dict(zip(cols, (conv(x) for x in line.split("|")))) for line in text.splitlines() if line]
            self.description = True
        else:
            self.ps.run(s)
            self.rows, self.description = [], None

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class Shim:
    def __init__(self, args):
        self.ps = Psql(args)

    def db_query(self, sql, params=()):
        c = Cursor(self.ps)
        c.execute(sql, params)
        return c.fetchall() if c.description else []

    @contextmanager
    def transaction(self):
        self.ps.run("BEGIN")
        try:
            yield Cursor(self.ps)
        except BaseException:
            self.ps.run("ROLLBACK")
            raise
        else:
            self.ps.run("COMMIT")

    def execute_values(self, sql, rows, page_size=500):
        if not rows:
            return 0
        vals = ",".join("(" + ",".join(lit(x) for x in r) + ")" for r in rows)
        self.ps.run(sql.replace("%s", vals))
        return len(rows)

    def close(self):
        self.ps.close()

    def reset_schema(self):
        import schema
        self.ps.run("DROP SCHEMA public CASCADE")
        self.ps.run("CREATE SCHEMA public")
        for st in schema.ALL_STATEMENTS:
            self.ps.run(st)
