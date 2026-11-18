# 页面、状态与 API 模式

## 复杂页面保留可见骨架

```text
src/
  components/ui/              # 通用 UI 基元
  pages/WorkReport/
    index.tsx                 # 组合筛选区、汇总区和记录列表
    useWorkReport.ts          # 页面共享查询与交互
    buildReportRows.ts        # 响应数据和筛选条件 → 展示行
    ReportFilters.tsx
    ReportSummary.tsx
    ReportResults.tsx
```

入口可以调用 `useWorkReport()` 得到请求状态与筛选条件，再用 `buildReportRows(records, filters)` 算出结果区需要的数据。页面共享逻辑放在页面层。只有内部复杂度明显增加的区域才拆子目录，单一职责的小页面可留在一个组件文件中。

## 核心数据和快照

采用 Zustand 的项目可以通过具名接口封装跨页面共享的客户端状态：

```text
私有 preferencesStore
  useReportPreferences()       → 组件订阅
  getReportPreferencesSnap()   → 用户点击导出时读取瞬时值
  setReportPreferences(next)   → 更新核心数据

buildReportRows(records, filters) → 纯转换
```

只有用到快照的交互才需要提供快照函数。共享 hook 可以复用行为并分别持有各自的局部状态。已有查询缓存时，服务端记录由查询缓存负责，前端 store 留给确需共享的客户端状态。

## 对接 Python 后端

```text
WorkReportPage
  → src/apis/reports/getWorkReport.ts          # 业务调用器
  → src/api/transport.ts                      # 请求发送、鉴权材料和公共错误映射
  → GET /reports/work                         # 稳定 HTTP 契约
  → Python reports 路由和响应模型
  → 工时聚合函数或表查询
```

- 已有请求类时，构造函数只接收输入，`send()` 才发请求。使用稳定路径或集中维护的操作标识，显式组装路径参数、查询参数或请求体。类名可以沿用前端的业务命名。
- 以公开端点声明的字段名、缺失和可空语义、时间格式、响应状态及错误形态为准。使用 FastAPI 等生成 OpenAPI 的框架时，优先从项目的 schema 获取或核对传输类型。内部 Python 函数和数据类由后端独立演进。
- 通用传输按项目约定发送凭证。前端权限状态可用于呈现界面，后端依据可信身份校验资源访问。仅对实际公开给页面的端点提供前端调用器。
