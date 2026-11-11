# 自定义上游 MRS

在仓库根目录的 `mrs-sources.json` 登记上游规则，GitHub Actions 会下载并转换为 Mihomo 可用的规则文件，写入 `main` 分支。域名和 IP 分别保存在 `mrs/domain/`、`mrs/ip/`，关键词、ASN 和进程等规则保存在 `classical/` 的补充 YAML 文件中。

## 规则来源

| 名称 | 上游 | 产物类型 |
| --- | --- | --- |
| OpenAI | blackmatrix7 的 OpenAI_No_Resolve | domain、ip、classical |
| Claude | blackmatrix7 的 Claude_No_Resolve | domain |
| Gemini | blackmatrix7 的 Gemini_No_Resolve、BardAI_No_Resolve | domain、classical |
| AWAvenue-Ads-Rule | TG-Twilight 的 AWAvenue-Ads-Rule-Clash | domain |
| Telegram | blackmatrix7 的 Telegram_No_Resolve | domain、ip、classical |
| GoogleFCM | blackmatrix7 的 GoogleFCM_No_Resolve | domain、ip |
| ChatGPTVoice | KevinChen222/rule- 的 ChatGPTVoice.list | ip |
| Alibaba | blackmatrix7 的 Alibaba_Classical_No_Resolve | domain、ip、classical |
| BiliBili | blackmatrix7 的 BiliBili_No_Resolve | domain、ip、classical |

完整上游 URL 见 `mrs-sources.json`。产物类型按上游实际内容生成；Claude、Gemini 的上述上游没有 IP-CIDR 规则，因此没有对应的 IP MRS。Gemini 的 `classical` 补充文件包含域名关键词规则。

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
| `domain` | `example.com`、`+.example.com`、`.example.com`、`*.example.com` 等域名规则 | `mrs/domain/<name>_domain.mrs` |
| `ipcidr` | IPv4 / IPv6 CIDR | `mrs/ip/<name>_ip.mrs` |
| `classical` | `DOMAIN`、`DOMAIN-SUFFIX`、`IP-CIDR`、`IP-CIDR6` 及下述补充类型 | 按内容分别生成域名 MRS、IP MRS、classical YAML |

一个 `classical` 上游同时包含域名和 IP 时，会生成两份 MRS，需要在 Mihomo 中分别引用。没有对应规则的类型不生成文件。Claude 示例生成 `mrs/domain/Claude_domain.mrs`，BiliBili 生成 `mrs/domain/BiliBili_domain.mrs`、`mrs/ip/BiliBili_ip.mrs` 和 `classical/BiliBili_classical.yaml`。

MRS 仅支持 `domain` 和 `ipcidr`。`DOMAIN-KEYWORD`、`DOMAIN-REGEX`、`IP-ASN`、`PROCESS-NAME`、`PROCESS-PATH` 会保留在 `classical/<name>_classical.yaml` 中，需要一并引用才能覆盖这些上游规则。`IP-ASN` 的 `no-resolve` 保留在补充 YAML 中。未知类型、策略字段、无效输入或下载失败会使工作流报错，仓库保留上次成功生成的文件。

`IP-CIDR` / `IP-CIDR6` 后的 `no-resolve` 不写入 MRS；使用 No_Resolve 上游时，在对应 IP MRS 的 `RULE-SET` 引用处添加 `no-resolve`。

`mrs/` 中的 `.mrs` 和 `classical/` 中的 `*_classical.yaml` 由配置统一管理；移除配置条目或某类规则后，对应的产物会在成功转换时清理。其他规则文件应保存在这两个目录之外。

## 更新方式

Actions 每小时检查一次。距离 `mrs/.last-success` 记录的上次成功更新时间满 25 小时后，重新下载全部上游并转换；即使规则内容没有变化，也会记录本次成功时间。失败不更新时间，下次检查会重试。GitHub Actions 调度可能延迟，因此实际更新时间可能略晚。

向 `main` 推送配置、转换器或其工作流的修改后会立即转换。也可以点击 **Actions → Convert custom MRS → Run workflow**，选择 `main` 手动更新；这两种触发方式不受 25 小时间隔限制。

工作流使用 GitHub 自动提供的 `GITHUB_TOKEN` 提交 `mrs/` 和 `classical/` 目录。分支保护规则需要允许该工作流提交。

## 在 Mihomo 中使用

```yaml
rule-providers:
  BiliBili_domain:
    type: http
    behavior: domain
    format: mrs
    url: https://raw.githubusercontent.com/KevinChen222/ruleset_convert/main/mrs/domain/BiliBili_domain.mrs
    path: ./ruleset/BiliBili_domain.mrs
    interval: 90000
  BiliBili_ip:
    type: http
    behavior: ipcidr
    format: mrs
    url: https://raw.githubusercontent.com/KevinChen222/ruleset_convert/main/mrs/ip/BiliBili_ip.mrs
    path: ./ruleset/BiliBili_ip.mrs
    interval: 90000
  BiliBili_classical:
    type: http
    behavior: classical
    format: yaml
    url: https://raw.githubusercontent.com/KevinChen222/ruleset_convert/main/classical/BiliBili_classical.yaml
    path: ./ruleset/BiliBili_classical.yaml
    interval: 90000

rules:
  - RULE-SET,BiliBili_domain,PROXY
  - RULE-SET,BiliBili_ip,PROXY,no-resolve
  - RULE-SET,BiliBili_classical,PROXY
```

将 `PROXY` 换成配置中的代理组名称。其他规则按相同的目录与命名方式引用；只有 IP 产物的 ChatGPTVoice 使用 `behavior: ipcidr`。其语音媒体流量需要代理节点支持 UDP。`interval: 90000` 是客户端每 25 小时拉取一次，与仓库自动转换分别计时。

## 本地运行

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s mrs_converter/tests -v
python3 mrs_converter/convert.py --mihomo /path/to/mihomo
python3 mrs_converter/convert.py --check-due
```

`--manifest` 可指定配置文件，`--output-dir` 可指定 MRS 目录，`--classical-dir` 可指定补充 YAML 目录，默认是 MRS 目录同级的 `classical/`。转换使用官方 Mihomo 的 `convert-ruleset` 命令。
