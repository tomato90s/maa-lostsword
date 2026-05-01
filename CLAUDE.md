# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Design Context

### Users
- macOS 游戏玩家，在 Apple Silicon Mac 上运行 iOS App on Mac 的 StarSavior
- 工具作为游戏窗口旁边的辅助面板常驻，用户边玩边看
- 核心需求：快速查看任务状态、连接状态、截图，偶尔调整设置
- 使用环境：屏幕空间有限（与游戏窗口并排），需要信息一目了然

### Brand Personality
- **简约** — 每一个元素都有存在的理由，没有装饰性噪音
- **干净** — 清晰的视觉层次，信息密度适中，不拥挤
- **克制** — 颜色使用克制，accent 色极少且精准，不追求"酷炫"

### Aesthetic Direction
- 暗色主题为主，但拒绝廉价的纯黑+灰组合
- 精致的层次：通过微妙的阴影、border 透明度、背景色阶来区分层级
- 类似 macOS 原生应用的暗色变体（如 Xcode Dark、Safari 的暗色模式）
- 不是 Discord/VS Code 的工具感，而是更偏向 Apple 的精致暗色
- 拒绝：霓虹色、渐变文字、玻璃拟态、卡片嵌套卡片

### Design Principles
1. **空间即信息** — 用间距和留白来分组，减少边框和背景色的使用
2. **一屏可见** — 辅助面板空间有限，所有关键信息应在不滚动的情况下可见
3. **动效即反馈** — 状态变化需要即时、克制的动效反馈，但不过度
4. **颜色即层级** — 用品牌色的饱和度和明度差异来引导视觉焦点，而不是装饰
5. **字体即结构** — 清晰的字号层级（大标题/小节/正文/辅助），不用靠颜色来区分

---

## MAA Pipeline 设计原则

### 1. 状态机即循环
流程控制靠 `next` + `[JumpBack]`，而非线性链条。父节点定义状态列表，子节点执行后 JumpBack 回来形成循环。

### 2. 顺序即优先级
`next` 数组的**先后顺序就是匹配优先级**。最前面放期望终态，中间放可恢复中间态，最后放兜底终止。框架只执行**第一个匹配成功**的节点。

### 3. 节点即状态
用 `DisableNode` 和 `NodeOverride` 做动态状态管理：
- 节点完成使命后自毁（如 ReturnMain 识别到主页后禁用自己）
- 任务开始前重置被禁用的节点
这替代了复杂的条件分支语法。

### 4. 识别优先于坐标
能模板匹配就不盲点点。通用操作（BackButton、HomeButton、CloseX）必须识别到才执行，固定坐标点击只作为最后兜底。复杂场景用 `And`/`Or`/`ColorMatch` 组合识别。

### 5. max_hit 是安全阀
循环节点必须设 `max_hit`，值宜小（2~20）。它的作用仅是防止死循环，业务终止靠识别条件自然触发。

### 6. 通用复用，专用隔离
- 通用节点（返回、主页、关闭、跳过）集中维护，全项目引用
- 专用逻辑（竞技场、副本、活动）各自隔离在独立文件
- 不重复造轮子

### 7. 等待即策略
充分考虑游戏动画和转场：
- 页面切换 → `post_delay: 1500~3000`
- 加载检测 → `post_wait_freezes` 配合 ROI
- "点完就跑"会导致识别旧页面状态

### 8. 自我注释
复杂节点必须写 `desc` 说明设计意图，关键识别失败用 `focus` 输出调试信息。Pipeline 是给人读的设计文档，不只是机器配置。

---

## MAA Pipeline 节点命名规范

参考 M9A 实践，节点命名遵循以下规则：

### 核心原则
- **全英文 PascalCase**，不用中文节点名
- **中文意图写在 `desc`**，不靠名字塞语义
- **循环/自毁/终止不靠命名表达**，靠 `max_hit` / `DisableNode` / `Stop`

### 全局唯一性

- **所有节点名必须全局唯一**，跨文件也不能重复
- **模块前缀是强制要求**：`Arena_` / `Instance_` / `Bank_` 等
- 通用节点（如 `ReturnMain`、`BackButton`）可跨文件引用，但不得重复定义

### 模式速查

| 模式 | 示例 | 含义 |
|------|------|------|
| **动词+名词** | `ClickChallenge`, `CloseArenaPopup`, `EnterBank` | 执行动作 |
| **XxxButton** | `BackButton`, `HomeButton`, `SkipButton` | 识别并点击通用按钮 |
| **XxxFlag** | `HomeFlag`, `ArenaHomeFlag`, `FlagInBank` | 状态/地标检测，通常只做识别 |
| **模块前缀** | `Arena_MenuClick`, `BankPurchase_Rabbit` | 业务隔离，全局唯一 |
| **NoXxx** | `NoFree`, `NoRabbit` | "资源不存在"，常触发 DisableNode |
| **Sub_Xxx** | `Sub_MailBadge`, `Sub_CollectJukebox` | 子流程入口 |
| **XxxTrue/False** | `ReturnMainStoryChapterTrue` | 条件分支 |
| **XxxFirst** | `HomeFlagFirst`, `ClosePageFirst` | 首次专用版本 |
| **XxxWithDelay** | `BackButtonWithDelay` | 带延迟的变体 |
| **Xxx_wait** | `HomeLoading_wait` | 等待专用版本 |
| **Stop** | `Stop` | 空节点，显式终止 |

### 禁止
- 不用 `_Once`、`_Loop`、`_Terminate` 后缀
- 不用纯中文节点名
- 不在名字里堆砌功能描述（如 `HomeFlagCloseReturnMain` 是反例）
