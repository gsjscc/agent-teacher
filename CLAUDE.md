# 项目说明

## 浏览器工具使用规范

- 优先使用 `get_page_text` / `read_page` 直接读取页面文字内容，减少交互轮次和 token 消耗
- 非必要不要截图（`computer` 的 screenshot/zoom）；确需截图时，先告知用户原因再截
- 能一次性用 `browser_batch` 批量执行的点击/输入/导航操作，尽量合并成一次调用，不要逐步单独调用
