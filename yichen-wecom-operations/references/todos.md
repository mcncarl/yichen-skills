# 企微待办

## 当前能力

先运行 `wecom-cli todo --help`。当前企业已返回以下工具：

- `search_todo_userid`；
- `create_todo`、`update_todo`、`delete_todo`；
- `get_todo_list`、`get_todo_detail`；
- `change_todo_user_status`。

只能操作本机器人创建的待办。

## 创建

创建前确认内容、参与人、截止时间和提醒。`follower_list` 必填；userid 必须通过 `search_todo_userid` 查询，不得猜测或展示给用户。

```bash
wecom-cli todo create_todo '{"content":"提交报告","follower_list":{"followers":[{"follower_id":"USERID","follower_status":1}]},"end_time":"2026-08-01 18:00:00","remind_type_list":[3]}'
```

提醒枚举：`0`不提醒、`1`到期时、`3`提前15分钟、`5`提前1小时、`6`提前2小时、`7`提前1天、`8`提前2天、`9`提前1周。设置实际提醒时必须提供截止时间。

## 查询与更新

- 查询范围通常限当天前后30天；
- `update_todo` 的参与人列表是全量替换，先读取详情再合并；
- `change_todo_user_status` 用于接受、拒绝或完成参与状态；
- todo_id 只用于内部传参，不在回复中展示。

## 删除

删除前先读取详情，向用户复述待办内容、截止时间和当前状态，并取得对该目标的明确确认。禁止批量猜测或自动清理。
