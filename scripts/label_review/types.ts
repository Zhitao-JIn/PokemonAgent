/** 审阅页的数据形状；原始标注与浏览器审核草稿分别保存。 */
type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
type TruthGroup = 'scene_truth' | 'screen_truth' | 'takeover_truth' | 'terrain_truth';
type ReviewStatus = 'pending' | 'approved' | 'issue';
interface TruthRow {
  sample_id: string;
  scene_truth: Record<string, JsonValue>;
  screen_truth: Record<string, JsonValue>;
  takeover_truth: Record<string, JsonValue>;
  terrain_truth: Record<string, JsonValue>;
  note: string;
  unresolved_fields: Record<string, string>;
}
interface ReviewFrame {
  id: string;
  image: string;
  source: string;
  note: string;
  truth: TruthRow;
  tiles: number[][];
  differences: Record<string, { expected: JsonValue; actual: JsonValue }>;
  warning: string;
  cursor_evidence: {
    image: [number, number][];
    ram: [number, number][];
    hollow: [number, number][];
    mismatch: boolean;
    method: string;
  } | null;
}
interface ReviewBundle {
  schema_version: number;
  generated_at: string;
  truth_sha256: string;
  samples_sha256: string;
  diagnostic_current: boolean;
  compatible_truth_sha256: string[];
  revised_groups: Partial<Record<string, TruthGroup[]>>;
  imported_review: ReviewExport | null;
  frames: ReviewFrame[];
}
interface ReviewDraft {
  status: ReviewStatus;
  note: string;
  approved_groups: TruthGroup[];
  edits: Partial<Record<TruthGroup, Record<string, JsonValue>>>;
  updated_at: string;
}
interface ReviewExport {
  schema_version: number;
  truth_sha256: string;
  samples_sha256: string;
  exported_at: string;
  reviews: Record<string, ReviewDraft>;
}
const GROUPS: TruthGroup[] = ['scene_truth', 'screen_truth', 'takeover_truth', 'terrain_truth'];
const GROUP_NAMES: Record<TruthGroup, string> = {
  scene_truth: '场合', screen_truth: '屏幕文字', takeover_truth: '接管视图', terrain_truth: '地形与位置'
};
const EXPLANATIONS: Record<string, string> = {
  scene: '界面所属场合', covered_by_script: '该场合由接管脚本负责；子菜单也算覆盖',
  at_start: '是否处于脚本入口主菜单；普通场合为 null', overlay: '按键控制模式：none 常规 / dialog 对话推进 / choice 菜单或数量选择；不表示窗口是否重叠',
  dialog_text: '底部对话或图鉴说明的实际文字', options: '光标菜单或无光标的完整商品价格表，按屏幕顺序',
  cursor: '实心光标指向的选项；无实心光标时为空', option_grid: '实际排布：外层为行，内层为列',
  cursor_cell: '光标在排布中的 [行, 列]，从 0 开始', option_details: '与选项一一对应的数量或价格附注',
  covered: '文字解码是否完整切出光标菜单；与脚本覆盖无关', has_cursor: '是否出现实心 ▶ 光标',
  quantity_box: '是否出现 ×01 等数量框', strict_dialog: '只有底部对话框，且没有光标、数量框或其他框',
  screen: '整屏参考字表渲染；未知图形为 ·', in_battle: '冻结 RAM 的战斗标志是否非零',
  view: '脚本需要的完整业务数据；普通场合为 null', kind: '接管视图种类', target: '起名对象的标题',
  typed: '已经输入的名字', items: '商店商品或 PC 道具', money: '当前金钱', bag: '背包道具及数量',
  mine: '我方在场宝可梦', foe: '对手宝可梦', trainer: '是否训练家对战', party: '队伍，保持队伍顺序',
  name: '名称或昵称', level: '等级', hp: '当前 HP', max_hp: '最大 HP', status: '状态：ok / PSN / BRN / FRZ / PAR / SLP',
  active: '是否正在场上', moves: '招式列表', pp: '剩余 PP', quantity: '道具数量', price: '商品单价',
  box: '当前 PC 箱中的宝可梦', box_number: 'PC 箱号，从 1 开始', pokemon: '正在学招的宝可梦',
  new_move: '准备学习的新招式', map_id: '地图编号', where: '主角实际所在的全局坐标',
  facing: '朝向 north / south / west / east', walk_map: '当前图块缓冲的 10×9 地形投影，菜单遮挡时不代表底图',
  neighbors: '主角北、南、西、东四格的地形标记', screen_contains: '此前已审核的整屏文字片段'
};
const bundle: ReviewBundle = JSON.parse(document.getElementById('review-data')!.textContent!);
const drafts: Record<string, ReviewDraft> = {};
const cacheKey: string = `pokemon-label-review-v1:${bundle.truth_sha256}`;
let selectedId: string = bundle.frames[0].id;
let selectedGroup: TruthGroup = 'scene_truth';
let filteredFrames: ReviewFrame[] = bundle.frames;
let editorDirty: boolean = false;

function element<T extends HTMLElement = HTMLElement>(id: string): T {
  const found: HTMLElement | null = document.getElementById(id);
  if (!found) throw new Error(`缺少页面元素 ${id}`);
  return found as T;
}
function escapeText(value: string): string {
  const span: HTMLSpanElement = document.createElement('span');
  span.textContent = value;
  return span.innerHTML;
}
function displayValue(value: JsonValue): string {
  if (value === '') return '""（空字符串）';
  if (value === null) return 'null（不适用 / 无此内容）';
  if (Array.isArray(value) && value.every((item: JsonValue): boolean => item === null || typeof item !== 'object')) {
    return JSON.stringify(value);
  }
  if (Array.isArray(value) && value.every((item: JsonValue): boolean => Array.isArray(item))) {
    return '[\n' + value.map((row: JsonValue): string => `  ${JSON.stringify(row)}`).join(',\n') + '\n]';
  }
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}
function currentFrame(): ReviewFrame {
  return bundle.frames.find((frame: ReviewFrame): boolean => frame.id === selectedId)!;
}
function draftFor(frame: ReviewFrame): ReviewDraft {
  return drafts[frame.id] ?? { status: 'pending', note: '', approved_groups: [], edits: {}, updated_at: '' };
}
function truthFor(frame: ReviewFrame, group: TruthGroup): Record<string, JsonValue> {
  return draftFor(frame).edits[group] ?? frame.truth[group];
}
function applicableGroups(frame: ReviewFrame): TruthGroup[] {
  return GROUPS.filter((group: TruthGroup): boolean => group !== 'terrain_truth' || Object.keys(frame.truth.terrain_truth).length > 0);
}
function notify(message: string): void {
  element('message').textContent = message;
}
