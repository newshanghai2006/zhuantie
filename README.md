# 译浪：海外热帖本土化内容工作台

译浪是一个本地运行的内容编辑工具。它可以发现 Reddit 热门帖子和 Quora 公开问答，自动导入来源内容，并通过大语言模型同时生成小红书、今日头条文章及中英双语 AI 绘图提示词。

## 功能

- 按门类浏览 Reddit 热帖，并可接入已授权的 Quora 内容源
- Reddit 支持热度、点赞、评论、最新和上升排序；仅在来源提供指标时显示数值
- Quora 授权连接器支持热度、点赞、评论、浏览量和最新排序
- 自动读取 Reddit 或已授权 Quora 来源的正文与可用评论
- Reddit JSON 接口不可用时回退至 RSS，并使用短期本地缓存降低限流影响
- 不直接抓取 Quora 页面，也不通过代理绕过登录、访问控制或机器人规则
- 同时生成小红书和今日头条两个版本
- 输出固定结构的 JSON，可复制文章或下载完整结果
- 每张配图同时输出适用于 Midjourney、Flux、ChatGPT 的英文 Prompt 和适用于豆包的中文 Prompt
- 提供敏感主题预过滤和本土化合规改编提示词
- 支持保存多个 OpenAI 兼容或 Claude 原生模型配置
- 使用请求间隔、滑动窗口 RPM 和 TPM 预算共同控制调用频率
- 在调用模型前清洗 HTML、删除状态、Reddit 内链及图片链接，并按预算截断正文与评论
- 优先使用 JSON Schema、JSON Mode 或 Claude Tool Schema，接口不兼容时自动降级

## 环境要求

- Python 3.11 或更高版本
- 能够访问 Reddit、图标 CDN 及所配置模型服务的网络环境
- OpenAI Chat Completions 兼容接口或 Claude Messages API；本地兼容服务可以不使用 Token

项目仅使用 Python 标准库，无需安装第三方 Python 包。

## 本地启动

```bash
python server.py
```

浏览器访问：

```text
http://127.0.0.1:8765
```

需要修改监听地址或端口时：

```bash
python server.py --host 127.0.0.1 --port 9000
```

## 使用流程

1. 在左侧选择 Reddit 或 Quora，再选择内容门类和可用排序方式。
2. 选择帖子，程序会自动填入标题、正文摘要和可用评论。
3. 在创作台选择评论排序和 Top 5、Top 8 或 Top 10。
4. 打开“模型设置”，选择或新增配置，填写供应商协议、接口地址、模型和调用预算。
5. 生成小红书、今日头条文章和中英双语配图 Prompt。
6. 人工核验事实、版权、平台规范和配图提示词后再发布。

OpenAI、DeepSeek 及其他兼容服务使用“OpenAI 兼容”协议。直接调用 Claude Messages API 时选择“Claude 原生”协议。

## Quora 授权连接器

Quora 当前没有供本项目直接使用的公开热榜 API，并在机器人规则中限制将平台内容用于 AI/机器学习。项目因此不直接抓取 Quora。若你拥有合同授权、自有数据接口或合规的数据供应商，可以在启动前设置：

```powershell
$env:QUORA_API_BASE_URL = "https://your-authorized-connector.example/v1"
$env:QUORA_API_TOKEN = "在本机设置，不要写入仓库"
python server.py
```

连接器需要实现：

- `GET /posts?topic=...&sort=hot|upvotes|comments|views|new&limit=...`
- `GET /post?url=...`

列表接口返回 `{"posts": [...]}`，详情接口返回 `{"post": {...}}`。帖子字段支持 `title`、`body`、`url`、`topic`、`upvotes`、`answer_count`、`views`、`created_at` 和 `comments`。连接器 Token 只从进程环境读取，不应写入 `.env` 后提交。

## 模型与凭据安全

- 仓库不包含任何 API Token、账户密码或供应商凭据。
- 每个浏览器会生成一个匿名设备配置 ID，该 ID 不采集硬件、账户、IP 或浏览器指纹。
- 勾选“在此设备记住 Token”后，Token 使用 Web Crypto AES-GCM 加密并保存在浏览器本地存储；密钥由本地设备配置 ID 派生。
- 这种设备端加密用于避免明文保存和意外泄露，不能防御已经取得本机浏览器访问权或页面脚本执行权的攻击者。公共或多人共用设备上请取消“记住 Token”。
- 可以保存多个模型配置；模型参数和加密后的 Token 仅存在当前浏览器，不写入项目目录或服务日志。
- 原帖内容、评论和来源链接会发送给用户选择的模型供应商。使用前请确认其隐私政策和数据保留规则。
- 不要把 Token 写入源码、README、截图、日志或提交记录。若凭据曾被提交，应立即在供应商后台撤销并重新生成。

> 本项目默认仅监听 `127.0.0.1`，定位为单用户本地工具。服务没有用户认证、TLS、权限隔离或凭据保险库，不应直接暴露到公网。

## 数据源与合规说明

- Reddit 数据来自其公开 JSON 或 RSS 页面。站点策略和网络环境可能导致正文、评论、分数或缩略图暂时不可用。
- Quora 没有供本项目直接使用的稳定公开热门榜和浏览量接口。只有授权连接器返回的数据才会显示为 Quora 内容。
- 项目不会绕过登录、访问控制或反爬机制；未配置连接器时，Quora 页面会明确显示不可用状态。
- 敏感主题预过滤和模型提示词只能辅助审核，不能替代人工审查。
- 发布前应确认内容准确性、素材版权、原平台条款以及目标平台的最新规范，并清晰区分原帖陈述、网友意见和可验证事实。

## 项目结构

```text
.
├── server.py             # 本地 HTTP 服务、数据源和模型调用
├── static/
│   ├── favicon.svg       # 红底“轉”字站点图标
│   ├── index.html        # 工作台页面
│   ├── styles.css        # 响应式界面样式
│   └── app.js            # 浏览器交互逻辑
├── tests/
│   └── test_server.py    # 后端单元测试
├── .gitignore
└── README.md
```

## 测试

```bash
python -m unittest discover -s tests -v
```

测试使用模拟模型响应，不会调用真实模型，也不需要 API Token。

## GitHub 发布前检查

```bash
git status --short
git diff --cached
```

确认提交列表中没有 `.env`、密钥文件、日志、截图、生成结果或个人配置。`.gitignore` 只能阻止尚未被 Git 跟踪的文件；已经进入提交历史的敏感信息必须从历史中移除，并立即轮换相关凭据。
