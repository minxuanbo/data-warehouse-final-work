"""批次 README 与清单复核：把真实计数、抽检证据和待验收状态写回批次目录。"""
import json
import random
from collections import Counter
from pathlib import Path

from .batch import count_nonempty_lines, sha256_file

SPOT_SEED = 20261101


def _load_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _item_at(batch, meta):
    payload = json.loads((batch.path / meta["list_path"]).read_text(encoding="utf-8"))
    return payload["data"]["list"][meta["index"]]


def _raw_check(row, item):
    """把 jobs 记录与列表原始对象逐字段回读，返回不一致项。"""
    checks = (
        ("source_job_id", str(item.get("id"))),
        ("title_raw", (item.get("name") or "").strip() or None),
        ("category_raw", (item.get("firstPostTypeName") or "").strip() or None),
        ("education_raw", (item.get("reqEducationName") or "").strip() or None),
        ("experience_raw", (item.get("reqWorkYearsName") or "").strip() or None),
        ("description_raw", (item.get("description") or "").strip() or None),
        ("requirements_raw", (item.get("requirement") or "").strip() or None),
    )
    problems = []
    for key, expected in checks:
        if row.get(key) != expected:
            problems.append(key)
    expected_locations = [str(part).strip() for part in (item.get("workPlaceNameList") or [])
                          if str(part).strip()] or None
    if row.get("locations_raw") != expected_locations:
        problems.append("locations_raw")
    return problems


def _issue_map(batch):
    found = {}
    for issue in _load_jsonl(batch.path / "quality_issues.jsonl"):
        job_id = issue.get("source_job_id")
        if job_id is None:
            continue
        found.setdefault(job_id, []).append(f"{issue['rule']}: {issue['message']}")
    return found


def _detail_map(batch):
    found = {}
    for path in sorted((batch.path / "raw").glob("detail_*.json")):
        found[path.name] = path
    return found


def _distribution(rows):
    categories = Counter(row["category_raw"] or "（空）" for row in rows)
    locations = Counter(loc for row in rows for loc in (row["locations_raw"] or ["（空）"]))
    education = Counter(row["education_raw"] or "（null）" for row in rows)
    experience = Counter(row["experience_raw"] or "（null）" for row in rows)
    work_types = Counter(row["employment_type_raw"] or "（null）" for row in rows)
    missing = {
        "地点为空": sum(1 for row in rows if not row["locations_raw"]),
        "职责为空": sum(1 for row in rows if not row["description_raw"]),
        "要求为空": sum(1 for row in rows if not row["requirements_raw"]),
        "学历为 null": sum(1 for row in rows if not row["education_raw"]),
        "人数为 null": sum(1 for row in rows if not row["headcount_raw"]),
    }
    return categories, locations, education, experience, work_types, missing


def _counter_line(counter):
    return "、".join(f"{name} {count}" for name, count in counter.most_common())


def verify_manifest(batch):
    """按 manifest.files 重新计算字节数与 SHA-256，返回不一致项。"""
    problems = []
    for entry in batch.manifest.get("files") or []:
        target = batch.path / entry["path"]
        if not target.exists():
            problems.append(f"缺失文件：{entry['path']}")
            continue
        if target.stat().st_size != entry["bytes"]:
            problems.append(f"字节数不一致：{entry['path']}")
        if sha256_file(target) != entry["sha256"]:
            problems.append(f"SHA-256 不一致：{entry['path']}")
        if entry.get("records") is not None:
            if count_nonempty_lines(target) != entry["records"]:
                problems.append(f"记录数不一致：{entry['path']}")
    return problems


def write_readme(batch, *, counts, args, parser_version, commit, rows, metas,
                 detail_results, stop_reason, detail_skipped=False, restriction_stage=None):
    issues = _issue_map(batch)
    categories, locations, education, experience, work_types, missing = _distribution(rows)

    rng = random.Random(SPOT_SEED)
    spot_indices = sorted(rng.sample(range(len(rows)), min(20, len(rows))))
    spot_lines = []
    for index in spot_indices:
        row, meta = rows[index], metas[index]
        problems = _raw_check(row, _item_at(batch, meta))
        notes = issues.get(row["source_job_id"], [])
        note = "；".join(notes) if notes else "无"
        if row["source_job_id"] in detail_results:
            note += "；已抽查详情"
        result = "回读一致（待人工复核）" if not problems else f"回读不一致：{','.join(problems)}"
        spot_lines.append(
            f"| {row['source_job_id']} | {meta['list_path']}#/data/list/{meta['index']} | "
            f"{row['title_raw']}／{'、'.join(row['locations_raw'] or [])}；"
            f"职责 {len(row['description_raw'] or '')} 字、要求 {len(row['requirements_raw'] or '')} 字 | "
            f"{note} | {result} |"
        )

    detail_lines = []
    for job_id, result in sorted(detail_results.items()):
        if result.get("status") != "ok":
            detail_lines.append(f"| {job_id} | {result.get('list_path', '')} | {result.get('path', '未取得')} | "
                                f"— | 详情请求失败/业务失败：{result.get('message', '')} |")
            continue
        mismatches = result["mismatches"]
        detail_lines.append(
            f"| {job_id} | {result['list_path']} | {result['path']} | "
            f"10 项关键字段 | {'一致' if not mismatches else '；'.join(mismatches)} |"
        )

    accepted_manual = "（自动回读；人工复核由 B 签字）"
    detail_raw_count = len(_detail_map(batch))
    detail_ok_count = sum(1 for item in detail_results.values() if item.get("status") == "ok")
    output_note = "达到 pilot 目标后停止" if counts["output_records"] >= args.target \
        else "翻满页数仍未达到 pilot 目标"
    stop_note = f"本批到 {args.target} 条即停止，属于截取样本。" \
        if counts["output_records"] >= args.target \
        else f"本批翻满 {counts['list_pages']} 页仍未达到 {args.target} 条目标，属于截取样本。"
    restriction_note = {
        "list": "本批列表请求期间触发，已停止后续列表与详情请求",
        "detail": "本批详情抽查期间触发，已停止后续详情请求",
    }.get(restriction_stage, "本批未触发")
    detail_note = "列表阶段已停止，本批未发起详情请求。" if detail_skipped \
        else f"另抽 {len(detail_results)} 条详情核对，成功 {detail_ok_count} 条。"
    source_entries = batch.manifest.get("collector_source") or []
    source_line = "；".join(
        f"`{entry['path']}` `{entry['sha256'][:12]}…`" for entry in source_entries
    ) or "见 `manifest.json` 的 `collector_source`"
    collector_version = batch.manifest.get("collector_version") or parser_version
    collector_commit = batch.manifest.get("collector_commit") or commit or "pending"
    fix_version = batch.manifest.get("collector_fix_version")
    fix_commit = batch.manifest.get("collector_fix_commit")
    fix_source = batch.manifest.get("collector_fix_source") or []
    fix_source_line = "；".join(
        f"`{entry['path']}` `{entry['sha256'][:12]}…`" for entry in fix_source
    )
    fix_line = (
        f"- 修复版本：`{fix_version}`，commit `{fix_commit}`"
        f"（仅修复访问受限与重试逻辑，未重采数据；合并后回填 squash commit）\n"
        if fix_version else ""
    )
    fix_source_line = (
        f"- 修复版本源码校验（SHA-256，UTF-8，LF 换行归一化）：{fix_source_line}\n"
        if fix_source_line else ""
    )
    body = f"""# {batch.batch_id}

状态：**小批采集完成，技术接入与数据验收待 C/D 完成**。本批为截取样本，不能用于全量变化指标或岗位下架判断。

- 来源：netease（网易社会招聘 https://hr.163.com/）；负责人：B（姓名/学号待填）
- 规范：schema v1.0；范围：digital_jobs_cn_v1；阶段：pilot
- 实际执行命令：`python -m collectors.netease --batch-dir data/netease/{batch.batch_id} --target {args.target} --max-pages {args.max_pages} --page-size {args.page_size} --interval {args.interval} --detail-samples {args.detail_samples}`
- 依赖：Python 3.12+，仅标准库（`collectors/netease/requirements.txt`）
- 采集版本：`{collector_version}`，commit `{collector_commit}`（本批数据由该版本生成）
{fix_line}- 采集版本源码校验（SHA-256，UTF-8，LF 换行归一化，前 12 位）：{source_line}
{fix_source_line}- parser_version（数据内）：`{parser_version}`
- 来源及字段映射：见 [collectors/netease/README.md](../../../collectors/netease/README.md)

## 1. 实际数量、范围与停止原因

| 项目 | 数值 | 说明 |
| --- | --- | --- |
| 列表页 | {counts['list_pages']} 页 | currentPage 1—{counts['list_pages']}，pageSize={args.page_size}，不使用关键词 |
| 列表返回条数 | {counts['listed_records']} | 含重复请求；本批跨页重复由 `duplicate_source_id` 登记 |
| 不同来源岗位 ID | {counts['unique_source_ids']} | 接口当页返回的岗位对象总数 |
| 输出记录 | {counts['output_records']} | {output_note} |
| 排除 ID | {counts['excluded_unique_ids']} | 类目/标题/地点不在数字技术范围，`quality_issues.jsonl` 逐条含原因 |
| 待复核（已输出） | {counts['unresolved_unique_ids']} | 已写入 jobs，同时登记 review 问题 |
| 未处理 | {counts['unprocessed_unique_ids']} | 达到 target 时同页剩余，未输出也未排除，下一批可继续 |
| 失败请求 | {counts['failed_requests']} | HTTP 失败或业务状态非成功（含详情重试尝试） |
| 原始响应文件 | {counts['raw_response_files']} | {counts['list_pages']} 个列表 + {detail_raw_count} 个抽查详情 |
| 无法识别 ID | {counts['unidentified_records']} | 列表对象缺少 id 的记录 |

计数核对：{counts['unique_source_ids']} 个不同 ID = {counts['output_records']} 输出 + {counts['excluded_unique_ids']} 排除 + {counts['unprocessed_unique_ids']} 未处理。

未处理的 ID（下一批可继续采，不在本批 jobs 中）：
{('`' + '`、`'.join(counts['unprocessed_ids']) + '`') if counts['unprocessed_ids'] else '无'}

`coverage_status=partial`，`stop_reason={stop_reason}`：{stop_note}

## 2. 范围与分布（仅描述本批样本，不代表网易全部岗位）

- 类目：{_counter_line(categories)}
- 城市（`workPlaceNameList` 展开后）：{_counter_line(locations)}
- 学历原值：{_counter_line(education)}
- 经验原值：{_counter_line(experience)}
- `employment_type_raw`（`workType` 原代码，未译码）：{_counter_line(work_types)}
- 缺失：{'，'.join(f'{name} {value}' for name, value in missing.items())}
- 薪资：接口未披露，{counts['output_records']} 条 `salary_raw=null`，不补造；`headcount_raw` 保留 `recruitNum` 原值字符串。

## 3. 访问规则与异常说明

- 单并发、请求间隔 ≥{args.interval} 秒；网络失败最多重试 {args.retries} 次并退避（单次调用合计最多 {args.retries + 1} 次尝试）。
- 列表与详情均为公开只读接口；未登录、未投递、未使用代理轮换、未绕过访问控制。
- 列表请求 {counts['list_pages']} 页；请求日志共记 {counts['failed_requests']} 次失败（含网络重试尝试，逐条见 `requests.jsonl`）。
- 遇到 HTTP 401/403/418/429 或 HTML 登录/验证码页立即停止（{restriction_note}）。
- 列表已含完整 `description`/`requirement`，未逐条重复请求详情；{detail_note}
- `updateTime` 为来源毫秒时间戳，`source_updated_at_raw` 原样保存其字符串形式，不代表发布时间。
- 标题括号城市与 `workPlaceNameList` 不一致、结构化学历低于正文“X及以上”时，均保留原值并登记 `quality_issues.jsonl`，不静默修正。

## 4. 自检

- [x] 所有文件是真实采集结果；`collector_commit` 待合并后回填，`collector_source` 已记录源码 SHA-256
- [x] jobs 字段、类型、时区符合 v1.0，同批 `(source, source_job_id)` 唯一
- [x] manifest.files 清单、字节数、SHA-256 全部回读核对一致
- [x] 每条 raw_refs 能定位本批 raw 文件，列表响应哈希为 64 位小写
- [x] 正文未混入弹窗/广告；列表原文与 jobs 字段已逐项回读
- [x] 无凭据、私人联系方式、绝对路径；单文件远小于 50 MiB
- [x] 已按唯一 ID 解释输出、排除、待复核和未处理去向
- [ ] 人工抽检 20 条：下表为脚本回读结果，待 B 逐条浏览签字

## 5. 人工抽检（20 条）

抽样方法：固定随机种子 `{SPOT_SEED}` 从 {len(rows)} 条中随机抽 {len(spot_indices)} 条；逐条回读 `raw/list_*.json` 原始对象，对照 `jobs.jsonl` 的 ID、标题、地点、类目、学历、经验、职责与要求；并对抽中的详情样本同时核对列表与详情。{accepted_manual}

| 来源岗位 ID | 原始文件及定位 | 标题/地点/正文核对 | 冲突或缺失 | 结果及检查人 |
| --- | --- | --- | --- | --- |
{chr(10).join(spot_lines)}

检查人签字：__________　日期：__________（自动回读结论不能替代人工抽检）

## 6. 详情抽查核对（{len(detail_results)} 条，成功 {detail_ok_count} 条）

抽样方法：固定随机种子 `{SPOT_SEED}` 抽取，覆盖不同页与类目；比较列表对象与详情对象的标题、类目、地点、学历、经验、职责、要求、招聘人数、招聘类型、更新时间共 10 项。

| 来源岗位 ID | 列表原始文件 | 详情原始文件 | 核对项 | 结果 |
| --- | --- | --- | --- | --- |
{chr(10).join(detail_lines)}

## 7. 验收

结论：pending；验收人/日期：待 C 复核格式、哈希、去重与入库，D 抽检正文与指标字段，A 交叉抽检原文。
数据验收与技术联调分别说明；小批通过不代表全量覆盖，不允许据此计算岗位下架。
问题、修正 commit、复验结果：待填。
"""
    (batch.path / "README.md").write_text(body, encoding="utf-8", newline="\n")
    return body
