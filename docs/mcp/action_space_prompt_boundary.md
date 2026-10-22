# 动作空间与 prompt 文案的边界

原生 ActionSpace / MCP 返回仅包含 scene、names、mask、entries。entries 中的 description 与 params 的 description 是 world 定义的能力数据，仍原样提供。按键帮助、连按说明与读图规则由 prompt 的活动版本按 overlay 与脚本接管状态选择。

为保持冻结历史请求的精确 JSON 往返，模型允许保留旧输入中的扩展键。旧 descriptions / note / map_note 不再是声明字段，新生产者不生成它们，当前 prompt 也不读取它们。mcpclient.with_prompt_text 仅保留原入口的透传行为，不增加文案。

受保护的旧 prompt 包与常量保持不动，供历史对拍使用，物理删除留到 CP7。CP5a 的工具层帧与签名转换为暂时桥接，CP5b 收回版本内。
