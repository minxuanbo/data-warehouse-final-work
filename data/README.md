# 采集提交入口 · v1.0

2026-10-30：用户已确认设计审核通过。本版规范冻结，用于**小批采集和联调**；尚未完成数据验收，不直接扩量。代码与完整采集批次统一通过本 GitHub 仓库交付，无需另传网盘。

## 1. 谁交到哪里

| 成员 | 代码及来源说明 | 完整数据批次 | 分支 |
| --- | --- | --- | --- |
| A：腾讯 | `collectors/tencent/` | `data/tencent/<batch_id>/` | `feature/collector-tencent` |
| B：网易 | `collectors/netease/` | `data/netease/<batch_id>/` | `feature/collector-netease` |
| C：模型与入库 | 审核字段、接入和技术链路 | 在对应批次 README 填验收结论 | `feature/warehouse` |
| D：技能与指标 | 抽检正文、技能与指标字段 | 在对应批次 README 补抽检结果 | `feature/analysis` |

新增企业先在 Issue 认领并验证，批准 source 代码后再建同结构目录。不得擅自把新企业数据混入腾讯/网易批次。现有 `research/` 是历史可行性证据，不作为正式交付目录。

## 2. 现在具体采什么

- A 腾讯、B 网易，首批各目标 **100 个不同来源岗位 ID**，不足如实交付并说明原因，不复制数据凑数。
- 中国大陆数字技术岗位：开发、测试、数据开发/分析、算法/AI、运维/安全；不限制单一城市。明确海外、游戏美术、纯销售、纯产品/非技术项目管理、综合招聘简章排除于核心样本。
- 社招、校招、实习按实际入口保留，未知类型留 null；不要求为了凑齐类型去猜接口。优先使用已经试采成功的入口，具体来源及字段见[小组说明第 4—5 节](../docs/小组项目说明与采集交付规范.md)。
- 小批按页面正常顺序采集，类别及地点有疑义的记录登记异常，交 C 复核；排除记录也在异常文件注明 ID、理由和原始引用。无单城市/单类别配额，不保证样本代表市场。
- `query_spec` 必须记录真实端点、请求参数、页序和筛选策略。达到约 100 条便停止的小批属于截取样本，`coverage_status=partial`、`stop_reason=pilot_limit`，即便小批验收通过也不能用于全量变化指标。
- 腾讯补采详情中的任职要求；网易列表正文完整时无需每条重复请求详情，但抽查至少 5 条详情核对；缺失/截断则补采。薪资没有就 null。
- 单来源单并发，请求间隔至少 3 秒；最多重试 2 次并退避，网站更严格时遵守其要求。遇登录、验证码、访问限制立即停止并记录。

## 3. 一条命令建立批次

先拉取最新 main，在**仓库根目录**执行（命令中的 python 为本机 Python 3.12）：

```powershell
# A 执行；B 将 tencent 改为 netease，A 改为 B
python scripts/new_collection_batch.py --source tencent --owner A
```

工具生成带 UTC 时间和随机后缀的批次 ID，输出实际目录。它**只建立空模板，不采集数据，也不代表验收通过**。生成结构如下：

```text
data/tencent/<batch_id>/
├─ raw/                   原始响应，按请求分文件
├─ jobs.jsonl             规范数据，一行一条来源岗位
├─ manifest.json          范围、计数、文件哈希清单
├─ requests.jsonl         不含凭据的请求日志
├─ quality_issues.jsonl   异常、排除及冲突记录，无异常时为空
└─ README.md              自检、逐条抽检、待验收/验收结论
```

不要创建“最终版”“修改版2”文件夹。每次真实采集产生新 batch_id；失败后重新解析同一批原始数据，验收前可以修订 jobs 和清单并保留 Git 记录。已验收批次的数据文件不原地覆盖，修正须新建批次并填写 `supersedes_batch_id` 和原因；重新解析不伪装成新的观察时间。

## 4. 文件规范

**岗位字段唯一正式定义在[小组说明第 5 节](../docs/小组项目说明与采集交付规范.md)**，不得自行改名。字段键全部存在；可选值缺失用 null。规范文件为 UTF-8（无 BOM），JSONL 不包在一个总数组里，末尾换行。ID 始终为字符串；地点为字符串数组；同批 `(source,source_job_id)` 唯一，跨日保留同岗观察。

`raw_refs` 每项固定为 `{"path":"raw/<文件名>","sha256":"<64位小写十六进制>"}`，路径相对**本批次目录**，统一 `/`，禁止绝对路径及 `..`。多个岗位共用同一列表文件时引用同一个文件，不复制响应。此处是格式占位说明，不得当真实数据提交。

| 文件 | 填写规则 |
| --- | --- |
| `raw/` | 以 `list_000001.json`、`detail_<安全文件名>.json` 等保存实际响应体字节；HTML 用 `.html`。文件名只用字母、数字、下划线、连字符；不要直接使用未经处理的源 ID。记录响应编码，不混入请求头和凭据 |
| `jobs.jsonl` | 完整岗位正文，按字段契约输出；观察时间带时区，推荐 UTC；`schema_version=1.0`，source、batch_id 与清单一致 |
| `requests.jsonl` | 每请求一行：request_id、requested_at、method、url、脱敏 params/body、http_status、business_success、response_path、encoding、elapsed_ms、attempt、error；不保存 Cookie、Authorization、Token 或登录态 |
| `quality_issues.jsonl` | 每问题一行：source_job_id（无法识别时 null）、rule、severity（info/warning/error）、action（exclude/review/retry/reject）、message、raw_refs。职责/学历冲突同时保留原值，不静默修正 |
| `manifest.json` | 模板所有键都保留；填真实起止时间、范围、页数、各项计数、代码 commit。`acceptance_status` 初始 pending；coverage 与验收是两个独立概念。raw_response_files 包含所有保存的响应数，分页按列表响应计 |
| `README.md` | 写运行命令、来源/访问限制、缺口、自检和至少 20 条逐条抽检（不足则全检），最后由 C/D 写验收结果 |

`manifest.files` 枚举本批次全部原始响应、jobs、requests、quality_issues，每项包含 `path`、`bytes`、`sha256`、`records`。JSONL 的 records 为非空行数；原始响应填 null。**排除 manifest 自身、README 和 .gitkeep**，避免自引用哈希及验收文字修改导致哈希变化。哈希计算保存后的文件字节；仓库 `.gitattributes` 对 data 禁用换行转换，保证 clone/pull 后字节不变，不要自行重新保存原始文件；含凭据或私人联系方式的响应不要直接公开，先停交并记录问题，处理方式需说明，不能改了响应还称其原样保存。

模板中的 null 表示待填写，不是合格结果。计数要解释：列表返回条数（含重复）、不同来源 ID 数、输出记录数、排除数、待复核/拒绝数、失败请求数。各去向按唯一 ID 核对；重复请求数另计，无法识别 ID 的失败另列，不能强行相加。

## 5. 怎么提交给组长

1. 在各自 feature 分支写采集器、填来源目录 README，按生成的目录放数据。
2. 完成自检；运行 `git status --short`，确认只包含本人代码和本次批次，不包含密码、虚拟环境、数据库文件。
3. 用具体路径暂存：`git add collectors/tencent data/tencent/<实际批次编号>`（B 改为 netease），然后 commit、push 自己的分支。
4. 在 GitHub 发起到 main 的 PR，写明来源、批次编号、实际条数、缺口和执行命令，附该批次 README 链接。未完成的可以开 Draft PR，但不能标验收通过。
5. C 检查格式、哈希、去重和入库；D 抽检正文和指标字段，A/B 交叉检查原文。通过后在批次 README 与 manifest 同步记录接受结论，再合并。组长 `git pull` 即得到代码和完整数据。

首批必须能追溯每条岗位、哈希一致、无同批重复、无正文错配，且目录文件齐全。技术和数据问题修复后复验；先通过小批联调，才启动扩量及每日快照。

原始响应按请求存小文件，不把全部页面合成大文件。本项目单文件达到 50 MiB 即暂停提交并评估拆分或 Git LFS；GitHub 普通 Git 单文件上限 100 MiB。扩量前检查仓库体积并决定是否迁移大文件到 Git LFS，本次未启用 LFS，也不承诺不限量存储。

## 6. C 生成的交接数据

`data/derived/` 保存带来源哈希、映射规则及范围版本的加工结果。当前交接见[腾讯 C/D v1.1](derived/tencent/tencent_20261031T093102Z_366ad0a4/cd_v1.1/README.md)。采集成员提交原始批次，C 更新派生目录，D 从派生目录读取补充字段后在自己的分支提交分析结果。
