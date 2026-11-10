#!/usr/bin/env python3
"""版面与 PDF（film-story）。折行、分页、把排好的页写成 PDF、把 PDF 按每行的位置读回剧本元素。
由 render_screenplay.py 调用，自己不做命令行。

标准页（US Letter，Courier 12 pt；一格 = 0.1 in = 7.2 pt，一行 = 12 pt）：左边距 1.5 in，右、上、下 1 in；动作通栏
60 格；对白缩进 10 格、宽 35 格；括注缩进 15 格、宽 25 格；角色名缩进 20 格；一页 54 行；页码在右上角，从正文第二页起；
扉页不编号。中日韩文字和全角标点一个字宽 12 pt（不是整两格），折行按实际宽度算。

写 PDF：这里先分好页（对白跨页时页底加 (MORE)、下一页角色名后加 (CONT'D)；场景标题和小标题不留在页底），再用本机的
Chrome / Chromium / Edge 无头打印。找不到浏览器时只写出排好页的 HTML，并说明。
读 PDF：用 macOS 自带的 PDFKit（通过 swift 运行 pdf_lines.swift）取每一行的文字和位置，按缩进认元素；页码、(MORE)、
(CONT'D) 去掉。两行是不是同一段折出来的，看上一行排没排满（下一行开头那一截接在后面放不放得下）。只认标准版式、
带文字层的 PDF，扫描件读不了。读回来认不准的几种情况见 references/screenplay-format.md §5。"""
import html, re, shutil, subprocess, tempfile
from pathlib import Path

import check_dialogue as cd

COLS = {'action': (0, 60), 'scene': (0, 60), 'sub': (0, 60), 'character': (20, 38), 'paren': (15, 25),
        'dialogue': (10, 35), 'alt': (10, 35)}
WIDTH = 60          # 通栏格数
CENTER, RIGHT = '\x01', '\x02'  # 排好的行开头的记号：这一行居中 / 靠右。交给浏览器去对齐，中文字宽不是整两格，按格数算会偏
PAGE_LINES = 54     # 上、下边距各 1 in：9 in ÷ 12 pt
PT = 7.2            # 一格的宽度（pt）
UNIT = 2.4          # 量宽度的单位（pt）：西文一格 3 个单位，中日韩文字一个字 5 个单位
FOUNTAIN_SCENE = re.compile(r'^(?:INT\./EXT|INT/EXT|INT|EXT|EST|I/E)[. ]', re.I)
STANDARD_HEAD = re.compile(r'^(?:(?:INT\./EXT|INT/EXT|INT|EXT|EST|I/E)\.? .+ - .+|(?:内|外|内外)\s*·\s*.+\s*·\s*.+|'
                           r'(?:内景|外景|内外景)\s+.+\s[-–·]\s.+)', re.I)  # INT. 地点 - 时间；内 · 地点 · 时间；内景 地点 - 时间
NO_LINE_START = '，。！？、；：”’）》…,.!?;:)'
CJK_RANGE = r'⺀-鿿豈-﫿＀-￯'  # 中日韩文字、兼容表意文字、全角标点
FULL_PUNCT = r'、-〿！-／：-＠［-｀｛-･'  # 全角标点：旁边不留空格
LOOSE_PUNCT = '“”‘’—…'  # 中西文都用的标点：挨着中日韩文字时不留空格
TOKEN = re.compile(r'\s+|[' + CJK_RANGE + r']|[^\s' + CJK_RANGE + r']+')
SENTENCE_END = re.compile(r'[.?!…:。？！：][\"”’\')）\]]*$')
LINE_END = re.compile(r'[.?!…:。？！：—–\-][\"”’\')）\]]*$')  # 一句台词说完（或被打断）的样子
MORE = re.compile(r'\(MORE\)', re.I)
CONTD = re.compile(r"\s*\(CONT['’]D\)\s*$", re.I)
BROWSERS = ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
            '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge')
BROWSER_NAMES = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome', 'microsoft-edge')


def plain(text):
    """去掉粗体记号（角色名、片名卡的 **…**）。"""
    return re.sub(r'\*\*(.+?)\*\*', r'\1', text)


def unmarked(text):
    """去掉 Markdown 的粗体、斜体记号：版面上不印星号。"""
    return re.sub(r'(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])', r'\1', plain(text))


units = cd.page_units  # 排出来的宽度（单位 2.4 pt）：西文一格 3 个单位，中日韩文字和全角标点一个字 5 个单位


def is_caps(s):
    """去掉括号里的补充（(V.O.)、(O.S.)）之后，有字母且没有小写。"""
    core = re.sub(r'[（(].*?[)）]', '', s)
    return any(c.isalpha() for c in core) and core == core.upper() and not cd.CJK.search(core)


def join_lines(a, b):
    """折行接回去：挨着全角标点、或两边都是中日韩文字，直接接；否则加一个空格。"""
    if not a or not b:
        return a or b
    x, y = a[-1], b[0]
    cjk = [bool(re.match('[' + CJK_RANGE + ']', c)) for c in (x, y)]
    if all(cjk) or re.match('[' + FULL_PUNCT + ']', x) or re.match('[' + FULL_PUNCT + ']', y):
        return a + b
    if (cjk[0] and y in LOOSE_PUNCT) or (cjk[1] and x in LOOSE_PUNCT):
        return a + b
    return a + ' ' + b


def _tokens(text):
    """切成词：[(词, 它前面有没有空格)]。西文在空格处分，中日韩文字一字一个。"""
    out, gap = [], False
    for tok in TOKEN.findall(text.strip()):
        if tok.isspace():
            gap = True
        else:
            out.append((tok, gap and bool(out)))
            gap = False
    return out


def _joined(us):
    return ''.join((' ' if s and k else '') + t for k, (t, s) in enumerate(us))


def _glued(us, k):
    """第 k 个词和前一个词之间不能断：断了以后接回去和原文不一样。"""
    (a, _), (b, s) = us[k - 1], us[k]
    return join_lines(a, b) != a + (' ' if s else '') + b


def first_chunk(text):
    """一行开头那一截断不开的字。折行时是它整个放不下，才挪到了这一行。"""
    us = _tokens(text)
    k = 1
    while k < len(us) and _glued(us, k):
        k += 1
    return _joined(us[:k])


def _pieces(word, limit):
    """比一行还宽的词（网址之类）硬切成几截；别的词原样返回。"""
    out = []
    while units(word) > limit and len(word) > 1:
        n = max([i for i in range(1, len(word)) if units(word[:i]) <= limit] or [1])
        out.append(word[:n])
        word = word[n:]
    return out + [word]


def wrap(text, width):
    """折行，width 是格数：西文在空格处断，中日韩文字逐字可断，收尾标点不放行首（放不下就挂在行尾）。
    只在"接回去和原文一样"的地方断（见 join_lines），写成 PDF 再读回来才一字不差；硬切的长词除外。"""
    limit, out, cur = width * 3, [], []
    for tok, gap in _tokens(text):
        for j, part in enumerate(_pieces(tok, limit)):
            if j:  # 硬切出来的后半截另起一行
                out.append(_joined(cur))
                cur = []
            cur.append((part, gap and not j))
            while len(cur) > 1 and units(_joined(cur)) > limit and cur[-1][0][0] not in NO_LINE_START:
                at = next((k for k in range(len(cur) - 1, 0, -1) if not _glued(cur, k) and cur[k][0][0] not in NO_LINE_START), None)
                if at is None:
                    break
                out.append(_joined(cur[:at]))
                cur = cur[at:]
    if cur:
        out.append(_joined(cur))
    return out or ['']


def line_text(line):
    """排好的一行按格数还原成纯文本（居中、靠右的记号换成空格），终端里看用。"""
    if line[:1] == CENTER:
        return ' ' * max(0, (WIDTH - cd.display_width(line[1:])) // 2) + line[1:]
    if line[:1] == RIGHT:
        return ' ' * max(0, WIDTH - cd.display_width(line[1:])) + line[1:]
    return line


# ---------- 分页 ----------

def blocks_of(paras):
    """段 → 排好行的块：[{'kind', 'gap'（前面空几行）, 'lines': [(类型, 带缩进的一行)]}]。场标记不排。"""
    out = []
    for kind, lines in paras:
        if kind == 'mark':
            continue
        rows = []
        for sub, text in lines:
            text = unmarked(text)
            if sub in ('scene', 'sub'):
                text = text.upper()
            if sub == 'center':
                rows += [('center', CENTER + x) for x in wrap(text, WIDTH)]
            elif sub == 'transition':
                rows.append(('transition', RIGHT + text))
            else:
                indent, width = COLS[sub]
                rows += [(sub, ' ' * indent + x) for x in wrap(text, width)]
        out.append({'kind': kind, 'gap': 2 if kind == 'scene' else 1, 'lines': rows})
    return out


def _cut_speech(lines, room):
    """一段台词在这一页最多放 room 行（含角色名和 (MORE)）。返回这一页放几行台词；放不下返回 0。"""
    body = lines[1:]
    k = min(room - 2, len(body) - 2)  # 角色名 1 行 + (MORE) 1 行；下一页至少留 2 行
    while k >= 2 and body[k - 1][0] == 'paren':  # 括注不留在页底
        k -= 1
    return k if k >= 2 else 0


def _cut_action(lines, room):
    """一段动作在这一页最多放 room 行。断在句子中间（读回来才接得上）；两边各至少 2 行。放不下返回 0。"""
    k = min(room, len(lines) - 2)
    while k >= 2 and SENTENCE_END.search(lines[k - 1][1]):
        k -= 1
    return k if k >= 2 else 0


def paginate(blocks, page_lines=PAGE_LINES):
    """块 → 页：[[一行…], …]。页首不留空行；场景标题和小标题不留在页底；对白跨页加 (MORE) / (CONT'D)。"""
    pages = [[]]
    queue = [dict(b) for b in blocks]
    held = []  # 这一页末尾连着放的标题：[(放它之前这一页有几行, 块)]。后面那一块整块去了下一页，它们跟着走
    i = 0
    while i < len(queue):
        b = queue[i]
        page = pages[-1]
        gap = b['gap'] if page else 0
        room = page_lines - len(page) - gap
        heading = b['kind'] in ('scene', 'sub')
        need = len(b['lines'])
        if heading and i + 1 < len(queue):
            need += queue[i + 1]['gap'] + min(2, len(queue[i + 1]['lines']))
        if need <= room or (not page and len(b['lines']) >= page_lines and b['kind'] not in ('speech', 'action')):
            held = held + [(len(page), b)] if heading else []
            page += [''] * gap + [t for _, t in b['lines'][:page_lines]]
            i += 1
            continue
        k = 0
        if b['kind'] == 'speech':
            k = _cut_speech(b['lines'], room)
            if k:
                cue = b['lines'][0][1]
                page += [''] * gap + [cue] + [t for _, t in b['lines'][1:1 + k]] + [' ' * COLS['character'][0] + '(MORE)']
                again = cue if CONTD.search(cue) else cue.rstrip() + " (CONT'D)"
                queue[i] = {'kind': 'speech', 'gap': 0, 'lines': [('character', again)] + b['lines'][1 + k:]}
        elif b['kind'] == 'action':
            k = _cut_action(b['lines'], room)
            if k:
                page += [''] * gap + [t for _, t in b['lines'][:k]]
                queue[i] = {'kind': 'action', 'gap': 0, 'lines': b['lines'][k:]}
        if not k and held and held[0][0]:  # 这一块整块去下一页：页底的标题一起带走
            del page[held[0][0]:]
            queue[i:i] = [h for _, h in held]
        elif not k and (not page or (held and not held[0][0])):  # 整页（或只有标题的一页）还放不下：硬切，免得死循环
            take = max(1, room)
            page += [''] * gap + [t for _, t in b['lines'][:take]]
            queue[i] = dict(b, gap=0, lines=b['lines'][take:])
            if not queue[i]['lines']:
                i += 1
        held = []
        pages.append([])
    if not pages[-1]:
        pages.pop()
    return pages


def title_page(title, page_lines=PAGE_LINES, dropped=None):
    """扉页：剧名、集名居中在上三分之一，版本一行在下面（别处来的 Fountain 里的署名、来源也排在这里）；
    说明和日期在页底靠左。没有剧名就不出扉页。排不下的行不印，行数记进 dropped（给了的话）。"""
    names = [x for x in title.get('Title', []) if x]
    if not names:
        return None
    top = []
    for name in names:
        top += [CENTER + x for x in wrap(name, WIDTH)] + ['']
    below = [' '.join(title[k]) for k in ('Credit', 'Author', 'Authors', 'Source') if title.get(k)]  # 本 skill 的稿只有版本一行
    if below:
        top.append('')  # 和剧名隔两行：读回来靠这个间隔认出它
        for item in below:
            top += [CENTER + x for x in wrap(item, WIDTH)]
    while not top[-1]:
        top.pop()
    date = ' '.join(title.get('Draft date', []))
    notes = wrap(' '.join(title.get('Notes', [])), WIDTH) if title.get('Notes') else []
    notes += [x for x in title.get('Contact', []) if x]  # 别处来的 Fountain 里的联系方式，也放左下角
    end = page_lines - 5  # 左下角那一块的最后一行
    tail = ['', date] if date and notes else [date] if date else []
    first = max(1, min(14, end - len(notes) - len(tail) - len(top)))  # 平常从第 15 行起；内容多就往上提
    spare = end + 1 - first - len(tail) - 1  # 剧名一块和说明一共能占几行（中间隔一行）
    lost = max(0, len(top) + len(notes) - spare)
    if lost:
        cut_notes = min(lost, len(notes))
        notes = notes[:len(notes) - cut_notes]
        top = top[:len(top) - (lost - cut_notes)]
        if dropped is not None:
            dropped.append(lost)
    page = [''] * page_lines
    page[first:first + len(top)] = top
    bottom = notes + tail
    page[end + 1 - len(bottom):end + 1] = bottom
    return page


PAGE_CSS = '''@page { size: 8.5in 11in; margin: 0; }
html, body { margin: 0; padding: 0; }
pre { box-sizing: border-box; width: 8.5in; height: 11in; margin: 0; padding: 1in 1in 0 1.5in; position: relative;
  overflow: hidden; white-space: pre; page-break-after: always; break-after: page;
  font: 12pt/12pt "Courier Prime", "Courier New", Courier, "Songti SC", "PingFang SC", "SimSun", monospace; }
pre:last-of-type { page-break-after: auto; break-after: auto; }
.num { position: absolute; top: 0.5in; right: 1in; }
.c, .r { display: inline-block; width: 6in; }
.c { text-align: center; }
.r { text-align: right; }
@media screen { body { background: #e8e8e4; } pre { margin: 16px auto; background: #fff; box-shadow: 0 1px 6px rgba(0,0,0,.25); } }'''


def line_html(line):
    if line[:1] == CENTER:
        return f'<span class="c">{html.escape(line[1:])}</span>'
    if line[:1] == RIGHT:
        return f'<span class="r">{html.escape(line[1:])}</span>'
    return html.escape(line)


def pages_html(front, pages, name='Screenplay', lang='en'):
    """排好的页 → 一页一个 <pre> 的 HTML。front 是扉页（没有就传 None）；正文页码从第二页起印。"""
    e = html.escape
    out = [f'<!doctype html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n<title>{e(name)}</title>\n'
           f'<style>\n{PAGE_CSS}\n</style>\n</head>\n<body>']
    if front:
        out.append('<pre>' + '\n'.join(line_html(x) for x in front).rstrip() + '</pre>')
    for n, page in enumerate(pages, 1):
        num = f'<span class="num">{n}.</span>' if n > 1 else ''
        out.append('<pre>' + num + '\n'.join(line_html(x) for x in page) + '</pre>')
    out.append('</body>\n</html>\n')
    return '\n'.join(out)


def find_browser():
    for p in BROWSERS:
        if Path(p).is_file():
            return p
    for n in BROWSER_NAMES:
        p = shutil.which(n)
        if p:
            return p
    return None


def write_pdf(page_html, out_path):
    """用无头浏览器把排好页的 HTML 打印成 PDF。返回 (成功没有, 说明)。失败时把 HTML 写在 PDF 旁边。"""
    out = Path(out_path).resolve()
    browser = find_browser()
    fallback = out.with_suffix('.html')
    if not browser:
        fallback.write_text(page_html, encoding='utf-8')
        return False, f'本机没有找到 Chrome / Chromium / Edge，没法直接出 PDF。排好页的 HTML 写在 {fallback}，用浏览器打开打印（边距选"无"）。'
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'pages.html'
        src.write_text(page_html, encoding='utf-8')
        try:
            run = subprocess.run([browser, '--headless=new', '--disable-gpu', '--no-pdf-header-footer',
                                  f'--print-to-pdf={out}', src.as_uri()], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as err:
            run = None
            why = str(err)
        if run is None or run.returncode or not out.is_file() or out.stat().st_size < 500:
            fallback.write_text(page_html, encoding='utf-8')
            why = why if run is None else (run.stderr.strip().splitlines() or ['没有生成文件'])[-1]
            return False, f'浏览器打印 PDF 失败（{why[:120]}）。排好页的 HTML 写在 {fallback}。'
    return True, ''


# ---------- 读 PDF ----------

NEAR = 17   # 上下两行的中线相距不超过这么多 pt 算挨着（行距 12 pt；中文字的外框比西文高，位置会有两三 pt 的出入）
SAME = 4    # 中线相距不超过这么多 pt 算同一行


def merge_fragments(rows):
    """同一行被拆成几截的接回去（中西文混排时常见）。挨着的直接接，隔着一两格的加一个空格，隔得远的不接（页码）。"""
    out = []
    for r in sorted(rows, key=lambda r: (r[0], -r[3], r[1])):
        prev = out[-1] if out else None
        if prev and prev[0] == r[0] and abs(prev[3] - r[3]) <= SAME and r[1] - prev[2] <= 3 * PT:
            gap = ' ' if r[1] - prev[2] >= PT / 2 else ''
            out[-1] = (prev[0], prev[1], r[2], prev[3], prev[4] + gap + r[4])
        else:
            out.append(r)
    return out


def pdf_rows(path):
    """PDF → [(页, 左, 右, 中线的高度, 文字)]，以及每页的 (宽, 高)。出错抛 RuntimeError（说明里写怎么办）。"""
    if not Path(path).is_file():
        raise RuntimeError(f'找不到文件：{path}')
    swift = shutil.which('swift')
    if not swift:
        raise RuntimeError('读 PDF 要用 macOS 自带的 PDFKit（通过 swift），这台机器上没有 swift。先把 PDF 转成 Fountain 或 Markdown 再给脚本。')
    script = Path(__file__).resolve().parent / 'pdf_lines.swift'
    try:
        run = subprocess.run([swift, str(script), str(path)], capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise RuntimeError(f'读 PDF 失败：{err}')
    if run.returncode:
        why = (run.stderr.strip().splitlines() or ['swift 出错'])[-1][:160]
        raise RuntimeError('打不开这份 PDF（文件坏了，或者不是 PDF）。' if 'cannot open pdf' in why else f'读 PDF 失败：{why}')
    rows, sizes, page = [], {}, 0
    for line in run.stdout.splitlines():
        parts = line.split('\t')
        if line.startswith('=== PAGE') and len(parts) == 3:
            page += 1
            sizes[page] = (int(parts[1]), int(parts[2]))
        elif len(parts) >= 5 and parts[4].strip():
            mid = round((int(parts[2]) + int(parts[3])) / 2)
            rows.append((page, int(parts[0]), int(parts[1]), mid, '\t'.join(parts[4:]).strip()))
    if not rows:
        raise RuntimeError('这份 PDF 里读不出文字（可能是扫描件）。')
    return merge_fragments(rows), sizes


def _band(dx):
    """按离左边距多远分栏（pt）：动作 0，对白 72，括注 108–122，角色名 144–158。"""
    if dx <= 20:
        return 'action'
    if 55 <= dx <= 92:
        return 'dialogue'
    if 93 <= dx <= 132:
        return 'paren'
    if 133 <= dx <= 178:
        return 'character'
    return 'other'


def is_heading(text):
    """这一行是场景标题，或者像场内小标题（全大写的短行，不以句号结尾）。"""
    if FOUNTAIN_SCENE.match(text) or STANDARD_HEAD.match(text) or cd.SCENE_HEAD.match(text):
        return 'scene'
    if is_caps(text) and not text.endswith('.') and len(text.split()) <= 6:
        return 'sub'
    return ''


STD_RIGHT = {'action': WIDTH * PT, 'dialogue': (10 + 35) * PT, 'paren': (15 + 25) * PT}  # 各栏的右界离左边距多远（pt）


def rows_to_elements(rows, sizes):
    """带位置的行 → (标题信息, 元素列表)。"""
    pages = sorted({r[0] for r in rows})
    # 左边距：反复出现的最小横坐标（动作描写和场景标题顶格）。不能取出现最多的，对白多的稿子那会是对白的缩进
    xs = [r[1] for r in rows]
    often = [x for x in set(xs) if xs.count(x) >= 2]
    left = min(often) if often else min(xs)
    middle = left + WIDTH * PT / 2
    by_page = {p: sorted((r for r in rows if r[0] == p), key=lambda r: (-r[3], r[1])) for p in pages}

    def below(a, b):  # b 紧挨在 a 的下一行
        return 0 < a[3] - b[3] <= NEAR

    def centred(r):  # 左右留白一样多，又不是顶格的满行
        return abs((r[1] + r[2]) / 2 - middle) <= 8 and r[1] - left > 14

    def kind_of(seq, k):
        r = seq[k]
        _, x0, x1, y, text = r
        height = sizes.get(r[0], (612, 792))[1]
        if re.fullmatch(r'\d+\.?', text) and (y > height - 66 or y < 50):
            return 'number'
        band = _band(x0 - left)
        up = seq[k - 1] if k and below(seq[k - 1], r) else None
        down = seq[k + 1] if k + 1 < len(seq) and below(r, seq[k + 1]) else None
        if band == 'character' and down and _band(down[1] - left) in ('dialogue', 'paren'):
            return 'character'
        if band == 'action':
            end = k  # 顶格的满行下面紧跟着居中的一行：是折成几行的片名卡，不是动作
            while end + 1 < len(seq) and below(seq[end], seq[end + 1]):
                end += 1
            return 'center' if end > k and centred(seq[end]) else band
        if centred(r) and (not up or centred(up) or _band(up[1] - left) == 'action') and (not down or centred(down)):
            return 'center'  # 片名卡：先于按缩进分栏，免得宽一点的卡被当成对白或括注
        if band == 'dialogue':
            return band
        if band == 'paren' and (text.startswith(('(', '（')) or up):
            return 'paren'
        if x1 >= left + WIDTH * PT - 8:
            return 'transition'
        return 'character' if band == 'character' else 'paren' if band == 'paren' else 'center'

    # 扉页：第一页上没有场景标题、也没有"角色名 + 对白"
    title = {}
    first = by_page[pages[0]]
    spoken = any(kind_of(first, k) == 'character' for k in range(len(first)))
    # 场景标题要顶格才算：扉页上居中的"场 01〈…〉"这类集名不算
    if not spoken and not any(_band(r[1] - left) == 'action' and is_heading(r[4]) == 'scene' for r in first):
        groups = []
        for r in first:
            if groups and below(groups[-1][-1], r):
                groups[-1].append(r)
            else:
                groups.append([r])
        height = sizes.get(pages[0], (612, 792))[1]
        upper = [g for g in groups if g[0][3] > height / 2]
        lower = [g for g in groups if g[0][3] <= height / 2]

        def text(g):
            out = ''
            for r in g:
                out = join_lines(out, r[4]) if out else r[4]
            return out
        # 版本一行：和剧名隔得比剧名各行之间远（本脚本排的是隔两行），或者看得出是稿次
        if len(upper) > 1 and (upper[-2][-1][3] - upper[-1][0][3] >= 30 or
                               re.search(r'(?i)\bdraft\b|\bv\d+(\.\d+)*\b|稿', text(upper[-1]))):
            title['Credit'] = [text(upper.pop())]
        if upper:
            title['Title'] = [text(g) for g in upper]
        if lower and len(lower[-1]) == 1 and len(lower[-1][0][4]) <= 40 and re.search(r'\d', lower[-1][0][4]):
            title['Draft date'] = [text(lower.pop())]
        if lower:
            title['Notes'] = [' '.join(text(g) for g in lower)]  # 说明里分了段的，段与段之间留一个空格
        pages = pages[1:]

    # 各栏的右界：照标准版式；这份稿明显更窄或更宽（别的工具排的）就照它实际的
    right = {}
    for band, std in STD_RIGHT.items():
        seen = [r[2] - left for p in pages for r in by_page[p] if _band(r[1] - left) == band]
        widest = max(seen) if seen else std
        right[band] = left + (widest if widest > std + 15 or std - 60 <= widest < std else std)

    def full(prev, row, band):
        """上一行排满了：这一行开头那一截接在上一行后面放不下，所以这一行是折出来的。"""
        chunk = first_chunk(row[4])
        gap = PT if join_lines(prev[4], chunk) != prev[4] + chunk else 0
        return prev[2] + gap + units(chunk) * UNIT > right[band] + 2

    els, last, more = [], None, False  # last: (页, 类型, 那一行)
    for p in pages:
        seq = by_page[p]
        for k, row in enumerate(seq):
            text = row[4]
            kind = kind_of(seq, k)
            if kind == 'number':
                continue
            if MORE.fullmatch(text):
                more = True
                continue
            if more is True and kind == 'character' and CONTD.search(text):
                more = 'joined'  # 接着上一页那段台词；last 还是 (MORE) 前面那一行
                continue
            new_page = bool(last) and last[0] != p
            near = bool(last) and not new_page and below(last[2], row)
            runs_on = near or more == 'joined'
            if els and els[-1][0] == kind and last[1] == kind and kind in ('action', 'dialogue', 'paren', 'center'):
                prev = last[2]
                if kind == 'dialogue' and runs_on:
                    langs = cd.line_lang(prev[4]), cd.line_lang(text)
                    # 另起一行的两种情况：上一行没排满（手动分的行、对照翻译）；换了语言而上一行已经说完（对照翻译，上一行恰好排满）
                    if not full(prev, row, kind) or (all(langs) and langs[0] != langs[1] and LINE_END.search(prev[4])):
                        els.append((kind, text))
                        last, more = (p, kind, row), False
                        continue
                    carry = True
                elif kind == 'action':
                    # 跨页的动作段：上一页最后一行排满了、话没说完才接；页底的场景标题、小标题不接
                    carry = near or (new_page and full(prev, row, kind) and not SENTENCE_END.search(prev[4])
                                     and not is_heading(text) and not is_heading(els[-1][1]))
                else:
                    carry = near
                if carry:
                    els[-1] = (kind, join_lines(els[-1][1], text))
                    last, more = (p, kind, row), False
                    continue
            if els and not (runs_on and kind in ('paren', 'dialogue') and last[1] in ('character', 'paren', 'dialogue')):
                els.append(('blank', ''))
            els.append((kind, text))
            last, more = (p, kind, row), False

    out = []
    for k, (kind, text) in enumerate(els):
        alone = (k == 0 or els[k - 1][0] == 'blank') and (k + 1 == len(els) or els[k + 1][0] == 'blank')
        if kind == 'action' and alone and is_heading(text):
            kind = is_heading(text)
        out.append((kind, text))
    return title, out


def read_pdf(path):
    rows, sizes = pdf_rows(path)
    return rows_to_elements(rows, sizes)
