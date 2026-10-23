# film-story

人机协同的连续剧剧情开发与改稿。设计依据与试跑见 `/Users/sky/Desktop/Film/offset/_film-story/`（00 核心判断 → 01 诊断 → 04 流程 → 05 试跑）。2026-10-18 起取代 film-creative；分镜与 Prompt 仍归 film-director。

## 第一次用在一个项目上
1. 建 `<项目>/story/`，从 `templates/` 复制 `ledger.md`、`decisions.md`、`constraints.md`。
2. 让 AI 从已拍 / 已采用的正典整理台账（季卡只定三项；事实注明出处；伏笔写明涉及人物与关系、可引出的选择、最晚回收点）；你逐条确认。术语见 `references/glossary.md`。
3. 之后每次任务：处境卡 → 方向卡 → 节拍单 → 场次表 → 一场一场写（每场附检验，你采用或改定后再写下一场）→ 记录。往下走之前上一层要有内容；同一层被否两次回上一层（场景按场计）。

## 调用
Claude Code 里 `/film-story`，或直接说"下一集写什么 / 这段戏怎么接 / 这版哪里不对"。

## 脚本
```bash
python3 ~/.claude/skills/film-story/scripts/check_dialogue.py <场景.md>
```
```bash
python3 ~/.claude/skills/film-story/scripts/check_constraints.py <场景.md> --constraints <项目>/story/constraints.md
```

## 状态
试用版；对照验证未运行（`validation/protocol.md`）。模块的删除条件在 `SKILL.md` §8。
