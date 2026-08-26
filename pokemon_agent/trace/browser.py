"""把 trace 事件推给浏览器的那个小服务：一个 HTTP server + 一条 SSE 通道。

只做两件事：发一张静态页面，和把新事件顺着 SSE 推出去。**它不认识 `TracePort`**，
`MockTrace.sse()` 调它，反过来不成立——观测台坏了不该影响这一局跑不跑得下去。

断线重连靠 `event_id` 补发，所以这里对事件顺序的唯一要求就是 id 单调，
而那是 `TracePort.append` 的后置条件，不是这一层的事。
"""


from __future__ import annotations

import queue
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pokemon_agent.schemas.trace import EventType, TraceEvent


_SHARED: "BrowserTraceServer | None" = None


def shared_server() -> "BrowserTraceServer":
    """整个进程共用的那一台观测台。**端口是进程级资源，服务也该是。**

    `BrowserTraceServer.__init__` 就地 `bind` 到固定端口 8765。一个进程里跑第二局
    （`run_experiment --repeat`、或任何连着建两次会话的流程）时再 new 一台，
    在 Linux 上会直接 `EADDRINUSE`，而在 **Windows 上更坏**：`allow_reuse_address`
    让第二次 bind **也成功**，于是同一个端口上有两台服务，浏览器那个标签页还挂在
    第一台的 SSE 连接上——**第二局的事件全推给了第二台，页面从此一个字都不再更新**。
    症状是"第二次循环浏览器就没信息了"，而日志和落盘一切正常。

    共用一台之后，一个进程里跑多少局，都推进同一条 SSE，标签页不用重开。
    每局开头由页面打一条 RUN 分隔线区分。

    **这是有意的进程级单例**：端口只有一个，谁先拿到谁就是它。
    """
    global _SHARED
    if _SHARED is None:
        _SHARED = BrowserTraceServer()
        _SHARED.start()
    return _SHARED


class BrowserTraceServer:

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """起一个本地端口，备好事件队列。"""
        self._clients: list[queue.Queue[str]] = []
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                """按路径分发：要页面就发页面，要事件流就挂一条 SSE 长连接。"""
                if self.path == "/events":
                    owner._serve_events(self)
                    return
                self._serve_page()

            def _serve_page(self) -> None:
                """把静态页面写回响应。"""
                body = owner.page().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                """吞掉 http.server 默认的请求日志，别刷屏。"""
                return

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        """观测台的访问地址。"""
        return f"http://{self._server.server_address[0]}:{self._server.server_address[1]}"

    def start(self, open_browser: bool = True) -> None:
        """在后台线程里把服务跑起来。"""
        self._thread.start()
        if open_browser:
            webbrowser.open(self.url)

    def close(self) -> None:
        """停掉服务，断开还连着的浏览器。"""
        self._server.shutdown()
        self._server.server_close()

    def publish(self, event: TraceEvent) -> None:
        """把一条事件放进推流队列。"""
        message = f"data: {event.model_dump_json()}\n\n"
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            client.put_nowait(message)

    def _serve_events(self, handler: BaseHTTPRequestHandler) -> None:
        """维持一条 SSE 长连接，把队列里的事件源源推出去。"""
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
        """观测台那张静态页面的 HTML。"""
        return """<!doctype html>
<meta charset="utf-8"><title>Pokemon Agent Trace</title>
<style>body{background:#111;color:#ddd;font:15px ui-monospace,monospace;margin:24px}
#log{white-space:pre-wrap;max-width:1000px}.step{color:#7dd3fc;margin-top:18px}
.phase{color:#fbbf24;margin-top:8px}.control{color:#888}</style>
<div id="log"></div><script>
const log=document.querySelector('#log'); let current=''; let currentRun='';
// inspect 还留着：功能已经删了，但旧的 trace 文件里有这类事件，回放要看得见。
const info=new Set(['observe','memory_read','think','act','inspect','memory_write']);
function line(s, cls=''){const e=document.createElement('div');e.textContent=s;e.className=cls;log.append(e)}
function render(e){
  if(!info.has(e.type)) return;
  // 一个进程可以连着跑好几局（--repeat），它们推的是同一条 SSE。
  // 没有这条分隔线的话，第二局的 STEP 0 直接接在第一局的 STEP 12 后面。
  if(e.run_id&&e.run_id!==currentRun){currentRun=e.run_id;line('===== RUN '+e.run_id+' =====','step')}
  const key=e.episode_id+':'+e.step;
  if(key!==current){current=key;line('----- STEP '+e.step+' -----','step')}
  line('--- '+e.phase.toUpperCase()+' ---','phase');
  const p=e.payload||{};
  if(e.type==='observe'){
    let facts={};
    try{facts=JSON.parse(p.facts||'{}')}catch(_error){}
    line('观察：'+(p.status||p.summary||''));
    line('  scene       = '+(p.scene||facts.scene||'(无)'));
    line('  overlay     = '+(p.overlay||facts.overlay||'(无)'));
    // overview 是视觉模型写的那一整段；status 只是 scene+overlay 拼的一行。
    // 以前这里只印 status，等于把这一帧真正被看到的东西藏了起来。
    if(facts.overview) line('  overview    = '+facts.overview);
    if(facts.dialog_text) line('  dialog      = 「'+facts.dialog_text+'」');
    if(facts.where) line('  where       = '+facts.where
        +(facts.facing?('  朝向 '+facts.facing):'  朝向 ?'));
    if(facts.neighbors) line('  neighbors   = '+facts.neighbors);
    if(facts.landmarks) line('  landmarks   = '+facts.landmarks);
    // walk_map 逐行打，别指望 pre-wrap：它一行 10 个字符、行首带 y=，
    // 挤成一段之后**看不出形状**，而这张图的全部用处就是看形状。
    //
    // **换行符写成 \\n（两个反斜杠）。** 这段 JS 住在 Python 的三引号字符串里，
    // 写 \\n 的话 Python 会把它变成一个真换行，JS 字符串就断成两行、整个 script
    // 语法错误——症状是观测台**一个字都不显示**，而不是这一块出问题。
    if(facts.walk_map){
      const rows=facts.walk_map.split('\\n');
      line('  walk_map    = '+rows[0]);
      for(let i=1;i<rows.length;i++) line('                '+rows[i]);
    } else line('  walk_map    = (无)');
  }
  else if(e.type==='memory_read'){
    line('记忆：');
    line('  step_memory   = '+(p.step_memory_count||p.count||0));
    line('  known_object  = '+(p.known_objects_text?('共 '+(p.known_object_count||'?')+' 条'):'(无)'));
    if(p.known_objects_text) line(p.known_objects_text.replace(/^/gm,'    '));
    line('  knowledge     = '+(p.knowledge_sources||'(无)'));
    line('  episode_level = '+(p.episode_level_count||0));
  }
  else if(e.type==='think') line('思考：'+(p.thought||''));
  else if(e.type==='act'){
    const chain=(p.segment_count&&p.segment_count!=='1')
      ?'  ('+p.segment_count+' 段 / '+(p.press_count||'?')+' 次按键)':'';
    line('行动：'+(p.action||'')+chain);
  }
  else if(e.type==='inspect') line('细看：'+(p.answer||''));
  else line('记忆写入');
}
new EventSource('/events').onmessage=e=>render(JSON.parse(e.data));
</script>"""
