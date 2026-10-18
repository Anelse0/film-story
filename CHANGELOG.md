# Changelog

## 0.1.0 — 2026-10-18

首个版本。基于 Offset / FAMILIARS 真实材料的诊断（`offset/_film-story/01_瓶颈诊断.md`）、职业编剧一手材料与 AI 协同写作实证的调研（`02`、`03`）设计；取代 film-creative 承担故事层工作。

- `SKILL.md`：五个工作对象（账本含季卡、处境卡、方向卡、节拍单、场景稿）+ 决策记录；入口可在任一层，往下走前上一层要有内容；同一层被否两次回上一层；对白三测；改稿先定层级；分工表；模块删除条件；取代 film-creative 的约定。
- `templates/`：账本、处境卡、方向卡、节拍单、场景头部、改稿单、约束、决策记录。
- `scripts/check_dialogue.py`：问答对接链、疑似金句、解释 / 复述标记、回声句、括号情绪标签、台词秒数（只给线索）；`scripts/check_constraints.py`：未登记人物、禁用词、头部必填、同框人数。
- `references/`：why（问题 → 模块 → 依据）、dialogue-patterns（AI 对白四种固定失误的真实例子）、production-constraints（AI 视频制作约束怎样进剧本层）。
- `validation/`：对照协议、读者理解探测、评阅表、尝试记录。
- 验证状态：Offset EP06 非盲试跑一次（`offset/_film-story/trial/`）；对照实验未运行。
