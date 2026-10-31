-- D 的只读候选，未做真实 SQL Server 执行验证。
-- 前置：C 的 feature/warehouse 已部署，且同一修订批次已入试验库。
-- 不安装数据库，不创建持久表，不改变源数据或仓内状态。
SET NOCOUNT ON;
DECLARE @batch_id nvarchar(128) = N'tencent_20261031T093102Z_366ad0a4';
DECLARE @jobs TABLE (
    source nvarchar(64), source_job_id nvarchar(128), batch_id nvarchar(128),
    category_raw nvarchar(200), education_raw nvarchar(200), experience_raw nvarchar(200),
    has_body bit, locations_json nvarchar(max),
    PRIMARY KEY (source, source_job_id, batch_id)
);

-- PRIMARY KEY 让接口粒度错误直接失败，而非用 DISTINCT 静默掩盖重复。
INSERT INTO @jobs
SELECT j.source, j.source_job_id, j.batch_id, j.category_raw, j.education_raw, j.experience_raw,
       CASE WHEN NULLIF(LTRIM(RTRIM(COALESCE(p.description_raw,N''))),N'') IS NOT NULL
                  OR NULLIF(LTRIM(RTRIM(COALESCE(p.requirements_raw,N''))),N'') IS NOT NULL THEN 1 ELSE 0 END,
       p.locations_raw
FROM ads.trial_job_detail AS j
CROSS APPLY OPENJSON(j.content_json) WITH (
    description_raw nvarchar(max) '$.description_raw',
    requirements_raw nvarchar(max) '$.requirements_raw',
    locations_raw nvarchar(max) '$.locations_raw' AS JSON
) AS p
WHERE j.batch_id=@batch_id AND j.source=N'tencent';

IF NOT EXISTS (SELECT 1 FROM @jobs)
    THROW 51000, N'试验接口无此批次；先核对C的输入版本和部署状态。', 1;

DECLARE @total bigint=(SELECT COUNT_BIG(*) FROM @jobs);
DECLARE @body bigint=(SELECT COUNT_BIG(*) FROM @jobs WHERE has_body=1);
SELECT @batch_id AS batch_id, @total AS source_posting_count, @body AS parseable_body_count,
       1.0*@body/NULLIF(@total,0) AS body_coverage;

-- 城市先按岗位去重；空数组/null进未知，多地点总和可能超过全局岗位数。
SELECT city, COUNT_BIG(*) AS posting_count, @total AS denominator
FROM (
    SELECT DISTINCT j.source, j.source_job_id, j.batch_id,
           COALESCE(c.value,N'未知') AS city
    FROM @jobs AS j OUTER APPLY OPENJSON(j.locations_json) AS c
) AS city_postings
GROUP BY city ORDER BY posting_count DESC, city;

SELECT COALESCE(category_raw,N'未知') AS category_raw, COUNT_BIG(*) AS posting_count,
       @total AS denominator, 1.0*COUNT_BIG(*)/NULLIF(@total,0) AS share
FROM @jobs GROUP BY category_raw;
SELECT COALESCE(education_raw,N'未知') AS education_raw, COUNT_BIG(*) AS posting_count,
       @total AS denominator FROM @jobs GROUP BY education_raw;
SELECT COALESCE(experience_raw,N'未知') AS experience_raw, COUNT_BIG(*) AS posting_count,
       @total AS denominator FROM @jobs GROUP BY experience_raw;

-- 后半段需要调用者把 skill_evidence.jsonl 解析后组成 JSON 数组，用参数绑定传入。
-- 例 Python: json.dumps([json.loads(line) for line in handle], ensure_ascii=False)
-- 不把文件路径、正文或凭据拼接成 SQL；下面 NULL 仅是待绑定的模板值。
DECLARE @skills_json nvarchar(max)=NULL;
IF @skills_json IS NULL
BEGIN
    PRINT N'基础岗位核对完成；未绑定技能JSON，跳过技能核对。';
    RETURN;
END;
IF ISJSON(@skills_json)<>1 OR LEFT(LTRIM(@skills_json),1)<>N'['
    THROW 51001, N'技能输入必须为JSON数组。', 1;

DECLARE @evidence TABLE (
    source nvarchar(64), source_job_id nvarchar(128), batch_id nvarchar(128),
    skill_name nvarchar(200), requirement_level nvarchar(20), context_polarity nvarchar(20),
    eligible_for_metric bit, dictionary_version nvarchar(64), rule_version nvarchar(64)
);
INSERT INTO @evidence
SELECT * FROM OPENJSON(@skills_json) WITH (
    source nvarchar(64), source_job_id nvarchar(128), batch_id nvarchar(128),
    skill_name nvarchar(200), requirement_level nvarchar(20), context_polarity nvarchar(20),
    eligible_for_metric bit, dictionary_version nvarchar(64), rule_version nvarchar(64)
);
IF EXISTS (
    SELECT 1 FROM @evidence AS e WHERE e.dictionary_version<>N'skills-dict-0.1.0'
       OR e.rule_version<>N'skills-rules-0.2.0' OR e.dictionary_version IS NULL OR e.rule_version IS NULL
       OR e.skill_name IS NULL OR e.requirement_level NOT IN (N'必需',N'优先',N'提及',N'不确定')
       OR e.requirement_level IS NULL OR e.context_polarity NOT IN (N'positive',N'negated',N'alternative',N'uncertain')
       OR e.context_polarity IS NULL OR e.eligible_for_metric IS NULL
       OR NOT EXISTS (SELECT 1 FROM @jobs AS j WHERE j.source=e.source AND j.source_job_id=e.source_job_id AND j.batch_id=e.batch_id)
)
    THROW 51002, N'技能版本、字段或岗位引用不符；禁止混用批次/规则。', 1;
IF EXISTS (
    SELECT 1 FROM @evidence WHERE eligible_for_metric<>
    CASE WHEN context_polarity=N'positive' AND requirement_level IN (N'必需',N'优先',N'提及') THEN 1 ELSE 0 END
)
    THROW 51003, N'技能有效标记与语境/强度不一致。', 1;

DECLARE @valid TABLE (
    source nvarchar(64), source_job_id nvarchar(128), batch_id nvarchar(128),
    skill_name nvarchar(200) COLLATE Latin1_General_100_BIN2,
    PRIMARY KEY(source,source_job_id,batch_id,skill_name)
);
INSERT INTO @valid
SELECT DISTINCT e.source,e.source_job_id,e.batch_id,e.skill_name
FROM @evidence AS e JOIN @jobs AS j
  ON j.source=e.source AND j.source_job_id=e.source_job_id AND j.batch_id=e.batch_id
WHERE j.has_body=1 AND e.eligible_for_metric=1;

SELECT skill_name, COUNT_BIG(*) AS posting_count, @body AS denominator,
       1.0*COUNT_BIG(*)/NULLIF(@body,0) AS share
FROM @valid GROUP BY skill_name ORDER BY posting_count DESC,skill_name;

SELECT a.skill_name AS skill_a,b.skill_name AS skill_b,COUNT_BIG(*) AS posting_count,
       @body AS denominator,1.0*COUNT_BIG(*)/NULLIF(@body,0) AS share
FROM @valid AS a JOIN @valid AS b
  ON a.source=b.source AND a.source_job_id=b.source_job_id AND a.batch_id=b.batch_id
 AND a.skill_name<b.skill_name
GROUP BY a.skill_name,b.skill_name ORDER BY posting_count DESC,skill_a,skill_b;
