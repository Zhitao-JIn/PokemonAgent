/** 用当前筛选、原标注和草稿渲染页面；所有外来字符串均转义。 */
function renderFilters(): void {
  for (const [id, key] of [['scene-filter', 'scene'], ['overlay-filter', 'overlay']] as const) {
    const values: string[] = [...new Set(bundle.frames.map((frame: ReviewFrame): string =>
      String(key === 'scene' ? frame.truth.scene_truth.scene : frame.truth.screen_truth.overlay)))].sort();
    element<HTMLSelectElement>(id).innerHTML += values.map((value: string): string =>
      `<option value="${escapeText(value)}">${escapeText(value)}</option>`).join('');
  }
}
function matchesFilters(frame: ReviewFrame): boolean {
  const search: string = element<HTMLInputElement>('search').value.trim().toLowerCase();
  const scene: string = element<HTMLSelectElement>('scene-filter').value;
  const overlay: string = element<HTMLSelectElement>('overlay-filter').value;
  const status: string = element<HTMLSelectElement>('status-filter').value;
  const group: string = element<HTMLSelectElement>('difference-filter').value;
  const differenceKeys: string[] = Object.keys(frame.differences);
  return (!search || JSON.stringify([frame.id, frame.truth, frame.note]).toLowerCase().includes(search)) &&
    (!scene || frame.truth.scene_truth.scene === scene) && (!overlay || frame.truth.screen_truth.overlay === overlay) &&
    (!status || draftFor(frame).status === status) && (!group || (group === 'any' ? differenceKeys.length > 0 :
      differenceKeys.some((path: string): boolean => path.startsWith(`${group}.`)))) &&
    (!element<HTMLInputElement>('boundary-filter').checked || Boolean(frame.warning)) &&
    (!element<HTMLInputElement>('cursor-mismatch-filter').checked || Boolean(frame.cursor_evidence?.mismatch));
}
function renderList(): void {
  filteredFrames = bundle.frames.filter(matchesFilters);
  element('list-count').textContent = `${filteredFrames.length} / ${bundle.frames.length} 帧`;
  element('frame-list').innerHTML = filteredFrames.map((frame: ReviewFrame): string => {
    const status: ReviewStatus = draftFor(frame).status;
    const count: number = Object.keys(frame.differences).length;
    return `<button class="frame-row ${frame.id === selectedId ? 'active' : ''}" data-frame="${escapeText(frame.id)}">
      <span class="status-dot ${status}" aria-label="${status}"></span><span class="frame-name">${escapeText(frame.id)}
      <small>${escapeText(String(frame.truth.scene_truth.scene))} · ${escapeText(String(frame.truth.screen_truth.overlay))}</small></span>
      ${count ? `<span class="diff-count">${count}</span>` : ''}${frame.warning ? '<span title="重点核对">!</span>' : ''}</button>`;
  }).join('') || '<p class="empty">没有符合筛选条件的帧。</p>';
  const counts: Record<ReviewStatus, number> = { pending: 0, approved: 0, issue: 0 };
  bundle.frames.forEach((frame: ReviewFrame): void => { counts[draftFor(frame).status] += 1; });
  element('progress').textContent = `待审 ${counts.pending} · 通过 ${counts.approved} · 有问题 ${counts.issue}`;
  element<HTMLProgressElement>('progress-bar').value = counts.approved + counts.issue;
  element<HTMLProgressElement>('progress-bar').max = bundle.frames.length;
}
function flattenFields(value: JsonValue, prefix: string): [string, JsonValue][] {
  if (value !== null && typeof value === 'object' && Object.keys(value).length > 0) {
    return Object.entries(value).flatMap(([key, child]: [string, JsonValue]): [string, JsonValue][] =>
      flattenFields(child, `${prefix}.${key}`));
  }
  return [[prefix, value]];
}
function renderFields(): void {
  const frame: ReviewFrame = currentFrame();
  const truth: Record<string, JsonValue> = truthFor(frame, selectedGroup);
  const groupKey: string = selectedGroup.replace('_truth', '');
  const fields: [string, JsonValue][] = Object.entries(truth).flatMap(([key, value]: [string, JsonValue]): [string, JsonValue][] =>
    key === 'view' && value !== null ? flattenFields(value, key) : [[key, value]]);
  element('field-count').textContent = `${fields.length} 个字段 / 成员`;
  element('fields').innerHTML = fields.map(([path, value]: [string, JsonValue]): string => {
    const key: string = path.split('.').at(-1)!;
    const changed: boolean = Object.keys(frame.differences).some((diff: string): boolean =>
      diff === `${groupKey}.${path}` || `${groupKey}.${path}`.startsWith(`${diff}.`));
    return `<tr class="${changed ? 'different' : ''}"><td><code>${escapeText(path)}</code>
      <small>${escapeText(EXPLANATIONS[key] ?? '')}</small></td>
      <td><pre>${escapeText(path === 'screen' ? '见左侧「整屏文字参考」' : displayValue(value))}</pre>${changed ? '<span class="diff-label">原始诊断有差异，见下方对照</span>' : ''}</td></tr>`;
  }).join('');
  element('not-applicable').hidden = fields.length > 0;
  element<HTMLTextAreaElement>('json-editor').value = JSON.stringify(truth, null, 2);
  element<HTMLDetailsElement>('editor-panel').open = false;
  editorDirty = false;
  const approvedNow: boolean = draftFor(frame).approved_groups.includes(selectedGroup);
  element<HTMLButtonElement>('approve-group').textContent = approvedNow ? '撤回本组通过' : '通过本组';
  element<HTMLButtonElement>('approve-group').disabled = fields.length === 0;
  document.querySelectorAll<HTMLButtonElement>('[data-group]').forEach((button: HTMLButtonElement): void => {
    const group: TruthGroup = button.dataset.group as TruthGroup;
    button.classList.toggle('active', group === selectedGroup);
    button.classList.toggle('approved-tab', draftFor(frame).approved_groups.includes(group));
  });
}
function renderDifferences(): void {
  const frame: ReviewFrame = currentFrame();
  const entries: [string, { expected: JsonValue; actual: JsonValue }][] = Object.entries(frame.differences);
  element('difference-title').textContent = `解码差异对照（${entries.length} 项）`;
  element('differences').innerHTML = entries.map(([path, value]): string =>
    `<article class="difference"><code>${escapeText(path)}</code><div class="comparison"><section><small>原始候选标注</small>
      <pre>${escapeText(displayValue(value.expected))}</pre></section><section><small>被测 decoder 输出</small>
      <pre>${escapeText(displayValue(value.actual))}</pre></section></div></article>`).join('') ||
      '<p class="empty">本次诊断没有记录差异；仍需核对标注。相符不代表已经审核。</p>';
}
function renderFrame(): void {
  const frame: ReviewFrame = currentFrame();
  element('frame-title').textContent = frame.id;
  element('frame-meta').textContent = `${String(frame.truth.scene_truth.scene)} · ${String(frame.truth.screen_truth.overlay)} · 来源 ${frame.source}`;
  element<HTMLImageElement>('screenshot').src = frame.image;
  element<HTMLImageElement>('screenshot').alt = `冻结截图 ${frame.id}`;
  element('reference-screen').textContent = String(truthFor(frame, 'screen_truth').screen || '（无可渲染文字）');
  element('raw-tiles').textContent = frame.tiles.map((row: number[]): string =>
    row.map((tile: number): string => tile.toString(16).toUpperCase().padStart(2, '0')).join(' ')).join('\n');
  const cursorWarning: string = frame.cursor_evidence?.mismatch ?
    '截图与冻结 RAM 的实心光标证据不一致。此帧不能直接按截图审核 RAM 光标；请对照下方光标证据与 RAM 文字，或标记问题等待同步素材。' : '';
  element('warning').hidden = !frame.warning && !cursorWarning;
  element('warning').textContent = [frame.warning, cursorWarning].filter(Boolean).join(' ');
  element('source-note').textContent = `${frame.note}\n${frame.truth.note}`;
  element<HTMLTextAreaElement>('review-note').value = draftFor(frame).note;
  const status: ReviewStatus = draftFor(frame).status;
  element('frame-status').textContent = { pending: '待审核', approved: '本次整帧通过', issue: '本次标记有问题' }[status];
  element('frame-status').className = `pill ${status}`;
  renderFields();
  renderDifferences();
  renderCursorEvidence(frame);
}
function renderCursorEvidence(frame: ReviewFrame): void {
  const evidence: ReviewFrame['cursor_evidence'] = frame.cursor_evidence;
  element('cursor-evidence').hidden = !evidence;
  element('image-cursors').innerHTML = '';
  if (!evidence) return;
  const coordinates = (values: [number, number][]): string => values.length ?
    values.map(([row, col]: [number, number]): string => `行 ${row} / 列 ${col}`).join('；') : '未检出实心箭头';
  element('image-cursor-value').textContent = coordinates(evidence.image);
  element('ram-cursor-value').textContent = coordinates(evidence.ram);
  element('candidate-cursor-value').textContent = String(truthFor(frame, 'screen_truth').cursor || '空字符串（无当前选项）');
  element('cursor-match').textContent = evidence.mismatch ? '截图 / RAM 光标不一致' : '箭头位置一致；不代表整屏同步';
  element('cursor-match').className = `pill ${evidence.mismatch ? 'issue' : ''}`;
  element('image-cursors').innerHTML = evidence.image.map(([row, col]: [number, number]): string =>
    `<span class="cursor-ring" style="left:${col * 5}%;top:${row * 100 / 18}%;width:5%;height:${100 / 18}%" title="截图实心箭头：${row}, ${col}"></span>`).join('');
}
function moveFrame(direction: number, unreviewed: boolean = false): void {
  if (!leaveEditor()) return;
  const start: number = filteredFrames.findIndex((frame: ReviewFrame): boolean => frame.id === selectedId);
  let target: number = start + direction;
  while (target >= 0 && target < filteredFrames.length) {
    if (!unreviewed || draftFor(filteredFrames[target]).status === 'pending') {
      selectedId = filteredFrames[target].id;
      renderList(); renderFrame();
      document.querySelector('.frame-row.active')?.scrollIntoView({ block: 'nearest' });
      return;
    }
    target += direction;
  }
  notify('当前筛选范围内没有更多符合条件的帧。');
}
