TITLE='商圈客流设备重叠与人数区间估计'
SHORT='footfallbounds'
# 当前采信规则版本。历史版本仅用于并列重述与旧证据复核，不得就地改写。
RULE_VERSION='2026.11.18-v2'
LEGACY_RULE_VERSION='2026.11.17-v1'
RULE_VERSION_HISTORY=('2026.11.17-v1','2026.11.18-v2')
MODULES=[('m1_ingest', '设备采信'), ('m2_mapping', '区域映射'), ('m3_versions', '观测分桶'), ('m4_segments', '重叠约束'), ('m5_calculate', '人数估界'), ('m6_reconcile', '日汇对账'), ('m7_archive', '报告归档')]
REQUIRED=['id', 'bucket', 'version', 'kind', 'left', 'count', 'unit']
NUMERIC=['version', 'count']
DATES=[]
TIMES=['bucket']
# 采信时用于判断“同一条观测”的业务字段；备注类字段不参与业务同一性判断。
BUSINESS_FIELDS=tuple(REQUIRED)+('right',)
