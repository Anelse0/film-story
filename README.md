# film-story

人机协同的连续剧剧情开发与改稿。2026-10-18 起取代 film-creative；分镜与 Prompt 仍归 film-director。方法的公开出处见 `references/sources.md`，为什么是这几个模块见 `references/why.md`。

## 第一次用在一个项目上
1. 建 `<项目>/story/`，从 `templates/` 复制 `ledger.md`、`rules.md`、`decisions.md`、`constraints.md`。本剧规则表头几集可以很薄，每集采用后从你的纠正里补（`SKILL.md` 第 6 步）。约束文件的 `## 制作参数` 填上语速和单条生成上限，脚本才估秒数。
2. 让 AI 从已拍 / 已采用的正典整理台账（季卡只定三项；事实注明出处；伏笔写明涉及人物与关系、可引出的选择、最晚回收点）；你逐条确认。术语见 `references/glossary.md`。
3. 之后每次任务：先读本剧规则 → 处境卡 → 方向卡 → 节拍单（Beat Outline：一句话、因果链、谁知道什么，一场一节写拍和试写台词；交付前做对照检查）→ 一场一场把初稿写进这一集的剧本文件（Screenplay：标准剧本格式的 Markdown；每场附检验与批注依据，你采用或改定后再写下一场）→ 重写（改发生了什么；你说结构定了才算完）→ 精修（你发起；我先交精修简报，你确认后做一轮，只动对白、动作描写和留白）→ 改稿先定位、按故障选修改幅度、写前后对照 → 记录（一集采用后把纠正起草成规则）。往下走之前上一层要有内容；同一层被否两次回上一层（场景按场计）。

## 调用
Claude Code 里 `/film-story`，或直接说"下一集写什么 / 这段戏怎么接 / 这场写不下去 / 这句不像他会说的 / 这版哪里不对"。

## 脚本
四个脚本都只读 `<!-- script-body:start -->` 与 `<!-- script-body:end -->` 之间的正文（没有标记的旧文件按全文读，并提示）；只报线索，退出码恒为 0。

```bash
python3 ~/.claude/skills/film-story/scripts/check_dialogue.py <场景.md>
```
```bash
python3 ~/.claude/skills/film-story/scripts/check_constraints.py <场景.md>
```
```bash
python3 ~/.claude/skills/film-story/scripts/render_screenplay.py <剧本.md> --html <整集.html>
```
```bash
python3 ~/.claude/skills/film-story/scripts/compare_drafts.py <旧稿.md> <新稿.md>
```

- 约束文件：不给 `--constraints` 时，从场景文件所在目录往上找 `story/constraints.md`。
- 语言：`--lang auto|en|zh`，默认按全文多数台词判断，另一种语言的行算对照翻译。中文不支持的线索（与上一句实词重合）会在输出里写明。
- 时长：读约束文件的 `## 制作参数`（英文语速、中文语速、单条生成上限）；`--wps` / `--cps` 临时指定；都没有就只报词数或字数。估的是口播时长，不是成片时长。
- 动作描写线索（只在有正文标记的文件上给）：动作段偏长、动作里的心理词、连续对白中间没有动作段。
- 场标记：剧本一集一个文件，每场开头一行 `<!-- S03 · 名字 -->`；检查脚本的输出带场号，文末按场合计台词量。
- 导出：`render_screenplay.py` 不带输出选项时在终端里排出标准版面并报行数、页数；`--scene S03` 只取一场，`--html` 出标准页（Courier 12 pt，可打印成 PDF），`--fountain` 出 Fountain，`--md` 写成 Markdown（Fountain / txt 转入、取出单场、把一场一个文件的旧稿拼成一份）；`--no-translation` 去掉对照翻译行。格式见 `references/screenplay-format.md`。
- 比稿：`compare_drafts.py` 对两版剧本，报结构有没有变（场、场景标题、每场的说话人）和改了哪些句子（台词按"旧句 → 新句"列出）；只给一个文件加 `--rev HEAD` 是和 git 里的那一版比。精修之后"结构"一行应该是干净的。加 `--brief <精修简报.md>` 核对锁定的台词逐字都在，简报里登记了局部重写的场不算越界；加 `--dialogue-only` 只比对白，用来核对两个语言版本。
- 说话人分画内 / 画外（角色名或括注里有电话里、画外、旁白、V.O. 等）；同框人数要看动作描写，脚本不推算。

## 测试
```bash
bash ~/.claude/skills/film-story/tests/run_tests.sh
```
检查 SKILL.md 的名字与版本号、CHANGELOG、SKILL.md / README / 参考 / 模板里引用的文件是否存在，并跑脚本的回归用例（`tests/fixtures/`）。

## 状态
试用版；对照验证未运行（`validation/protocol.md`）。模块的删除条件在 `SKILL.md` §8。
