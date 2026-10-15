"""`PAGE_HTML`：后端 `GET /` 吐出的单页——人在这里答插话与审。

页面只认跳 B 的几封消息（`msg` 标签分流）；所有文本都经 `textContent` 放进页面。
它认得 trace 事件的形状（`kind`、`meta`、`content.frame`）——实时画面与时间线靠它，
问人时按被审对象挑出首末帧。
连上 `/ui` 后由后端推送，断线按退避自动重连（重连后后端补发历史与待答）。

**Agent Reviewer 叠加层（A4）**：后端连了 agent（`ask.deadline != null`）时，待答卡片顶部出现
「AI 接管 / 我来处理」开关与「AI 复核席」面板（结论框 + 聊天栏 + 发给 AI）。前端不感知 agent
存在——它只收 `proposal` 推送、发 `discuss`，计时与提交由本页按模式自管。
"""

from __future__ import annotations

PAGE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pokemon Agent · 人在环</title>
<style>
  :root {
    --bg: #f6f7f9; --panel: #ffffff; --ink: #1d2330; --muted: #667085; --line: #e3e6eb;
    --accent: #2f6fdf; --ok: #1f8a4c; --warn: #b54708; --bad: #c0362c; --code: #f2f4f7;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #12151b; --panel: #1b2029; --ink: #e6e9ef; --muted: #98a2b3; --line: #2a303b;
      --accent: #6d9cf2; --ok: #4cc38a; --warn: #f0a24b; --bad: #f07167; --code: #151a21;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 15px/1.55 system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }
  header { display: flex; align-items: center; gap: 12px; padding: 12px 20px;
           border-bottom: 1px solid var(--line); background: var(--panel); }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  #status { font-size: 13px; color: var(--muted); }
  #status.on::before { content: "● "; color: var(--ok); }
  #status.off::before { content: "● "; color: var(--bad); }
  main { max-width: 980px; margin: 0 auto; padding: 20px 16px 40px; display: grid; gap: 20px; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
          padding: 16px 18px; }
  .card h2 { margin: 0 0 4px; font-size: 17px; }
  .meta { color: var(--muted); font-size: 13px; }
  .tag { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px;
         border: 1px solid var(--line); margin-right: 6px; }
  .tag.inject { color: var(--accent); border-color: var(--accent); }
  .tag.audit { color: var(--warn); border-color: var(--warn); }
  pre { background: var(--code); border: 1px solid var(--line); border-radius: 8px;
        padding: 10px 12px; white-space: pre-wrap; word-break: break-word;
        max-height: 50vh; overflow: auto; margin: 12px 0;
        font: 13px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; }
  details summary { cursor: pointer; color: var(--muted); font-size: 13px; }
  details ol { font: 12px/1.5 ui-monospace, Consolas, monospace; max-height: 40vh; overflow: auto;
               padding-left: 22px; }
  textarea, input[type=text] { width: 100%; padding: 8px 10px; border-radius: 8px;
                               border: 1px solid var(--line); background: var(--bg);
                               color: var(--ink); font: inherit; }
  textarea { min-height: 72px; resize: vertical; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; align-items: center; }
  button { padding: 7px 16px; border-radius: 8px; border: 1px solid var(--line);
           background: var(--panel); color: var(--ink); font: inherit; cursor: pointer; }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button.danger { color: var(--bad); border-color: var(--bad); }
  button:disabled { opacity: .5; cursor: default; }
  #inject-ctl, #audit-ctl { margin-top: 12px; }
  #error { color: var(--bad); font-size: 13px; min-height: 1em; margin-top: 6px; }
  .empty { color: var(--muted); }
  #history { list-style: none; margin: 0; padding: 0; }
  #history li { padding: 8px 0; border-top: 1px solid var(--line); font-size: 14px; }
  #history li:first-child { border-top: 0; }
  .by-human { color: var(--ok); }
  .by-timeout { color: var(--muted); }
  .by-harness_gone { color: var(--bad); }
  .by-agent { color: var(--accent); }
  .modes { display: flex; gap: 8px; margin: 2px 0 12px; }
  .modes button { flex: 1; }
  .modes button.active { background: var(--accent); border-color: var(--accent); color: #fff; }
  #agent-ctl { margin-top: 14px; border-top: 1px dashed var(--line); padding-top: 12px; }
  #agent-ctl h3 { margin: 0 0 6px; font-size: 14px; font-weight: 600; }
  #chat { list-style: none; margin: 10px 0 0; padding: 0; max-height: 180px; overflow: auto;
          font: 13px/1.5 system-ui, sans-serif; }
  #chat li { padding: 5px 0; border-top: 1px solid var(--line); }
  #chat li:first-child { border-top: 0; }
  #chat .who { font-weight: 600; }
  #chat .ai .who { color: var(--accent); }
  #chat .me .who { color: var(--ok); }
  #countdown-ai { margin-left: auto; color: var(--muted); font-size: 13px; }
  .frames, .live { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
  figure { margin: 0; }
  figure img { width: 320px; max-width: 100%; image-rendering: pixelated;
               border: 1px solid var(--line); border-radius: 6px; background: #000; }
  figcaption { color: var(--muted); font-size: 12px; margin-top: 4px; }
  #timeline { flex: 1; min-width: 260px; max-height: 300px; overflow: auto; margin: 0;
              padding-left: 20px; font: 12px/1.6 ui-monospace, Consolas, monospace; }
</style>
</head>
<body>
<header><h1>人在环</h1><span id="status" class="off">未连接</span></header>
<main>
  <section class="card" id="ask">
    <p class="empty" id="idle">现在没有待答的问题。run 问到人时会自动出现在这里。</p>
    <div id="current" hidden>
      <div class="modes">
        <button id="mode-ai">AI 接管</button>
        <button id="mode-human">我来处理</button>
      </div>
      <div class="meta"><span id="kind" class="tag"></span><span id="where"></span></div>
      <h2 id="prompt"></h2>
      <pre id="body"></pre>
      <div id="ask-frames" class="frames" hidden>
        <figure><img id="first-frame" alt="首帧"><figcaption>首帧</figcaption></figure>
        <figure><img id="last-frame" alt="末帧"><figcaption>末帧</figcaption></figure>
      </div>
      <details id="events-box" hidden>
        <summary id="events-title"></summary><ol id="events"></ol>
      </details>
      <div id="inject-ctl" hidden>
        <textarea id="text"
          placeholder="有意见就写一句，模型会带着它重答；没有就点「没意见」"></textarea>
        <div class="row">
          <button class="primary" id="send-text">提交意见</button>
          <button id="no-opinion">没意见</button>
        </div>
      </div>
      <div id="audit-ctl" hidden>
        <input type="text" id="note" placeholder="推翻时写理由（下一次规划 / 拆解会看到）">
        <div class="row">
          <button class="primary" id="accept">认账</button>
          <button class="danger" id="overturn">推翻</button>
        </div>
      </div>
      <div id="agent-ctl" hidden>
        <h3>AI 复核席</h3>
        <textarea id="conclusion"
          placeholder="AI 提案会出现在这里；可改后「发给 AI」，或切「我来处理」自己答。"></textarea>
        <ol id="chat"></ol>
        <div class="row">
          <button id="send-ai">发给 AI</button>
          <span id="countdown-ai"></span>
        </div>
      </div>
      <div id="error"></div>
    </div>
  </section>
  <section class="card">
    <h2>实时</h2>
    <div class="live">
      <figure>
        <img id="live-frame" alt="当前画面" hidden>
        <figcaption id="live-caption">还没有画面（run 带 --review 起跑后会实时推过来）</figcaption>
      </figure>
      <ol id="timeline" reversed></ol>
    </div>
  </section>
  <section class="card">
    <h2>历史</h2>
    <ul id="history"><li class="empty" id="no-history">还没有问过。</li></ul>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
const asks = new Map();
const feed = [];
const FEED_KEEP = 300, TIMELINE_KEEP = 80, AI_COUNTDOWN = 30;
let ws = null, retry = 0, current = null, aiTimer = null;
let mode = 'human', locked = false, proposal = null;

function connect() {
  ws = new WebSocket(`ws://${location.host}/ui`);
  ws.onopen = () => {
    retry = 0; setStatus(true);
    $('history').replaceChildren($('no-history') || emptyHistory());
  };
  ws.onclose = () => {
    setStatus(false); show(null);
    setTimeout(connect, Math.min(1000 * 2 ** retry++, 10000));
  };
  ws.onmessage = (event) => {
    const m = JSON.parse(event.data);
    if (m.msg === 'feed') onFeed(m.event);
    else if (m.msg === 'ask') { asks.set(m.seq, m); show(m); }
    else if (m.msg === 'settle') settle(m);
    else if (m.msg === 'proposal') onProposal(m);
    else if (m.msg === 'answer_ack' && !m.ok && current && current.seq === m.seq) {
      $('error').textContent = `没被采纳：${m.reason}`; enable(false);
    }
  };
}

function parse(text) {
  try { return JSON.parse(text) || {}; } catch (err) { return {}; }
}

function onFeed(event) {
  const item = { kind: event.kind, ended_at: event.ended_at, meta: parse(event.meta),
                 content: parse(event.content) };
  feed.push(item);
  if (feed.length > FEED_KEEP) feed.shift();
  if (item.content.frame) {
    const img = $('live-frame');
    // `content.frame` 是**完整 data URI**（`data:image/png;base64,…`，0915 起全仓唯一
    // 帧格式，编码点 `world/frame_encoding.py::png_data_uri`）——直接上 src，别再拼前缀。
    img.src = item.content.frame; img.hidden = false;
    const m = item.meta;
    $('live-caption').textContent = `${m.episode_id || ''} · ${m.task_id || ''} · 第 ${m.step} 步`;
  }
  const li = document.createElement('li');
  const clock = new Date(item.ended_at * 1000).toLocaleTimeString();
  li.textContent = `${clock} · ${item.kind} · ${item.meta.source || '-'} · ${item.meta.step}`;
  $('timeline').prepend(li);
  while ($('timeline').children.length > TIMELINE_KEEP) $('timeline').lastChild.remove();
}

function framesOf(m) {
  if (m.kind !== 'audit') return [];
  return feed.filter((i) => i.content.frame && (m.task_id
    ? i.meta.task_id === m.task_id
    : m.form_kind === 'EpisodeOutput' && i.meta.episode_id === m.episode_id));
}

function setStatus(on) {
  $('status').className = on ? 'on' : 'off';
  $('status').textContent = on ? '已连接后端' : '未连接，正在重连…';
}

function emptyHistory() {
  const li = document.createElement('li');
  li.id = 'no-history'; li.className = 'empty'; li.textContent = '还没有问过。';
  return li;
}

function show(m) {
  current = m; locked = false; proposal = null;
  clearInterval(aiTimer); aiTimer = null;
  $('idle').hidden = !!m; $('current').hidden = !m;
  if (!m) return;
  const inject = m.kind === 'inject';
  $('kind').textContent = inject ? '插话' : '审';
  $('kind').className = `tag ${m.kind}`;
  const where = [m.run_id, m.episode_id].filter(Boolean).join(' · ');
  $('where').textContent = `第 ${m.seq} 问 · ${where}${m.form_kind ? ' · ' + m.form_kind : ''}`;
  $('prompt').textContent = m.prompt;
  $('body').textContent = m.body;
  $('events-box').hidden = !m.events.length;
  $('events-title').textContent = `被审对象的事件（${m.events.length} 条）`;
  $('events').replaceChildren(...m.events.map((line) => {
    const li = document.createElement('li'); li.textContent = line; return li;
  }));
  const frames = framesOf(m);
  $('ask-frames').hidden = !frames.length;
  if (frames.length) {
    $('first-frame').src = frames[0].content.frame;
    $('last-frame').src = frames[frames.length - 1].content.frame;
  }
  $('inject-ctl').hidden = !inject; $('audit-ctl').hidden = inject;
  // Agent 面板：仅当后端连了 agent（`deadline` 非 null）才出现；否则纯人路径（W5）。
  const hasAgent = m.deadline != null;
  $('agent-ctl').hidden = !hasAgent;
  $('conclusion').value = ''; $('chat').replaceChildren();
  if (hasAgent) {
    setMode('ai');
    $('countdown-ai').textContent = '等待 AI 提案…（或切「我来处理」自己答）';
  } else { setMode('human'); $('countdown-ai').textContent = ''; }
  $('text').value = ''; $('note').value = ''; $('error').textContent = '';
  enable(true);
}

function setMode(next) {
  mode = next;
  $('mode-ai').classList.toggle('active', mode === 'ai');
  $('mode-human').classList.toggle('active', mode === 'human');
  if (mode === 'human') {
    clearInterval(aiTimer); aiTimer = null; $('countdown-ai').textContent = '';
  }
}

function onProposal(pm) {
  if (!current || pm.seq !== current.seq) return;
  proposal = pm.proposal;
  // 结论框：round 0 首填；之后只在框还空时覆盖（保留人改过的稿）。
  if (pm.round === 0 || !$('conclusion').value) {
    $('conclusion').value = proposalText(pm.proposal);
  }
  const li = document.createElement('li');
  li.className = 'ai';
  const who = document.createElement('span');
  who.className = 'who';
  who.textContent = (pm.round === 0 ? 'AI 提案' : `AI 第 ${pm.round} 轮`) + '：';
  li.append(who, document.createTextNode(proposalText(pm.proposal)));
  $('chat').prepend(li);
  if (mode === 'ai') startAiTimer();
}

function proposalText(p) {
  if (p.verdict != null) {
    const v = p.verdict === 'overturn' ? '推翻' : '认账';
    return `${v}${p.note ? '：' + p.note : ''}`;
  }
  return p.text || '';
}

function startAiTimer() {
  clearInterval(aiTimer);
  let left = AI_COUNTDOWN;
  const tick = () => {
    if (left <= 0) { clearInterval(aiTimer); aiTimer = null; autoSubmitAI(); return; }
    $('countdown-ai').textContent = `${left}s 后自动提交 AI 提案`;
    left -= 1;
  };
  tick(); aiTimer = setInterval(tick, 1000);
}

function autoSubmitAI() {
  if (locked || !current) return;
  if (proposal && (current.kind === 'inject' || proposal.verdict != null)) {
    if (current.kind === 'inject') answer({ text: proposal.text ?? '', by: 'agent' });
    else answer({ verdict: proposal.verdict, note: proposal.note ?? '', by: 'agent' });
  } else {
    answer({ by: 'timeout' });
  }
}

function sendToAI() {
  if (!current || !ws || ws.readyState !== WebSocket.OPEN) return;
  const text = $('conclusion').value.trim();
  if (!text) return;
  ws.send(JSON.stringify({ msg: 'discuss', seq: current.seq, text }));
  const li = document.createElement('li');
  li.className = 'me';
  const who = document.createElement('span');
  who.className = 'who'; who.textContent = '你：';
  li.append(who, document.createTextNode(text));
  $('chat').prepend(li);
}

function enable(on) {
  for (const id of ['send-text', 'no-opinion', 'accept', 'overturn', 'send-ai']) {
    $(id).disabled = !on;
  }
}

function answer(payload) {
  if (locked || !current || !ws || ws.readyState !== WebSocket.OPEN) return;
  locked = true; clearInterval(aiTimer); aiTimer = null;
  enable(false);
  ws.send(JSON.stringify({ msg: 'answer', seq: current.seq, ...payload }));
}

function settle(m) {
  const ask = asks.get(m.seq);
  if (current && current.seq === m.seq) { clearInterval(aiTimer); aiTimer = null; show(null); }
  const none = $('no-history'); if (none) none.remove();
  const li = document.createElement('li');
  const by = { human: '人答了', timeout: '超时，按默认处理', harness_gone: 'run 断开，作废',
               agent: 'AI 答了' }[m.by];
  let said = '';
  if (m.verdict) said = m.verdict === 'overturn' ? `推翻${m.note ? '：' + m.note : ''}` : '认账';
  else said = m.text ? `意见：${m.text}` : '没意见';
  const head = document.createElement('div');
  head.textContent = `第 ${m.seq} 问 · ${ask ? ask.prompt : ''}`;
  const tail = document.createElement('div');
  tail.className = `meta by-${m.by}`; tail.textContent = `${by} · ${said}`;
  li.append(head, tail);
  $('history').prepend(li);
}

$('mode-ai').onclick = () => setMode('ai');
$('mode-human').onclick = () => setMode('human');
$('send-ai').onclick = sendToAI;
$('send-text').onclick = () => answer({ text: $('text').value.trim() });
$('no-opinion').onclick = () => answer({ text: '' });
$('accept').onclick = () => answer({ verdict: 'accept', note: '' });
$('overturn').onclick = () => answer({ verdict: 'overturn', note: $('note').value.trim() });
connect();
</script>
</body>
</html>
"""

__all__ = ["PAGE_HTML"]
