"""最小本地 SSE 观测台：只负责把 trace 事件推给一个浏览器页面。"""

from __future__ import annotations

import queue
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pokemon_agent.schemas.trace import EventType, TraceEvent


class BrowserTraceServer:
    """后台运行的单页 SSE 服务；没有浏览器连接时事件仍会被直接丢弃。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self._clients: list[queue.Queue[str]] = []
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/events":
                    owner._serve_events(self)
                    return
                self._serve_page()

            def _serve_page(self) -> None:
                body = owner.page().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://{self._server.server_address[0]}:{self._server.server_address[1]}"

    def start(self, open_browser: bool = True) -> None:
        self._thread.start()
        if open_browser:
            webbrowser.open(self.url)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def publish(self, event: TraceEvent) -> None:
        message = f"data: {event.model_dump_json()}\n\n"
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            client.put_nowait(message)

    def _serve_events(self, handler: BaseHTTPRequestHandler) -> None:
        client: queue.Queue[str] = queue.Queue()
        with self._lock:
            self._clients.append(client)
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "keep-alive")
        handler.end_headers()
        try:
            while True:
                handler.wfile.write(client.get().encode("utf-8"))
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with self._lock:
                if client in self._clients:
                    self._clients.remove(client)

    @staticmethod
    def page() -> str:
        return """<!doctype html>
<meta charset="utf-8"><title>Pokemon Agent Trace</title>
<style>body{background:#111;color:#ddd;font:15px ui-monospace,monospace;margin:24px}
#log{white-space:pre-wrap;max-width:1000px}.step{color:#7dd3fc;margin-top:18px}
.phase{color:#fbbf24;margin-top:8px}.control{color:#888}</style>
<div id="log"></div><script>
const log=document.querySelector('#log'); let current='';
const info=new Set(['observe','memory_read','think','act','inspect','memory_write']);
function line(s, cls=''){const e=document.createElement('div');e.textContent=s;e.className=cls;log.append(e)}
function render(e){
  if(!info.has(e.type)) return;
  const key=e.episode_id+':'+e.step;
  if(key!==current){current=key;line('----- STEP '+e.step+' -----','step')}
  line('--- '+e.phase.toUpperCase()+' ---','phase');
  const p=e.payload||{};
  if(e.type==='observe'){
    let facts={};
    try{facts=JSON.parse(p.facts||'{}')}catch(_error){}
    line('观察：'+(p.summary||''));
    line('  scene       = '+(p.scene||facts.scene||'(无)'));
    line('  overlay     = '+(p.overlay||facts.overlay||'(无)'));
    line('  walk_map    = '+(facts.walk_map||'(无)'));
  }
  else if(e.type==='memory_read'){
    line('记忆：');
    line('  step_memory   = '+(p.step_memory_count||p.count||0));
    line('  known_object  = '+(p.known_object_names||'(无)'));
    line('  knowledge     = '+(p.knowledge_sources||'(无)'));
    line('  episode_level = '+(p.episode_level_count||0));
  }
  else if(e.type==='think') line('思考：'+(p.thought||''));
  else if(e.type==='act') line('行动：'+(p.action||'')+' '+(p.message||''));
  else if(e.type==='inspect') line('细看：'+(p.answer||''));
  else line('记忆写入');
}
new EventSource('/events').onmessage=e=>render(JSON.parse(e.data));
</script>"""
