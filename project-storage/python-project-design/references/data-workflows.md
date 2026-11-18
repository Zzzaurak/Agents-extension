# 脚本与数据工作流

让输入解析、计算和写出有清楚的调用顺序。CLI 的 `main()` 可以负责参数、文件、退出码和错误提示，分析函数接收解析后的记录或表。仅有数十行的小工具可以把它们放在同一个文件里。

例如，对于已经过输入校验的工时记录，可以直接表达聚合：

```python
from dataclasses import dataclass
from enum import Enum


class ReviewStatus(Enum):
    APPROVED = "approved"
    PENDING = "pending"


@dataclass(frozen=True)
class WorkEntry:
    minutes: int
    status: ReviewStatus


def approved_minutes(entries: tuple[WorkEntry, ...]) -> int:
    return sum(
        entry.minutes
        for entry in entries
        if entry.status is ReviewStatus.APPROVED
    )
```

数据在数据库中时，可以用 SQL 执行适合下推的筛选、分组和聚合。处理本地文件或跨来源数据时，按现有依赖选择工具。已有 Polars 的项目可用惰性表达式描述筛选和聚合，在 `collect()` 时执行。小规模数据用标准库即可。

报表和批处理的契约通常在数据口径上。指出如何处理空输入、缺失字段、重复记录、时区和舍入中确实影响结果的项。依据任务验证这些边界，并用少量代表数据检查端到端解析和输出。
