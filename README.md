# film-story

人机协同的连续剧剧情开发与改稿。2026-10-18 起取代 film-creative；分镜与 Prompt 仍归 film-director。方法的公开出处见 `references/sources.md`，为什么是这几个模块见 `references/why.md`。

## 第一次用在一个项目上
1. 建 `<项目>/story/`，从 `templates/` 复制 `ledger.md`、`story-framework.md`（存为 `framework.md`）、`rules.md`、`decisions.md`、`constraints.md`。本剧规则表头几集可以很薄，每集采用后从你的纠正里补（`SKILL.md` 第 6 步）。约束文件的 `## 制作参数` 填上语速和单条生成上限，脚本才估秒数。
2. 让 AI 从已拍 / 已采用的正典整理台账（季卡只定三项；事实注明出处；伏笔写明涉及人物与关系、可引出的选择、最晚回收点）；你逐条确认。再让 AI 起草故事框架卡（中心论点一行、信念弧、引擎、支柱集落点、每集一句话；只写落点不写手段，`references/story-framework.md`）；进行中的剧补一张，先倒填已拍各集；在框架卡第 6 节选题材手册（`references/genre-playbooks/index.md`，可叠两本）。术语见 `references/glossary.md`。
3. 之后每次任务：先读本剧规则与框架卡 → 处境卡（引用框架卡）→ 方向卡 → 节拍单 → 场次表 → 一场一场写（每场附检验与批注依据，你采用或改定后再写下一场）→ 改稿先定位、按故障选修改幅度、写前后对照 → 记录（一集采用后把纠正起草成规则）。往下走之前上一层要有内容；同一层被否两次回上一层（场景按场计）。

## 调用
Claude Code 里 `/film-story`，或直接说"下一集写什么 / 这段戏怎么接 / 这场写不下去 / 这句不像他会说的 / 这版哪里不对"。

## 脚本
两个脚本都只读 `<!-- script-body:start -->` 与 `<!-- script-body:end -->` 之间的正文（没有标记的旧文件按全文读，并提示）；只报线索，退出码恒为 0。

```bash
python3 ~/.claude/skills/film-story/scripts/check_dialogue.py <场景.md>
```
```bash
python3 ~/.claude/skills/film-story/scripts/check_constraints.py <场景.md>
```

- 约束文件：不给 `--constraints` 时，从场景文件所在目录往上找 `story/constraints.md`。
- 语言：`--lang auto|en|zh`，默认按全文多数台词判断，另一种语言的行算对照翻译。中文不支持的线索（与上一句实词重合）会在输出里写明。
- 时长：读约束文件的 `## 制作参数`（英文语速、中文语速、单条生成上限）；`--wps` / `--cps` 临时指定；都没有就只报词数或字数。估的是口播时长，不是成片时长。
- 说话人分画内 / 画外（角色名或括注里有电话里、画外、旁白、V.O. 等）；同框人数要看动作描写，脚本不推算。
- 0.8.0 起的结构线索：等长对仗 / 排比、接住上一句的词反问（中英文都给）；复述确认也会被标，是否算问题看处境（`references/dialogue-patterns.md` §5）。

## 测试
```bash
bash ~/.claude/skills/film-story/tests/run_tests.sh
```
检查 SKILL.md 的名字与版本号、CHANGELOG、SKILL.md / README / 参考 / 模板里引用的文件是否存在，并跑脚本的回归用例（`tests/fixtures/`）。

## 状态
试用版；对照验证未运行（`validation/protocol.md`）。0.8.0 加的四层（故事框架卡、节拍单的三问与转向、对白生成法与脚本新线索、题材手册）只在两部剧的已采用稿和被否稿上做过回填复核，前瞻检验等下一集真的写一遍。模块的删除条件在 `SKILL.md` §8。
