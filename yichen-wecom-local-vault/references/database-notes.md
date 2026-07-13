# 企业微信5.x本地数据库说明

## 适用范围

- macOS 企业微信5.x。
- Bundle ID 通常为 `com.tencent.WeWorkMac`。
- 数据集以同时存在 `message.db`、`session.db`、`user.db` 为识别条件。
- 不适用于个人微信 `com.tencent.xinWeChat`。

## 加密格式

企业微信5.x数据库使用 wxSQLite3 风格的 AES-128-CBC 分页加密，与个人微信4.x SQLCipher AES-256/HMAC 格式不同：

- raw key：16字节。
- page size：通常4096字节。
- 每页 AES key：对 `raw_key + little_endian(page_number) + b"sAlT"` 取 MD5。
- IV：由页码驱动的 wxSQLite3 兼容伪随机序列再取 MD5。
- 第一页保留部分 SQLite header 字段，用于识别格式并验证 key。
- 没有个人微信 SQLCipher 的80字节 reserve/HMAC区。

## 核心数据库和表

### `user.db`

- `user_table`：联系人主体。常见字段：`id`、`name`、`real_name`、`account`、`external_corp_name`、`external_job`。
- `external_user_relation_v3`：外部联系人备注。常见字段：`user_id`、`remarks`、`real_remarks`、`corp_remark`。

### `session.db`

- `conversation_table`：会话。常见字段：`id`、`name`、`roomname_remark`、`last_message_time`、`last_message_id`。
- `conversation_user_table`：群成员昵称。常见字段：`conversation_id`、`user_id`、`nick_name`。
- conversation ID 常见前缀：`R:` 群聊、`S:` 单聊、`M:` 微信联系人、`O:` 应用、`Y:` 系统。

### `message.db`

常见消息表：

- `message_table`
- `message_small_table`
- `kf_message_tableV1`

常见字段：`message_id`、`server_id`、`sequence`、`sender_id`、`conversation_id`、`content_type`、`send_time`、`flag`、`content`、`extra_content`、`local_extra_content`。

所有查询都要先用 `PRAGMA table_info` 检查字段；版本升级时不要假定字段永远存在。

## WAL 快照

企业微信运行时可能把最新消息留在 `*.db-wal`。本 Skill 不生成可挂载的明文 WAL，而是：

1. 读取一次源 WAL 字节快照。
2. 解析32字节 WAL header 和每个24字节 frame header。
3. 只保留最后一个 commit frame 以前的完整事务。
4. 按 frame 中的数据库页码解密页面。
5. 把页面写入新建的明文数据库快照并按 commit size 截断。

这样不会修改源数据库，也不会依赖解密后已失效的 WAL checksum。

## 安全验证

- key 只有在解密第一页后出现合法 SQLite header，并且第100字节是合法 B-tree page type 时才算通过。
- 密钥文件权限必须为 `0600`，目录为 `0700`。
- 明文数据库和导出文件权限为 `0600`。
- manifest 不写 raw key，也不写原始账号目录。
