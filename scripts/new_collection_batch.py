"""Create an empty, auditable collection handoff; never overwrite a batch."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def create_batch(root: Path, source: str, owner: str) -> Path:
    if (source, owner) not in {('tencent', 'A'), ('netease', 'B')}:
        raise ValueError('Use tencent/A or netease/B; new sources require approval.')
    batch_id = f"{source}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid4().hex[:8]}"
    dest = root / 'data' / source / batch_id
    dest.mkdir(parents=True, exist_ok=False)
    (dest / 'raw').mkdir()
    (dest / 'raw' / '.gitkeep').write_text('', encoding='utf-8', newline='\n')
    for name in ('jobs.jsonl', 'requests.jsonl', 'quality_issues.jsonl'):
        (dest / name).write_text('', encoding='utf-8', newline='\n')
    manifest = {
        'schema_version': '1.0', 'scope_version': 'digital_jobs_cn_v1',
        'phase': 'pilot', 'source': source, 'owner': owner, 'batch_id': batch_id,
        'started_at': None, 'finished_at': None,
        'collector_commit': None, 'parser_version': None,
        'query_spec': {'endpoints': [], 'parameters': [], 'page_sequence': [],
                       'selection_rule': None, 'pagination_basis': None},
        'coverage_status': 'partial', 'stop_reason': None,
        'acceptance_status': 'pending', 'supersedes_batch_id': None,
        'counts': {key: None for key in (
            'requests', 'failed_requests', 'list_pages', 'raw_response_files',
            'listed_records', 'unique_source_ids', 'output_records',
            'excluded_unique_ids', 'unresolved_unique_ids', 'unidentified_records')},
        'error_pages': [], 'files': [],
    }
    (dest / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    (dest / 'README.md').write_text(f'''# {batch_id}

状态：待采集、待验收。此目录由工具初始化，不是真实采集结果。

- 来源：{source}；负责人：{owner}（提交时补姓名）
- 规范：1.0；范围：digital_jobs_cn_v1；阶段：pilot
- 实际执行命令/依赖/代码 commit：待填
- 来源及字段映射：见 ../../../collectors/{source}/README.md
- 实际数量、范围、分页及停止原因：待填
- 访问规则与缺失/冲突/失败说明：待填

## 自检

- [ ] 所有文件是真实采集结果，所有 manifest 待填项已处理
- [ ] jobs 字段、类型、时区符合规范，同批 ID 唯一
- [ ] manifest.files 清单、字节数、SHA-256 全部核对
- [ ] 每条 raw_refs 能定位原始响应，正文未错配或混入广告
- [ ] 无凭据/私人联系方式，无超大文件
- [ ] 已按唯一 ID 解释输出、排除和待复核去向

## 人工抽检（至少 20 条，不足全检）

抽样方法：待填；覆盖不同页、类别、地点和异常。

| 来源岗位 ID | 原始文件及定位 | 标题/地点/正文核对 | 冲突或缺失 | 结果及检查人 |
| --- | --- | --- | --- | --- |

## 验收

结论：pending；验收人/日期：待填。数据验收与技术联调分别说明；
小批通过不代表全量覆盖，不允许据此计算岗位下架。
问题、修正 commit、复验结果：待填。
''', encoding='utf-8', newline='\n')
    return dest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=['tencent', 'netease'], required=True)
    parser.add_argument('--owner', choices=['A', 'B'], required=True)
    args = parser.parse_args()
    print(create_batch(Path(__file__).resolve().parents[1], args.source, args.owner))
