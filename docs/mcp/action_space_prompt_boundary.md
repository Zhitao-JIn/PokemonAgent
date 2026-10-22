# ActionSpace 与 prompt 的边界

MCP仅传world能力数据：scene、mask、entries、names。客户端直接验证返回值，不补展示文案；with_prompt_text已删除。

ActionSpace使用extra="ignore"，冻结输入中的descriptions、note、map_note被忽略，不作为当前契约字段。按键说明、脚本签名和静态地图规则由版本化prompt网关生成。客户端与本地动作空间的结构化结果及最终prompt逐字节相等。
