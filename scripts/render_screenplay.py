#!/usr/bin/env python3
"""剧本格式转换（film-story）。把正文读成剧本元素，再写成需要的样子；只转换格式，不改一个字。

用法:
  python3 render_screenplay.py <文件…>                      标准版面的纯文本（终端里看）+ 页数
  python3 render_screenplay.py <文件…> --md 整集.md          标准格式的 Markdown（拼整集稿；PDF / Fountain / txt 转 Markdown）
  python3 render_screenplay.py <文件…> --html 整集.html      标准页的 HTML：和 PDF 是同一份排好的页，浏览器里看
  python3 render_screenplay.py <文件…> --fountain 整集.fountain  Fountain 纯文本，可导入 Final Draft、Highland 等
  python3 render_screenplay.py <文件…> --pdf 整集.pdf        PDF：带扉页、页码，对白跨页有 (MORE) / (CONT'D)
  选项：--scene S03[,S04] 只取这几场（按场标记 <!-- S03 · 名字 -->）；--no-translation 去掉对照翻译行
        （只留全文多数台词的那种语言）；--title 指定标题

输入：.md 按剧本文件读（只读 <!-- script-body:start/end --> 之间；没有标记按全文读）；.fountain / .txt 按 Fountain 读；
.pdf 按每行在页面上的位置读（标准版式、带文字层的才行）。几个文件按给的顺序接成一份。元素与写法见
references/screenplay-format.md。场标记在 Markdown 里是注释行，在 Fountain 里是分节行（# S03 · 名字），版面上不显示。

扉页信息在 Markdown 头部：一级标题是剧名和集名（用 · 分开）；"版本："一行里"依据"之前是版本（可带稿次标签），
最后一截带数字的是日期；"说明："一行印在扉页左下角。头部有"页数："一行时，出整集 PDF 后把页数回填进去。

版面和分页的规格、PDF 读写的做法和限制见 screenplay_pages.py。页数是这套版面排出来的页数；一页约一分钟是英文剧本的
经验值，对照翻译行和中文动作描写会让页数偏多，口播秒数看 check_dialogue.py。退出码恒为 0。"""
import argparse, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_dialogue as cd  # noqa: E402
import screenplay_pages as pages  # noqa: E402
from screenplay_pages import FOUNTAIN_SCENE, PAGE_LINES, STANDARD_HEAD, plain  # noqa: E402
from screenplay_pages import is_caps as _is_caps  # noqa: E402

TITLE_KEY = re.compile(r'^([A-Za-z][A-Za-z ]*):\s*(.*)$')
MD_HEADING = re.compile(r'^(#{1,6})\s+(.+?)\s*#*$')
BOLD_LINE = re.compile(r'^\*\*([^*]+)\*\*$')
MD_LEAD = re.compile(r'^(?:[#>+*-]\s|\d+[.)]\s)')


def header_info(lines):
    """正文之前的头部 → 扉页信息。一级标题是剧名和集名（用 · 分开）；"版本："一行去掉"依据：…"以后，
    最后一截带数字的是日期，前面的都是版本（稿次标签写在版本里或单独一截都行）；"说明："一行是说明。"""
    title = {}
    for no, line in enumerate(lines, 1):
        s = line.strip()
        m = re.match(r'^#\s+(.+)', s)
        if m and 'Title' not in title:
            title['Title'] = [x.strip() for x in m.group(1).split(' · ') if x.strip()]
            title['_line'] = no
        elif s.startswith('版本：') and 'Credit' not in title:
            parts = [x.strip() for x in s[3:].split(' · ') if x.strip() and not x.strip().startswith('依据')]
            date = [parts.pop()] if len(parts) > 1 and re.search(r'\d', parts[-1]) else []
            title['Credit'], title['Draft date'] = [' · '.join(parts)] if parts else [], date
        elif s.startswith('说明：') and s[3:].strip():
            title['Notes'] = [s[3:].strip()]
    return {k: v for k, v in title.items() if v}


# ---------- 读 ----------

def read_markdown(path):
    """剧本文件（Markdown）→ (标题信息, 元素列表)。分场和认角色名的规则与 check_dialogue.parse 一致。
    标题取正文标记之前的第一个一级标题；没有正文标记的旧稿取全文第一个一级标题，那一行不再排进正文。"""
    src = Path(path).read_text(encoding='utf-8').splitlines()
    body, note = cd.body_lines(src)
    first = next((i for i, l in enumerate(src) if cd.START.search(l) or cd.END.search(l)), len(src))
    title = header_info(src[:first])
    title_no = title.pop('_line', None)
    tight, els, i, n = cd.has_tight_cue(body), [], 0, len(body)
    known = cd.cue_names(body) if tight else ()
    while i < n:
        no, raw = body[i]
        s = raw.strip()
        i += 1
        if not s or (note == 'no-markers' and no == title_no):
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
        if m:  # 有正文标记的文件里，二级标题都是场景标题（不以 INT. / EXT. 开头的也算）；更深的是场内小标题
            els.append(('scene' if len(m.group(1)) == 2 and note != 'no-markers' else 'sub', m.group(2)))
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
        sp = cd._inline(m, no, tight, known) if m else None
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
        elif before and after and pages.is_heading(s) == 'sub':
            els.append(('sub', s))  # 场内小标题：AT THE BAR
        else:
            els.append(('action', s))
    return title, els


def read_any(path):
    """按后缀读：.pdf 按版面位置，.fountain / .txt 按 Fountain，其余按 Markdown 剧本。"""
    ext = Path(path).suffix.lower()
    if ext == '.pdf':
        return pages.read_pdf(path)
    return (read_fountain if ext in ('.fountain', '.txt') else read_markdown)(path)


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

def title_lines(title):
    """头部的三块：标题、版本一行（版本 · 日期）、说明。别处来的 Fountain 里的署名、来源并进版本，联系方式并进说明。"""
    name = ' · '.join(title.get('Title', []))
    credit = ' '.join(' '.join(title[k]) for k in ('Credit', 'Author', 'Authors', 'Source') if title.get(k))
    by = ' · '.join(x for x in (credit, ' '.join(title.get('Draft date', []))) if x)
    notes = ' '.join(x for k in ('Notes', 'Contact') for x in title.get(k, []) if x)
    return name, by, notes


def to_markdown(title, paras, skeleton=False):
    """写成剧本文件。skeleton：来源不是本 skill 的剧本文件（PDF、Fountain）时，把头部要补的几项列出来。"""
    name, by, notes = title_lines(title)
    out = [f'# {name}' if name else '# 剧本', '']
    if by:
        out.append(f'版本：{by}')
    if notes:
        out.append(f'说明：{notes}')
    if skeleton:
        out += ['承接：待补', '新事实（提案）：待补', '', '状态：待补']
    if out[-1]:
        out.append('')
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
    if not out[-1] and out[-2] != '<!-- script-body:start -->':
        out.pop()  # 最后一段后面的空行
    out += ['<!-- script-body:end -->', '']
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


def to_text(title, paras):
    """标准版面的纯文本（终端里看，不分页）。和 PDF 用同一份排好的行。返回行的列表。"""
    out = []
    name, by, _ = title_lines(title)
    for head in (name, by):
        if head:
            out += [pages.line_text(pages.CENTER + x) for x in pages.wrap(head, pages.WIDTH)] + ['']
    for block in pages.blocks_of(paras):
        if out:  # 块与块之间空 gap 行；标题后面已经空了一行
            out += [''] * (block['gap'] - (0 if out[-1] else 1))
        out += [pages.line_text(t) for _, t in block['lines']]
    return out + ['']


def format_notes(paras):
    """格式提示：只报和标准格式不一样的地方，不改。"""
    notes = []
    odd = [l[0][1] for k, l in paras if k == 'scene' and not STANDARD_HEAD.match(l[0][1])]
    if odd:
        notes.append(f"场景标题不是「INT. / EXT. 地点 - 时间」「内 / 外 · 地点 · 时间」或「内景 地点 - 时间」的有 {len(odd)} 处"
                     f"（照原样排）：{'；'.join(odd[:3])}")
    low = sorted({l[0][1] for k, l in paras if k == 'speech' and not _is_caps(l[0][1]) and not cd.CJK.search(l[0][1])})
    if low:
        notes.append(f"角色名不是全大写：{'、'.join(low[:6])}")
    return notes


def fill_page_count(path, n, title, extra=''):
    """头部有"页数："一行时，把导出的页数写回去（只动这一行）。返回写了没有。extra：含不含对照翻译。"""
    p = Path(path)
    src = p.read_text(encoding='utf-8').split('\n')
    first = next((i for i, l in enumerate(src) if cd.START.search(l)), len(src))
    for i, line in enumerate(src[:first]):
        if line.strip().startswith('页数：'):
            src[i] = f"页数：{n}（{' '.join(title.get('Credit', [])) or '这一版'}，不含扉页{extra}）"
            p.write_text('\n'.join(src), encoding='utf-8')
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description='剧本格式转换（film-story）：Markdown / Fountain / PDF → 标准版面、Markdown、标准页、Fountain、PDF。')
    ap.add_argument('files', nargs='+')
    ap.add_argument('--md', help='写成标准格式的 Markdown')
    ap.add_argument('--html', help='写成标准页的 HTML（和 PDF 是同一份排好的页，浏览器里看）')
    ap.add_argument('--fountain', help='写成 Fountain 纯文本')
    ap.add_argument('--pdf', help='写成 PDF（带扉页、页码；要本机有 Chrome / Chromium / Edge）')
    ap.add_argument('--scene', help='只取这几场，逗号分隔（按场标记，如 S03,S04）')
    ap.add_argument('--no-translation', action='store_true', help='去掉对照翻译行')
    ap.add_argument('--title', help='标题；不给时用第一个文件里的')
    a = ap.parse_args()
    title, els = {}, []
    for f in a.files:
        try:
            t, e = read_any(f)
        except RuntimeError as err:
            print(f'⚠ {f}：{err}')
            return
        title = title or t
        els += e + [('blank', '')]
    foreign = any(Path(f).suffix.lower() != '.md' for f in a.files)
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
    missing = [str(Path(x).resolve().parent) for x in (a.md, a.html, a.fountain, a.pdf) if x and not Path(x).resolve().parent.is_dir()]
    if missing:
        print(f"⚠ 要写到的目录不存在：{'、'.join(dict.fromkeys(missing))}")
        return
    text = to_text(title, paras)
    laid = pages.paginate(pages.blocks_of(paras))
    done, notes, lost = [], [], []
    # 标准页的 HTML 和 PDF 是同一份排好的页：扉页、页码、分页处的 (MORE) / (CONT'D) 都一样
    page_html = ''
    if a.html or a.pdf:
        page_html = pages.pages_html(pages.title_page(title, dropped=lost), laid, title_lines(title)[0] or 'Screenplay', primary)
    if lost:
        notes.append(f'⚠ 扉页排不下，有 {lost[0]} 行没印（标题或说明太长）。')
    for path, body in ((a.md, to_markdown(title, paras, foreign) if a.md else ''), (a.html, page_html if a.html else ''),
                       (a.fountain, to_fountain(title, paras) if a.fountain else '')):
        if path:
            Path(path).write_text(body, encoding='utf-8')
            done.append(path)
    alt = sum(k == 'alt' for _, lines in full for k, _ in lines)
    if a.pdf:
        ok, why = pages.write_pdf(page_html, a.pdf)
        if ok:
            done.append(a.pdf)
            extra = ('，对照翻译已去掉' if a.no_translation else '，含对照翻译') if alt else ''
            if len(a.files) == 1 and not foreign and not a.scene and fill_page_count(a.files[0], len(laid), title, extra):
                notes.append(f'页数 {len(laid)} 已回填到 {a.files[0]} 的头部。')
        else:
            notes.append('⚠ ' + why)
    if not done and not a.pdf:
        print('\n'.join(text))
    n_mark = sum(k == 'mark' for k, _ in paras)
    n_scene = sum(k == 'scene' for k, _ in paras)
    n_speech = sum(k == 'speech' for k, _ in paras)
    note = f"；对照翻译 {alt} 行{'已去掉' if a.no_translation else '在内'}" if alt else ''
    print(f"{'已写 ' + '、'.join(str(x) for x in done) + '：' if done else '-- '}{f'场 {n_mark} 个 · ' if n_mark else ''}场景标题 {n_scene} 个 · "
          f"台词 {n_speech} 段 · 排成 {len(laid)} 页（一页 {PAGE_LINES} 行，不含扉页{note}）")
    for x in notes:
        print(x)
    if foreign and a.md:
        print('头部的承接、新事实、状态写的是"待补"，场标记也要补。')
    for x in format_notes(paras):
        print('格式提示：' + x)


if __name__ == '__main__':
    main()
