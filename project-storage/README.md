# Python 与 React 项目技能

- [Python 项目设计](python-project-design/SKILL.md) 用于日常 Python 应用、API、脚本和数据处理。
- [React 前端规范](react-frontend-design/SKILL.md) 用于 React TypeScript 的页面组织、状态流、样式和 API 契约。

两个技能可以分别使用。全栈项目同时采用时，从 React 页面追到业务调用器和 Python 的公开端点。使用 FastAPI 时，可用 OpenAPI 对齐传输类型。

从外层仓库根目录安装：

```bash
node bin/agents-extension.js install python-project-design react-frontend-design
```

安装后可用 `$python-project-design` 和 `$react-frontend-design` 调用。也可以直接引用各自的 `SKILL.md`。分享时提供对应的整个技能目录，其中包含入口、界面元数据和按需读取的参考。
