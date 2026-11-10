#!/usr/bin/env python3
"""剧本格式转换（film-story）。把正文读成剧本元素，再写成需要的样子；只转换格式，不改一个字。

用法:
  python3 render_screenplay.py <文件…>                      标准版面的纯文本（终端里看）+ 行数、页数
  python3 render_screenplay.py <文件…> --md 整集.md          标准格式的 Markdown（拼整集稿；Fountain / txt 转 Markdown）
  python3 render_screenplay.py <文件…> --html 整集.html      标准页：Courier 12 pt，左 1.5 in、右上下 1 in；浏览器里可打印成 PDF
  python3 render_screenplay.py <文件…> --fountain 整集.fountain  Fountain 纯文本，可导入 Final Draft、Highland 等
  选项：--scene S03[,S04] 只取这几场（按场标记 <!-- S03 · 名字 -->）；--no-translation 去掉对照翻译行
        （只留全文多数台词的那种语言）；--title 指定标题

输入：.md 按剧本文件读（只读 <!-- script-body:start/end --> 之间；没有标记按全文读）；.fountain / .txt 按 Fountain 读。
几个文件按给的顺序接成一份（一场一个文件的旧稿可以这样拼成整集）。元素与写法见 references/screenplay-format.md。
场标记在 Markdown 里是注释行，在 Fountain 里是分节行（# S03 · 名字），标准版面和标准页上不显示。

标准版面（纯文本按格数、标准页按英寸；一格 = 0.1 in）：动作通栏 60 格；对白缩进 10 格、宽 35 格；括注缩进 15 格、
宽 25 格；角色名缩进 20 格；转场靠右；一页约 55 行。页数只是粗估：一页约一分钟是英文剧本的经验值，对照翻译行和
中文动作描写会让页数偏多；口播秒数看 check_dialogue.py。退出码恒为 0。"""
import argparse, html, math, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_dialogue as cd  # noqa: E402

COLS = {'action': (0, 60), 'scene': (0, 60), 'sub': (0, 60), 'character': (20, 38), 'paren': (15, 25),
        'dialogue': (10, 35), 'alt': (10, 35)}
PAGE_LINES = 55
FOUNTAIN_SCENE = re.compile(r'^(?:INT\./EXT|INT/EXT|INT|EXT|EST|I/E)[. ]', re.I)
TITLE_KEY = re.compile(r'^([A-Za-z][A-Za-z ]*):\s*(.*)$')
MD_HEADING = re.compile(r'^(#{1,6})\s+(.+?)\s*#*$')
BOLD_LINE = re.compile(r'^\*\*([^*]+)\*\*$')
MD_LEAD = re.compile(r'^(?:[#>+*-]\s|\d+[.)]\s)')
NO_LINE_START = '，。！？、；：”’）》…,.!?;:)'
CJK_RANGE = r'⺀-鿿豈-﫿＀-￯'  # 中日韩文字、兼容表意文字、全角标点
TOKEN = re.compile(r'\s+|[' + CJK_RANGE + r']|[^\s' + CJK_RANGE + r']+')


def _is_caps(s):
    """去掉括号里的补充（(V.O.)、(O.S.)）之后，有字母且没有小写。"""
    core = re.sub(r'[（(].*?[)）]', '', s)
    return any(c.isalpha() for c in core) and core == core.upper() and not cd.CJK.search(core)


# ---------- 读 ----------

def read_markdown(path):
    """场景稿（Markdown）→ (标题信息, 元素列表)。规则与 check_dialogue.parse 一致。"""
    src = Path(path).read_text(encoding='utf-8').splitlines()
    body, _ = cd.body_lines(src)
    first = next((i for i, l in enumerate(src) if cd.START.search(l) or cd.END.search(l)), 0)
    title = {}
    for l in src[:first]:
        m = re.match(r'^#\s+(.+)', l)
        if m:
            title['Title'] = [m.group(1).strip()]
            break
    tight, els, i, n = cd.has_tight_cue(body), [], 0, len(body)
    while i < n:
        no, raw = body[i]
        s = raw.strip()
        i += 1
        if not s:
            els.append(('blank', ''))
            continue
        if s.startswith('<!--'):
            m = cd.SCENE_MARK.match(s)
            if m:
                els.append(('mark', m.group(1)))
            continue
        if cd.SCENE_HEAD.match(s) and not cd.CUE_INLINE.match(s):
            els.append(('scene', s.lstrip('#').strip()))
            continue
        m = MD_HEADING.match(s)
        if m:  # 二级标题是场景标题（不以 INT. / EXT. 开头的也算），更深的是场内小标题
            els.append(('scene' if len(m.group(1)) == 2 else 'sub', m.group(2)))
            continue
        if cd.TRANSITION.match(s):
            els.append(('transition', s.lstrip('> ')))
            continue
        cue = cd.cue_of(s)
        loose = i < n and not body[i][1].strip()
        if cue and not (loose and tight):
            sp = cd._speech(cue[0], cue[1], no)
            j = (cd._loose_block if loose else cd._tight_block)(body, i, sp, cd._scene('x'))
            if sp['first']:
                els.append(('character', ' '.join(x for x in cue if x)))
                for k in range(i, j):
                    t = body[k][1].strip()
                    if t:
                        els.append(('paren' if cd.PAREN_ONLY.match(t) else 'dialogue', t))
                els.append(('blank', ''))
                i = j
                continue
        m = BOLD_LINE.match(s)
        if m:  # 加粗单独成段、下面没有台词：片名卡 / 本集完
            els.append(('center', m.group(1).strip()))
            continue
        m = cd.CUE_INLINE.match(s)
        sp = cd._inline(m, no, tight) if m else None
        if sp:  # 角色名：“台词” 同行的写法
            els.append(('character', ' '.join(x for x in (sp['speaker'], sp['cue_paren']) if x)))
            els += [('dialogue', t) for lg in ('en', 'zh') for t in sp['cand'][lg]]
            els.append(('blank', ''))
            continue
        els.append(('action', s))
    return title, els


def read_fountain(path):
    """Fountain（.fountain / .txt）→ (标题信息, 元素列表)。按 fountain.io/syntax 的规则；分节行当场标记，
    批注、弃稿、梗概不带过来。"""
    text = Path(path).read_text(encoding='utf-8')
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    text = re.sub(r'\[\[.*?\]\]', '', text, flags=re.S)
    lines = text.splitlines()
    title, i, n = {}, 0, len(lines)
    if lines and TITLE_KEY.match(lines[0]):
        key = None
        while i < n and lines[i].strip():
            m = TITLE_KEY.match(lines[i])
            if m and not lines[i][:1].isspace():
                key = m.group(1).strip()
                title[key] = [m.group(2).strip()] if m.group(2).strip() else []
            elif key:
                title[key].append(lines[i].strip())
            i += 1

    def blank(k):
        return k < 0 or k >= n or not lines[k].strip()

    els = []
    while i < n:
        s = lines[i].strip()
        i += 1
        if not s:
            els.append(('blank', ''))
            continue
        if s.startswith('#'):  # 分节：# S03 · 名字
            els.append(('mark', s.lstrip('#').strip()))
            continue
        if s.startswith('='):  # 分页、梗概
            continue
        before, after = blank(i - 2), blank(i)
        if s.startswith('!'):
            els.append(('action', s[1:]))
        elif s.startswith('>') and s.endswith('<'):
            els.append(('center', s[1:-1].strip()))
        elif s.startswith('>'):
            els.append(('transition', s[1:].strip()))
        elif s.startswith('.') and len(s) > 1 and s[1] != '.':
            els.append(('scene', s[1:].strip()))
        elif before and FOUNTAIN_SCENE.match(s):
            els.append(('scene', s))
        elif before and after and _is_caps(s) and s.endswith('TO:'):
            els.append(('transition', s))
        elif s.startswith('@') or (before and not after and _is_caps(s)):
            els.append(('character', s.lstrip('@').rstrip('^').strip()))
            while i < n and lines[i].strip():
                t = lines[i].strip()
                els.append(('paren' if cd.PAREN_ONLY.match(t) else 'dialogue', t))
                i += 1
            els.append(('blank', ''))
        elif before and after and _is_caps(s) and not s.endswith('.') and len(s.split()) <= 6:
            els.append(('sub', s))  # 场内小标题：AT THE BAR
        else:
            els.append(('action', s))
    return title, els


def read_any(path):
    return (read_fountain if Path(path).suffix.lower() in ('.fountain', '.txt') else read_markdown)(path)


def mark_translation(els):
    """全文多数台词的语言是主语言；同一段台词里另一种语言的行标成对照翻译（alt）。返回 (元素, 主语言)。"""
    blocks, cur = [], None
    for k, (kind, text) in enumerate(els):
        if kind == 'character':
            cur = []
            blocks.append(cur)
        elif kind == 'dialogue' and cur is not None:
            cur.append((k, cd.line_lang(text)))
        elif kind not in ('paren',):
            cur = None
    firsts = [b[0][1] for b in blocks if b]
    primary = 'zh' if firsts.count('zh') > firsts.count('en') else 'en'
    out = list(els)
    for b in blocks:
        if any(lg == primary for _, lg in b):
            for k, lg in b:
                if lg and lg != primary:
                    out[k] = ('alt', els[k][1])
    return out, primary


mark_label = cd.mark_label


def paragraphs(els, translation=True, scenes=None):
    """把元素并成段：[(类型, [行…])]。动作连着的几行是一段；角色名、括注、对白、对照行是一段。
    scenes：只留这几场（场标记开头的那一截，如 {'s03'}）；None 是全留。"""
    out, prev, keep = [], 'blank', scenes is None
    for kind, text in els:
        if kind == 'mark' and scenes is not None:
            keep = mark_label(text) in scenes
        if not keep or (kind == 'alt' and not translation):
            continue
        if kind == 'blank':
            prev = 'blank'
            continue
        if kind == 'action' and prev == 'action':
            out[-1][1].append(('action', text))
        elif kind in ('paren', 'dialogue', 'alt') and out and out[-1][0] == 'speech' and prev != 'blank':
            out[-1][1].append((kind, text))
        elif kind == 'character':
            out.append(('speech', [(kind, text)]))
        else:
            out.append((kind, [(kind, text)]))
        prev = kind
    return out


# ---------- 写 ----------

def plain(text):
    return re.sub(r'\*\*(.+?)\*\*', r'\1', text)


def title_lines(title):
    """标题页的三块：标题、署名与日期、备注。"""
    name = ' · '.join(title.get('Title', []))
    by = ' · '.join(' '.join(title[k]) for k in ('Credit', 'Author', 'Authors', 'Source', 'Draft date') if title.get(k))
    notes = ' '.join(title.get('Notes', []))
    return name, by, notes


def to_markdown(title, paras):
    name, by, notes = title_lines(title)
    out = [f'# {name}' if name else '# 剧本', '']
    if by:
        out += [by, '']
    if notes:
        out += [f'Notes: {notes}', '']
    out += ['<!-- script-body:start -->']
    for kind, lines in paras:
        if kind == 'mark':  # 场标记紧贴在它后面的场景标题上
            out.append(f'<!-- {lines[0][1]} -->')
            continue
        if kind == 'scene':
            out.append(f'## {lines[0][1]}')
        elif kind == 'sub':
            out.append(f'### {lines[0][1]}')
        elif kind == 'center':
            out.append(f'**{lines[0][1]}**')
        elif kind == 'speech':
            out.append(f'**{lines[0][1]}**')
            out += [t for _, t in lines[1:]]
        else:  # 动作、转场
            out += [('\\' + t if MD_LEAD.match(t) else t) for _, t in lines]
        out.append('')
    out[-1:] = ['<!-- script-body:end -->', '']
    return '\n'.join(out)


def to_fountain(title, paras):
    out = []
    for k, v in title.items():
        out.append(f'{k}: {v[0]}' if len(v) == 1 else f'{k}:')
        out += [f'    {x}' for x in (v[1:] if len(v) == 1 else v)]
    if out:
        out.append('')
    for kind, lines in paras:
        text = plain(lines[0][1])
        if kind == 'mark':
            out.append(f'# {text}')
        elif kind == 'scene':
            out.append(text if FOUNTAIN_SCENE.match(text) else '.' + text)
        elif kind == 'sub':
            out.append(text.upper())
        elif kind == 'center':
            out.append(f'>{text}<')
        elif kind == 'transition':
            out.append(f'> {text}')
        elif kind == 'speech':
            out.append(text if _is_caps(text) else '@' + text)
            out += [plain(t) for _, t in lines[1:]]
        else:
            out += [plain(t) for _, t in lines]
        out.append('')
    return '\n'.join(out)


def wrap(text, width):
    """按等宽格数折行：西文在空格处断，中日韩文字逐字可断，收尾标点不放行首。"""
    out, line, w = [], '', 0
    for tok in TOKEN.findall(text.strip()):
        if tok.isspace():
            if line:
                line, w = line + ' ', w + 1
            continue
        tw = cd.display_width(tok)
        if line.strip() and w + tw > width and tok[0] not in NO_LINE_START:
            out.append(line.rstrip())
            line, w = '', 0
        line, w = line + tok, w + tw
    if line.strip():
        out.append(line.rstrip())
    return out or ['']


def to_text(title, paras):
    """标准版面的纯文本。返回行的列表。"""
    out = []
    name, by, _ = title_lines(title)
    for head in (name, by):
        if head:
            out += [' ' * max(0, (60 - cd.display_width(x)) // 2) + x for x in wrap(head, 60)] + ['']
    for kind, lines in paras:
        if kind == 'mark':
            continue
        if kind == 'scene' and out:
            out.append('')
        for sub, text in lines:
            text = plain(text)
            if sub in ('scene', 'sub'):
                text = text.upper()
            if sub == 'center':
                out += [' ' * max(0, (60 - cd.display_width(x)) // 2) + x for x in wrap(text, 60)]
            elif sub == 'transition':
                out.append(' ' * max(0, 60 - cd.display_width(text)) + text)
            else:
                indent, width = COLS[sub]
                out += [' ' * indent + x for x in wrap(text, width)]
        out.append('')
    return out


CSS = '''@page { size: 8.5in 11in; margin: 1in 1in 1in 1.5in; }
body { margin: 0; background: #e8e8e4; color: #111; }
main { box-sizing: border-box; width: 8.5in; min-height: 11in; margin: 24px auto; padding: 1in 1in 1in 1.5in; background: #fff;
  box-shadow: 0 1px 6px rgba(0,0,0,.25); font: 12pt/12pt "Courier Prime", "Courier New", Courier, "Songti SC", "SimSun", monospace; }
p { margin: 0; overflow-wrap: break-word; }
.titlepage { text-align: center; padding: 2.5in 0 1.5in; }
.titlepage p + p { margin-top: 24pt; }
.titlepage .notes { margin-top: 2in; text-align: left; }
.scene { margin-top: 24pt; text-transform: uppercase; break-after: avoid; }
.sub { margin-top: 12pt; text-transform: uppercase; break-after: avoid; }
.action, .center, .transition { margin-top: 12pt; }
.center { text-align: center; }
.transition { text-align: right; }
.speech { margin-top: 12pt; break-inside: avoid; }
.character { margin-left: 2in; }
.paren { margin-left: 1.5in; width: 2.5in; }
.dialogue, .alt { margin-left: 1in; width: 3.5in; }
.alt { color: #666; }
@media print { body { background: none; } main { width: auto; min-height: 0; margin: 0; padding: 0; box-shadow: none; }
  .titlepage { break-after: page; } }
@media screen and (max-width: 8.6in) { main { width: auto; margin: 0; padding: 20px 16px; box-shadow: none; }
  .character { margin-left: 34%; } .paren { margin-left: 25%; width: 45%; } .dialogue, .alt { margin-left: 16%; width: 62%; } }'''


def to_html(title, paras, lang='en'):
    name, by, notes = title_lines(title)
    e = html.escape
    out = [f'<!doctype html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{e(name or "Screenplay")}</title>\n'
           f'<style>\n{CSS}\n</style>\n</head>\n<body>\n<main>']
    if name:
        out.append('<div class="titlepage">' + ''.join(f'<p>{e(x)}</p>' for x in title.get('Title', [])) +
                   (f'<p>{e(by)}</p>' if by else '') + (f'<p class="notes">{e(notes)}</p>' if notes else '') + '</div>')
    for kind, lines in paras:
        if kind == 'mark':
            continue
        if kind == 'speech':
            out.append('<div class="speech">' + ''.join(f'<p class="{k}">{e(plain(t))}</p>' for k, t in lines) + '</div>')
        else:
            out.append(f'<p class="{kind}">' + '<br>'.join(e(plain(t)) for _, t in lines) + '</p>')
    out.append('</main>\n</body>\n</html>\n')
    return '\n'.join(out)


def format_notes(paras):
    """格式提示：只报和标准格式不一样的地方，不改。"""
    notes = []
    odd = [l[0][1] for k, l in paras if k == 'scene' and not re.match(r'^(?:INT\./EXT|INT/EXT|INT|EXT|EST|I/E)\.? .+ - .+', l[0][1], re.I)]
    if odd:
        notes.append(f"场景标题不是「INT. / EXT. 地点 - 时间」的有 {len(odd)} 处（照原样排）：{'；'.join(odd[:3])}")
    low = sorted({l[0][1] for k, l in paras if k == 'speech' and not _is_caps(l[0][1]) and not cd.CJK.search(l[0][1])})
    if low:
        notes.append(f"角色名不是全大写：{'、'.join(low[:6])}")
    return notes


def main():
    ap = argparse.ArgumentParser(description='剧本格式转换（film-story）：Markdown / Fountain → 标准版面、Markdown、标准页、Fountain。')
    ap.add_argument('files', nargs='+')
    ap.add_argument('--md', help='写成标准格式的 Markdown')
    ap.add_argument('--html', help='写成标准页（Courier 12 pt、标准页边距）')
    ap.add_argument('--fountain', help='写成 Fountain 纯文本')
    ap.add_argument('--scene', help='只取这几场，逗号分隔（按场标记，如 S03,S04）')
    ap.add_argument('--no-translation', action='store_true', help='去掉对照翻译行')
    ap.add_argument('--title', help='标题；不给时用第一个文件里的')
    a = ap.parse_args()
    title, els = {}, []
    for f in a.files:
        t, e = read_any(f)
        title = title or t
        els += e + [('blank', '')]
    if a.title:
        title = dict(title, Title=[a.title])
    els, primary = mark_translation(els)
    wanted = {mark_label(x) for x in a.scene.split(',') if x.strip()} if a.scene else None
    full = paragraphs(els, True, wanted)
    paras = paragraphs(els, False, wanted) if a.no_translation else full
    if wanted and not paras:
        have = '、'.join(dict.fromkeys(t for k, t in els if k == 'mark')) or '没有场标记'
        print(f"没有找到 {a.scene}。文件里的场：{have}")
        return
    text = to_text(title, paras)
    done = []
    for path, body in ((a.md, to_markdown(title, paras) if a.md else ''),
                       (a.html, to_html(title, paras, primary) if a.html else ''),
                       (a.fountain, to_fountain(title, paras) if a.fountain else '')):
        if path:
            Path(path).write_text(body, encoding='utf-8')
            done.append(path)
    if not done:
        print('\n'.join(text))
    n_mark = sum(k == 'mark' for k, _ in paras)
    n_scene = sum(k == 'scene' for k, _ in paras)
    n_speech = sum(k == 'speech' for k, _ in paras)
    alt = sum(k == 'alt' for _, lines in full for k, _ in lines)
    note = f"；对照翻译 {alt} 行{'已去掉' if a.no_translation else '在内'}" if alt else ''
    print(f"{'已写 ' + '、'.join(done) + '：' if done else '-- '}{f'场 {n_mark} 个 · ' if n_mark else ''}场景标题 {n_scene} 个 · 台词 {n_speech} 段 · "
          f"标准版面约 {len(text)} 行 ≈ {math.ceil(len(text) / PAGE_LINES * 10) / 10:g} 页（一页 {PAGE_LINES} 行，粗估{note}）")
    for x in format_notes(paras):
        print('格式提示：' + x)


if __name__ == '__main__':
    main()
