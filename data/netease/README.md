# netease 数据提交目录

负责人：B。按[采集提交规范](../README.md)创建批次，每个批次一文件夹；不要直接在本目录放 jobs 或零散响应。

在仓库根目录运行：

```powershell
python scripts/new_collection_batch.py --source netease --owner B
```

已验收批次：`netease_20261101T044527Z_157cf969`（100 条，`coverage_status=partial`，`stop_reason=pilot_limit`，`acceptance_status=accepted`，可进入联调）。批次 README 记录实际命令、计数、抽检结果与验收结论；本目录 README 不是验收完成记录。
