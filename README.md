# 商圈客流设备重叠与人数区间估计

面向商场经营数据分析员，处理采信、判定、核算、复核与归档。

## 启动

```bash
docker compose up --build -d
```

访问 http://localhost:18251 。初次启动自动运行脏样例，可切换 clean.csv、legacy.csv 与 restated.csv。同源同规则输入复用同一批次。

## 业务模块

- 设备采信：`/m1_ingest`、`/api/m1_ingest`
- 区域映射：`/m2_mapping`、`/api/m2_mapping`
- 观测分桶：`/m3_versions`、`/api/m3_versions`
- 重叠约束：`/m4_segments`、`/api/m4_segments`
- 人数估界：`/m5_calculate`、`/api/m5_calculate`
- 日汇对账：`/m6_reconcile`、`/api/m6_reconcile`
- 报告归档：`/m7_archive`、`/api/m7_archive`

## 核心规则

无法识别个人时只输出满足区域交集约束的人数上下界；矛盾观测隔离而非伪造精确人数。完整数值、边界和异常定义见 `docs/DATA-DICTIONARY.md`。

## 验证

```bash
docker compose exec -T app pytest -q
docker compose config --quiet
```

原始样例在 `sample_data/`。测试在 `tests/`。封存文件是单份CSV，含运行清单、计算证据、隔离原因与对账。复核需提交当前版本，陈旧复核返回409。

## 规则版本与历史数据

规则版本贯穿采信、观测取舍、人数估界与归档。历史数据采用**并列重述**：

- 已签发批次只读回放，导出按原格式逐字节重现原指纹；不按新规则改写旧证据。
- 规则升级后用 `/api/runs/restate` 从旧批次原样字节生成并列新批次；同源键相同、`run_id` 不同。
- 同源同规则重跑命中同一批次，不新增重复结果。
- 跨版本批次不能合并成日汇总（`RULE_MIX`）；归档 CSV 每条记录都带规则版本。

当前规则：`2026.11.18-v2`（同版记录只比较业务字段，备注差异只算重复）。历史规则：`2026.11.17-v1`（整行比较）。版本登记见 `/api/rules` 与 `app/rulebook.py`。

## 数据与限制

SQLite保存在records命名卷，普通重启与构建不会清除。确认可丢弃本项目数据后，运行 `docker compose down -v` 再启动可重置。单文件上限2MB；不接入外部业务系统；历史规则由本项目样例定义，不代表实际行业标准。
