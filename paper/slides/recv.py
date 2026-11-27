"""Tiny local receiver for browser-captured frames: POST {name, i, img (data URL), meta} -> frames/<name>/NNN.jpg + meta.jsonl (localhost only)."""
import base64, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
OUT = Path("C:/urbanscenariogenerator/usg/paper/slides/frames")

class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "*"); self.send_header("Access-Control-Allow-Methods", "POST,OPTIONS")
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); d = json.loads(self.rfile.read(n))
        if d.get("reset"):
            import shutil; shutil.rmtree(OUT / d["name"], ignore_errors=True)
        else:
            p = OUT / d["name"]; p.mkdir(parents=True, exist_ok=True)
            (p / f"{d['i']:04d}.jpg").write_bytes(base64.b64decode(d["img"].split(",", 1)[1]))
            with open(p / "meta.jsonl", "a", encoding="utf8") as f: f.write(json.dumps({"i": d["i"], **d["meta"]}) + "\n")
        self.send_response(200); self._cors(); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

HTTPServer(("127.0.0.1", 7871), H).serve_forever()
