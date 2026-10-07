/** 保存、修订和导出本次审核；不会写入原始真值文件。 */
function leaveEditor(): boolean {
  return !editorDirty || window.confirm('本组 JSON 修改尚未保存。放弃这些未保存的修改并继续？');
}
function persistDrafts(): void {
  try {
    localStorage.setItem(cacheKey, JSON.stringify(drafts));
    notify('审核草稿已保存在此浏览器。请定期导出记录备份；原始 truth.jsonl 未修改。');
  } catch {
    notify('浏览器本地存储不可用：草稿暂存于当前页面，请立即导出备份。');
  }
}
function saveDraft(frame: ReviewFrame, update: Partial<ReviewDraft>): void {
  drafts[frame.id] = { ...draftFor(frame), ...update, updated_at: new Date().toISOString() };
  persistDrafts();
}
function setFrameStatus(status: ReviewStatus): void {
  if (!leaveEditor()) return;
  const frame: ReviewFrame = currentFrame();
  saveDraft(frame, { status, approved_groups: status === 'approved' ? applicableGroups(frame) : [] });
  renderList(); renderFrame();
}
function toggleGroup(): void {
  if (!leaveEditor()) return;
  const frame: ReviewFrame = currentFrame();
  const draft: ReviewDraft = draftFor(frame);
  const groups: TruthGroup[] = draft.approved_groups.includes(selectedGroup) ?
    draft.approved_groups.filter((group: TruthGroup): boolean => group !== selectedGroup) : [...draft.approved_groups, selectedGroup];
  const allApproved: boolean = applicableGroups(frame).every((group: TruthGroup): boolean => groups.includes(group));
  saveDraft(frame, { approved_groups: groups, status: allApproved ? 'approved' : draft.status === 'issue' ? 'issue' : 'pending' });
  renderList(); renderFields();
  element('frame-status').textContent = allApproved ? '本次整帧通过' : draftFor(frame).status === 'issue' ? '本次标记有问题' : '待审核';
  element('frame-status').className = `pill ${draftFor(frame).status}`;
}
function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function requireKeys(value: unknown, keys: string[], path: string): asserts value is Record<string, unknown> {
  if (!isObject(value)) throw new Error(`${path} 必须为对象。`);
  for (const key of keys) if (!(key in value)) throw new Error(`缺少 ${path}.${key}，不能把漏标当作空值。`);
}
function validateView(value: unknown): void {
  if (value === null) return;
  const schemas: Record<string, string[]> = {
    naming: ['target', 'typed'], shop_items: ['items', 'money', 'bag'],
    battle_menu: ['mine', 'foe', 'trainer', 'party', 'bag'], battle_switch: ['party'],
    bag: ['bag', 'party'], party: ['party'], pc: ['items', 'bag', 'box', 'box_number', 'party'],
    learn_move: ['pokemon', 'new_move', 'moves']
  };
  requireKeys(value, ['kind'], 'view');
  if (typeof value.kind !== 'string' || !schemas[value.kind]) throw new Error('view.kind 不是已知接管场合。');
  requireKeys(value, schemas[value.kind], 'view');
  for (const key of ['bag', 'items', 'box', 'party', 'moves']) {
    if (!(key in value)) continue;
    if (!Array.isArray(value[key])) throw new Error(`view.${key} 必须为数组。`);
    const entries: unknown[] = value[key];
    const fields: string[] = key === 'party' ? ['name', 'level', 'hp', 'max_hp', 'status', 'active', 'moves'] :
      ['name', key === 'box' ? 'level' : key === 'moves' ? 'pp' : key === 'items' && value.kind === 'shop_items' ? 'price' : 'quantity'];
    entries.forEach((entry: unknown, index: number): void => requireKeys(entry, fields, `view.${key}.${index}`));
  }
  const members: unknown[] = [...(Array.isArray(value.party) ? value.party : []), ...['mine', 'foe'].filter(
    (key: string): boolean => key in value).map((key: string): unknown => value[key])];
  members.forEach((member: unknown, index: number): void => {
    requireKeys(member, ['name', 'level', 'hp', 'max_hp', 'status', 'active', 'moves'], `宝可梦.${index}`);
    if (!Array.isArray(member.moves)) throw new Error('宝可梦 moves 必须为数组。');
    member.moves.forEach((move: unknown, slot: number): void => requireKeys(move, ['name', 'pp'], `招式.${slot}`));
  });
}
function validateEdit(group: TruthGroup, value: unknown, frame: ReviewFrame): asserts value is Record<string, JsonValue> {
  if (!isObject(value)) throw new Error('本组标注必须为 JSON 对象。');
  for (const key of Object.keys(value)) {
    if (!(key in frame.truth[group])) throw new Error(`${key} 不属于当前组的输出字段。`);
  }
  for (const [key, previous] of Object.entries(frame.truth[group])) {
    if (!(key in value)) throw new Error(`不能漏掉原字段 ${key}；内容不存在请填对应空值。`);
    const next: unknown = value[key];
    if (previous !== null && typeof previous !== 'object' && typeof next !== typeof previous) {
      throw new Error(`${key} 应保持 ${typeof previous} 类型。`);
    }
    if (Array.isArray(previous) && !Array.isArray(next)) throw new Error(`${key} 必须是数组。`);
  }
  if (group === 'scene_truth' && value.at_start !== null && typeof value.at_start !== 'boolean') {
    throw new Error('at_start 必须为 true、false 或 null。');
  }
  if (group === 'screen_truth' && !['none', 'dialog', 'choice'].includes(String(value.overlay))) {
    throw new Error('overlay 仅允许 none、dialog、choice。');
  }
  if (group === 'takeover_truth' && value.view !== null && !isObject(value.view)) {
    throw new Error('view 必须为对象或 null。');
  }
  if (group === 'takeover_truth') validateView(value.view);
}
function saveEdit(): void {
  try {
    const frame: ReviewFrame = currentFrame();
    const value: unknown = JSON.parse(element<HTMLTextAreaElement>('json-editor').value);
    validateEdit(selectedGroup, value, frame);
    const draft: ReviewDraft = draftFor(frame);
    saveDraft(frame, { edits: { ...draft.edits, [selectedGroup]: value }, status: 'pending',
      approved_groups: draft.approved_groups.filter((group: TruthGroup): boolean => group !== selectedGroup) });
    editorDirty = false;
    renderList(); renderFrame();
    notify(`已保存 ${frame.id} / ${GROUP_NAMES[selectedGroup]} 修订草稿。本组需要重新审核。`);
  } catch (error: unknown) {
    notify(`修订未保存：${error instanceof Error ? error.message : String(error)}`);
  }
}
function exportReviews(): void {
  if (!leaveEditor()) return;
  const payload: ReviewExport = { schema_version: 1, truth_sha256: bundle.truth_sha256,
    samples_sha256: bundle.samples_sha256, exported_at: new Date().toISOString(), reviews: drafts };
  const url: string = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
  const anchor: HTMLAnchorElement = document.createElement('a');
  anchor.href = url;
  anchor.download = `decoder-review-${new Date().toISOString().slice(0, 10)}-${bundle.truth_sha256.slice(0, 8)}.json`;
  anchor.click();
  window.setTimeout((): void => URL.revokeObjectURL(url), 1000);
  notify(`已导出 ${Object.keys(drafts).length} 帧的审核记录，包含修订、逐组通过与审核意见。`);
}
function validateReviews(value: unknown): Record<string, ReviewDraft> {
  value = compatibleExport(value);
  if (!isObject(value) || value.schema_version !== 1 || value.truth_sha256 !== bundle.truth_sha256 ||
    value.samples_sha256 !== bundle.samples_sha256 || !isObject(value.reviews)) {
    throw new Error('记录格式或数据版本不匹配，不能应用到当前标注快照。');
  }
  for (const [id, review] of Object.entries(value.reviews)) {
    const frame: ReviewFrame | undefined = bundle.frames.find((candidate: ReviewFrame): boolean => candidate.id === id);
    if (!frame || !isObject(review) || !['pending', 'approved', 'issue'].includes(String(review.status)) ||
      typeof review.note !== 'string' || !Array.isArray(review.approved_groups) || !isObject(review.edits) ||
      typeof review.updated_at !== 'string') throw new Error(`无效的审核记录：${id}`);
    if (!review.approved_groups.every((group: unknown): boolean => typeof group === 'string' &&
      applicableGroups(frame).includes(group as TruthGroup))) throw new Error(`无效的已审分组：${id}`);
    if (review.status === 'approved' && !applicableGroups(frame).every((group: TruthGroup): boolean =>
      (review.approved_groups as unknown[]).includes(group))) throw new Error(`整帧通过但分组未审完：${id}`);
    for (const [group, edit] of Object.entries(review.edits)) {
      if (!GROUPS.includes(group as TruthGroup)) throw new Error(`无效分组 ${group}`);
      validateEdit(group as TruthGroup, edit, frame);
    }
  }
  return value.reviews as unknown as Record<string, ReviewDraft>;
}
async function importReviews(file: File): Promise<void> {
  try {
    const imported: Record<string, ReviewDraft> = validateReviews(JSON.parse(await file.text()));
    if (Object.keys(drafts).some((id: string): boolean => id in imported) &&
      !window.confirm('导入文件包含已有草稿的帧，是否用导入记录覆盖这些帧？')) return;
    Object.assign(drafts, imported);
    persistDrafts(); renderList(); renderFrame();
    notify(`已导入 ${Object.keys(imported).length} 帧审核记录。`);
  } catch (error: unknown) {
    notify(`导入失败：${error instanceof Error ? error.message : String(error)}`);
  }
}
function bindEvents(): void {
  for (const id of ['search', 'scene-filter', 'overlay-filter', 'status-filter', 'difference-filter', 'boundary-filter', 'cursor-mismatch-filter']) {
    element(id).addEventListener(id === 'search' ? 'input' : 'change', renderList);
  }
  element('frame-list').addEventListener('click', (event: MouseEvent): void => {
    const button: HTMLButtonElement | null = (event.target as HTMLElement).closest('[data-frame]');
    if (button && leaveEditor()) { selectedId = button.dataset.frame!; renderList(); renderFrame(); }
  });
  document.querySelectorAll<HTMLButtonElement>('[data-group]').forEach((button: HTMLButtonElement): void => {
    button.addEventListener('click', (): void => { if (leaveEditor()) { selectedGroup = button.dataset.group as TruthGroup; renderFields(); } });
  });
  element('previous').addEventListener('click', (): void => moveFrame(-1));
  element('next').addEventListener('click', (): void => moveFrame(1));
  element('next-pending').addEventListener('click', (): void => moveFrame(1, true));
  element('approve-group').addEventListener('click', toggleGroup);
  element('approve-frame').addEventListener('click', (): void => setFrameStatus('approved'));
  element('flag-frame').addEventListener('click', (): void => setFrameStatus('issue'));
  element('reset-frame').addEventListener('click', (): void => setFrameStatus('pending'));
  element('json-editor').addEventListener('input', (): void => { editorDirty = true; });
  element('save-edit').addEventListener('click', saveEdit);
  element('review-note').addEventListener('input', (): void => saveDraft(currentFrame(), { note: element<HTMLTextAreaElement>('review-note').value }));
  element('export-button').addEventListener('click', exportReviews);
  element('import-button').addEventListener('click', (): void => { if (leaveEditor()) element<HTMLInputElement>('import-file').click(); });
  element('import-file').addEventListener('change', (): void => {
    const input: HTMLInputElement = element<HTMLInputElement>('import-file');
    if (input.files?.[0]) void importReviews(input.files[0]);
    input.value = '';
  });
  document.addEventListener('keydown', (event: KeyboardEvent): void => {
    if ((event.target as HTMLElement).matches('input,textarea,select,[contenteditable]') || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); moveFrame(event.key === 'ArrowLeft' ? -1 : 1); }
  });
  window.addEventListener('beforeunload', (event: BeforeUnloadEvent): void => { if (editorDirty) event.preventDefault(); });
}
function initialize(): void {
  element('total').textContent = `${bundle.frames.length} 帧`;
  try {
    if (bundle.imported_review) Object.assign(drafts, validateReviews(bundle.imported_review));
    let cached: string | null = localStorage.getItem(cacheKey);
    let cachedHash: string = bundle.truth_sha256;
    if (!cached) {
      for (const hash of bundle.compatible_truth_sha256) {
        cached = localStorage.getItem(`pokemon-label-review-v1:${hash}`);
        if (cached) { cachedHash = hash; break; }
      }
    }
    if (cached) {
      const restored: Record<string, ReviewDraft> = validateReviews({ schema_version: 1, truth_sha256: cachedHash,
        samples_sha256: bundle.samples_sha256, reviews: JSON.parse(cached) });
      for (const [id, draft] of Object.entries(restored)) {
        if (!drafts[id] || draft.updated_at > drafts[id].updated_at) drafts[id] = draft;
      }
    }
    if (cached && cachedHash !== bundle.truth_sha256) {
      persistDrafts();
      notify('已迁移去重前的本地审核进度；原缓存保留，请导出新记录备份。');
    }
  } catch {
    notify('本地缓存不可用或无效，已保留原始参考标注；可导入此前导出的审核记录。');
  }
  renderFilters(); renderList(); renderFrame(); bindEvents();
  if (bundle.imported_review) notify(`已载入用户审核记录 ${Object.keys(bundle.imported_review.reviews).length} 帧；更新的浏览器草稿保留。正式真值未因此自动获批。`);
  if (!bundle.diagnostic_current) notify('差异诊断与当前真值快照版本不一致，对照仅供历史参考；请以当前标注和原始素材为准。');
}
initialize();
