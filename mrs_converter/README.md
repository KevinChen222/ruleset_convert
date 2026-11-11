# 自定义上游 MRS

在仓库根目录的 `mrs-sources.json` 登记上游规则，GitHub Actions 会下载并转换为 Mihomo 可用的 `.mrs`，写入 `main` 分支的 `mrs/` 目录。

## 配置上游

```json
{
  "sources": [
    {
      "name": "Claude",
      "urls": [
        "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/refs/heads/master/rule/Clash/Claude/Claude_No_Resolve.yaml"
      ],
      "behavior": "classical"
    },
    {
      "name": "MyDomains",
      "urls": [
        "https://example.com/domains-a.yaml",
        "https://example.com/domains-b.txt"
      ],
      "behavior": "domain"
    }
  ]
}
```

`sources` 可包含多个条目，每项的 `name` 必须唯一，只能使用英文字母、数字、点、下划线和连字符，并以字母或数字开头。同一项的 `urls` 可填写多个 HTTPS 文件地址，下载后按规则合并、去重；这些 URL 使用同一个 `behavior`。GitHub 文件页面地址和 Raw 地址均可使用。示例中的 `example.com` 地址需要替换成实际规则地址。

输入支持含 `payload` 列表的 `.yaml` / `.yml` 文件，以及逐行规则的纯文本文件。`behavior` 填写上游的规则格式：

| behavior | 上游内容 | 产物 |
| --- | --- | --- |
| `domain` | `example.com`、`+.example.com`、`.example.com`、`*.example.com` 等域名规则 | `<name>.domain.mrs` |
| `ipcidr` | IPv4 / IPv6 CIDR | `<name>.ipcidr.mrs` |
| `classical` | `DOMAIN`、`DOMAIN-SUFFIX`、`IP-CIDR`、`IP-CIDR6` | 按内容生成 `<name>.domain.mrs`、`<name>.ipcidr.mrs` |

一个 `classical` 上游同时包含域名和 IP 时，会生成两份 MRS，需要在 Mihomo 中分别引用。没有对应规则的类型不生成文件。Claude 示例生成 `mrs/Claude.domain.mrs`。

MRS 仅支持 `domain` 和 `ipcidr`，无法保存 `DOMAIN-KEYWORD`、`DOMAIN-REGEX`、进程、端口、策略字段等规则。遇到这些规则、无效输入或下载失败时，工作流会报错，仓库保留上次成功生成的文件。`IP-CIDR` / `IP-CIDR6` 后的 `no-resolve` 不写入 MRS；需要时在 Mihomo 的 `RULE-SET` 引用处添加 `no-resolve`。

`mrs/` 中的 `.mrs` 文件由配置统一管理；移除配置条目或某类规则后，对应的产物会在成功转换时清理。其他文件应保存在该目录之外。

## 更新方式

Actions 每小时检查一次。距离 `mrs/.last-success` 记录的上次成功更新时间满 25 小时后，重新下载全部上游并转换；即使规则内容没有变化，也会记录本次成功时间。失败不更新时间，下次检查会重试。GitHub Actions 调度可能延迟，因此实际更新时间可能略晚。

向 `main` 推送配置、转换器或其工作流的修改后会立即转换。也可以点击 **Actions → Convert custom MRS → Run workflow**，选择 `main` 手动更新；这两种触发方式不受 25 小时间隔限制。

工作流使用 GitHub 自动提供的 `GITHUB_TOKEN` 提交 `mrs/` 目录。分支保护规则需要允许该工作流提交。

## 在 Mihomo 中使用

```yaml
rule-providers:
  Claude:
    type: http
    behavior: domain
    format: mrs
    url: https://raw.githubusercontent.com/KevinChen222/ruleset_convert/main/mrs/Claude.domain.mrs
    path: ./ruleset/Claude.domain.mrs
    interval: 90000

rules:
  - RULE-SET,Claude,PROXY
```

将 `PROXY` 换成配置中的代理组名称。IP 产物使用 `behavior: ipcidr` 和对应的 `.ipcidr.mrs` 地址。`interval: 90000` 是客户端每 25 小时拉取一次，与仓库自动转换分别计时。

## 本地运行

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s mrs_converter/tests -v
python3 mrs_converter/convert.py --mihomo /path/to/mihomo
python3 mrs_converter/convert.py --check-due
```

`--manifest` 可指定配置文件，`--output-dir` 可指定产物目录。转换使用官方 Mihomo 的 `convert-ruleset` 命令。
