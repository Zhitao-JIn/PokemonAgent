"""按 task 场合与叠加层投影决策显示；不改变完整观测、记忆或测评输出。"""

from pokemon_agent.world import Facts, TaskObservation, TaskScene


def render_task_frame(observation: TaskObservation) -> str:
    """只显示当前操作需要的字段；接管缺视图或选单切分不全时保留屏幕证据。"""
    header = f"- covered_by_script: {str(observation.covered_by_script).lower()}"
    if observation.covered_by_script:
        body = (
            observation.takeover.render()
            if observation.takeover is not None
            else _compact_screen(observation.facts.screen) or "（未读出业务视图）"
        )
        body += f"\n- overlay: {observation.facts.overlay_value or 'none'}"
        if observation.facts.cursor:
            body += f"\n- cursor: {observation.facts.cursor}"
        screen = _compact_screen(observation.facts.screen)
        if observation.takeover is not None and screen:
            body += f"\nscreen:\n{screen}"
        if observation.selected_map_location is not None:
            body += f"\nselected_map_location: {observation.selected_map_location}"
            if observation.facts.where:
                body += f"\nwhere: {observation.facts.where}"
        return _with_notes(f"{header}\n{body}", observation)
    facts = dict(observation.facts.items())
    fields = _visible_fields(observation, facts)
    lines = [f"- scene: {observation.scene.value}", header]
    lines.append(f"- overlay: {observation.facts.overlay_value or 'none'}")
    visible = [(key, value) for key, value in fields if value]
    lines.extend(f"- {key}: {value}" for key, value in visible)
    return _with_notes("\n".join(lines), observation)


def _with_notes(body: str, observation: TaskObservation) -> str:
    """只显示适用的完整性值与限制；走路没文字不需要重复提示。"""
    if observation.menu_decode_complete is not None and (
        observation.facts.overlay is Facts.Overlay.CHOICE
        or observation.menu_decode_complete is False
    ):
        body += f"\n- menu_decode_complete: {str(observation.menu_decode_complete).lower()}"
    notes = observation.observation_notes
    if observation.scene in {TaskScene.WALK, TaskScene.SHOP} and (
        observation.facts.overlay is Facts.Overlay.NONE
    ):
        notes = [note for note in notes if not note.startswith("未解码出屏幕文字")]
    if notes:
        body += "\n- observation_notes: " + "；".join(notes)
    return body


def _visible_fields(observation: TaskObservation, facts: dict[str, str]) -> list[tuple[str, str]]:
    """走路给空间信息，纯对话给文字，其他界面保留整屏以免菜单切分丢失证据。"""
    overlay = observation.facts.overlay or Facts.Overlay.NONE
    if observation.scene in {TaskScene.WALK, TaskScene.SHOP} and overlay is Facts.Overlay.NONE:
        keys = ["where", "facing", "landmarks", "known_objects"]
        keys.append("walk_map" if facts.get("walk_map") else "neighbors")
        fields = [(key, facts.get(key, "")) for key in keys]
    elif overlay is Facts.Overlay.DIALOG and observation.scene not in {
        TaskScene.POKEMON_INFO,
        TaskScene.START_MENU,
        TaskScene.TITLE,
    }:
        fields = []
        if observation.scene in {TaskScene.DIALOG, TaskScene.SHOP}:
            fields.append(("where", facts.get("where", "")))
        fields.append(("dialog_text", facts.get("dialog_text", "")))
        if not facts.get("dialog_text"):
            fields.append(("screen", _compact_screen(observation.facts.screen)))
    elif observation.facts.screen:
        fields = [("screen", _compact_screen(observation.facts.screen))]
    else:
        keys = ["dialog_text", "option_layout", "option_details"]
        if not facts.get("option_layout"):
            keys.extend(["options", "cursor"])
        fields = [(key, facts.get(key, "")) for key in keys]
    if observation.scene in {TaskScene.DIALOG, TaskScene.SHOP} and (
        overlay is not Facts.Overlay.NONE and not any(key == "where" for key, _ in fields)
    ):
        fields.insert(0, ("where", facts.get("where", "")))
    if observation.scene is TaskScene.BATTLE:
        fields.extend(
            (key, value) for key, value in facts.items() if key.startswith(("my_", "foe_"))
        )
    return fields


def _compact_screen(screen: str) -> str:
    """仅省略空白行与行尾空格，保留文字、边框、光标及行内排布。"""
    return "\n".join(line.rstrip() for line in screen.splitlines() if line.strip())
