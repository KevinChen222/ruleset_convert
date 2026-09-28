# Mihomo → sing-box 规则集

把自己维护的 Mihomo 规则集放进 `rules/`，在 `sources.json` 里登记。GitHub Actions 会在推送到 `main` 后、每天约 04:00（台北时间）以及手动点击 **Actions → Convert rule sets → Run workflow** 时构建。成功后，Release `ruleset` 中会有同名的 sing-box 源格式 `.json` 和二进制 `.srs`。

目前没有登记真实规则，因此初次运行会成功跳过发布；加入第一份规则后才会创建 Release。**无需个人访问令牌**：工作流使用 GitHub 自动提供的 `GITHUB_TOKEN`。

## 添加规则

例如把 `DOMAIN-SUFFIX,example.com` 写入 `rules/my-sites.list`，然后将 `sources.json` 改为：

```json
{
  "sources": [
    {"name": "my-sites", "path": "rules/my-sites.list", "behavior": "classical"}
  ]
}
```

`behavior` 对应 Mihomo `rule-providers` 中的 `classical`、`domain`、`ipcidr`。输入可用逐行纯文本（`.list`、`.txt` 等）或含 `payload` 列表的 `.yaml` / `.yml`；二进制 `.mrs` 不是源文件，不能直接转换。一个源文件生成一对 `<name>.json` 和 `<name>.srs`。

支持的 `classical` 类型：`DOMAIN`、`DOMAIN-SUFFIX`、`DOMAIN-KEYWORD`、`DOMAIN-REGEX`、`IP-CIDR`、`IP-CIDR6`、`SRC-IP-CIDR`、`SRC-IP-CIDR6`、`PROCESS-NAME`、`PROCESS-PATH`、`DST-PORT`、`SRC-PORT`、`NETWORK`。`domain` 类型支持普通域名、`+.`、`.` 和整段标签 `*`（例如 `*.example.com`）。遇到不能可靠转换的类型、策略字段或 `no-resolve`，构建会报出位置并停止，避免发布不完整规则。

## 在 sing-box 中使用

Release 地址固定：`https://github.com/KevinChen222/ruleset_convert/releases/download/ruleset/my-sites.srs`。将 `my-sites` 换成 `sources.json` 中的 `name`：

```json
{
  "type": "remote",
  "tag": "my-sites",
  "format": "binary",
  "url": "https://github.com/KevinChen222/ruleset_convert/releases/download/ruleset/my-sites.srs",
  "update_interval": "1d"
}
```

把这个对象加入 sing-box 配置的 `route.rule_set`，再在需要的 `route.rules` 中引用它，例如 `{"rule_set": "my-sites", "action": "route", "outbound": "proxy"}`。源格式可把 URL 后缀改为 `.json`，同时把 `format` 改为 `source`。输出使用 sing-box 规则集版本 2，适用于 sing-box 1.10.0 及更新版本；二进制由官方 sing-box 1.14.2 编译。已有仓库提供的现成 sing-box 规则集可以直接引用，无需放进这里重新构建。

本地检查：`python -m pip install -r requirements.txt`，然后运行 `python -m unittest discover -s tests` 和 `python scripts/convert.py`。
