/** 仅兼容已记录的去重前快照；将旧草稿中的重复字段移到其所属组。 */
function jsonAt(value: JsonValue, path: string): JsonValue | undefined {
  let current: JsonValue | undefined = value;
  for (const part of path.split('.')) {
    if (Array.isArray(current)) current = current[Number(part)];
    else if (current !== null && typeof current === 'object') current = current[part];
    else return undefined;
  }
  return current;
}
function migrateLegacyDraft(raw: ReviewDraft, frame: ReviewFrame): ReviewDraft {
  const draft: ReviewDraft = JSON.parse(JSON.stringify(raw));
  const revised: TruthGroup[] = bundle.revised_groups[frame.id] ?? [];
  draft.approved_groups = draft.approved_groups.filter((group: TruthGroup): boolean => !revised.includes(group));
  if (revised.length && draft.status === 'approved') draft.status = 'pending';
  const takeover: Record<string, JsonValue> | undefined = draft.edits.takeover_truth;
  if (!takeover) return draft;
  const view: JsonValue | undefined = takeover.view;
  if (frame.truth.scene_truth.scene === 'battle_switch' && view !== null &&
      typeof view === 'object' && !Array.isArray(view) && view !== undefined &&
      (view.kind === 'faint_switch' || view.kind === 'battle_menu')) {
    takeover.view = { kind: 'battle_switch', party: view.party };
  }
  for (const key of ['scene', 'screen', 'screen_contains']) {
    if (!(key in takeover)) continue;
    const target: TruthGroup = key === 'scene' ? 'scene_truth' : 'screen_truth';
    const value: JsonValue = takeover[key];
    if (JSON.stringify(value) !== JSON.stringify(frame.truth[target][key])) {
      draft.edits[target] = { ...frame.truth[target], ...draft.edits[target], [key]: value };
      draft.approved_groups = draft.approved_groups.filter((group: TruthGroup): boolean => group !== target);
      if (draft.status === 'approved') draft.status = 'pending';
    }
    delete takeover[key];
  }
  for (const path of Object.keys(takeover).filter((key: string): boolean => key.startsWith('view.'))) {
    const baseline: JsonValue | undefined = jsonAt(frame.truth.takeover_truth.view, path.slice(5));
    const edited: JsonValue | undefined = jsonAt(takeover.view, path.slice(5));
    if (JSON.stringify(takeover[path]) !== JSON.stringify(baseline) && JSON.stringify(takeover[path]) !== JSON.stringify(edited)) {
      throw new Error(`${frame.id}: 旧草稿对 ${path} 有独立修订，请先将修改合入 view 对象后导入；原记录未覆盖。`);
    }
    delete takeover[path];
  }
  return draft;
}
function compatibleExport(value: unknown): unknown {
  if (!isObject(value) || value.truth_sha256 === bundle.truth_sha256) return value;
  if (!bundle.compatible_truth_sha256.includes(String(value.truth_sha256)) ||
    value.samples_sha256 !== bundle.samples_sha256 || !isObject(value.reviews)) return value;
  const reviews: Record<string, ReviewDraft> = {};
  for (const [id, raw] of Object.entries(value.reviews)) {
    const frame: ReviewFrame | undefined = bundle.frames.find((candidate: ReviewFrame): boolean => candidate.id === id);
    if (!frame || !isObject(raw) || !isObject(raw.edits) || !Array.isArray(raw.approved_groups)) throw new Error(`无效旧记录 ${id}`);
    reviews[id] = migrateLegacyDraft(raw as unknown as ReviewDraft, frame);
  }
  return { ...value, truth_sha256: bundle.truth_sha256, reviews };
}
