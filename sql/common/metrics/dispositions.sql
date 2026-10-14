SELECT origin, disposition, COUNT(*) AS n
FROM case_dispositions_current
GROUP BY origin, disposition
