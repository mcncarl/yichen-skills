# 企微会议与日程

## 权限守门

每次先运行：

```bash
wecom-cli meeting --help
wecom-cli schedule --help
```

若当前企业返回“不支持授权”，停止并报告；不得创建测试会议、操作客户端或换用非官方协议。

## 预约会议

权限开放后，先用 `wecom-cli meeting create_meeting --schema` 读取当前 schema。至少确认：

- 标题；
- 开始时间，格式 `YYYY-MM-DD HH:mm`，默认按 Asia/Shanghai；
- 时长（秒）；
- 是否需要地点、描述和受邀成员。

用户未给齐标题、开始时间或时长时必须询问。不得猜测 userid；通讯录不可用时可创建无邀请人的会议，或让用户提供明确人员标识。

```bash
wecom-cli meeting create_meeting '{"title":"周例会","meeting_start_datetime":"2026-08-01 15:00","meeting_duration":3600}'
```

成功后返回可读标题、时间、时长、会议链接和格式化会议号；meetingid 仅内部保存。

## 查询与修改会议

- 列表：`list_user_meetings`，范围只支持当天前后30天；
- 详情：`get_meeting_info`；
- 受邀成员：`set_invite_meeting_members`，这是全量覆盖，先读取现有列表再合并；
- 取消：`cancel_meeting`，先列表＋详情定位，再让用户确认精确标题和时间。

禁止只凭标题模糊命中后直接修改或取消。

## 日程

权限开放后可用：

- `get_schedule_list_by_range`、`get_schedule_detail`；
- `create_schedule`、`update_schedule`、`cancel_schedule`；
- `add_schedule_attendees`、`del_schedule_attendees`；
- `check_availability`。

创建日程前确认标题、开始、结束、时区、提醒和参与人。取消日程和移除参与人前必须读取详情并确认目标。
