# Manual Gates

Use this file before any workflow that touches login, credentials, proxy, certificates, or WeChat desktop.

## Must Be Done By The User

- Scan exporter login QR code.
- Select the correct WeChat Official Account or service account during login.
- Confirm use of any auth-key or credentials file.
- Open article/history pages in WeChat desktop when credential capture is required.
- Scroll the historical article list if using proxy/history fallback.
- Manually inspect downloaded content when copyright, restricted access, or publication risk matters.

## Must Require Explicit Confirmation

- Install mitmproxy or wxdown-service dependencies.
- Trust a mitmproxy root CA certificate.
- Enable, disable, or change macOS system proxy settings.
- Start a proxy that intercepts WeChat article HTTPS traffic.
- Store credentials in a local file or Keychain.
- Use browser automation on exporter UI after login.

## Never Do

- Do not control the user's WeChat UI.
- Do not publish, delete, mass-send, follow, unfollow, or send messages.
- Do not bypass login, paywalls, deleted articles, private content, or permission checks.
- Do not use another person's account/session as an account pool.
- Do not print cookies, auth-key, token, pass_ticket, key, uin, credential JSON, or QR login secrets.
- Do not leave system proxy pointing at a local interceptor after a run.

## Things That May Fail Even With User Help

- WeChat changes endpoint behavior or markup.
- The article has comments disabled or hidden.
- Metrics require fresh credentials that expire quickly.
- Images or media URLs expire.
- Public exporter endpoints rate-limit or reject requests.
- Local proxy conflicts with Clash or other system proxy settings.

## Safe User Prompts

Use concise prompts like:

```text
这个步骤需要你扫码登录公众号后台。我不会操作微信。你扫码并选择对应公众号后告诉我“已登录”。
```

```text
要抓阅读量和评论，需要启动本地 wxdown-service 并信任 mitmproxy 证书。确认后我只启动本地服务；微信页面需要你自己打开。
```

```text
现在需要临时改系统 HTTP/HTTPS 代理到 127.0.0.1:<port>。我会先保存当前设置，结束后恢复。确认吗？
```
