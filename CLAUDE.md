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
