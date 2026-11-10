#!/usr/bin/env python3
"""比稿（film-story）。把剧本的两个版本逐场对一遍，报三件事：
  - 结构有没有变：场（场标记）、场景标题、每场的说话人。精修不该动这些；重写动了要回头改节拍单。
  - 改了哪些句子：台词和动作段的 改 / 删 / 加，台词按"本版改动"的写法列出来，贴进剧本头部之前逐条核对。
  - 带上精修简报（--brief）时：简报里锁定的台词是不是逐字都在；指定改法是不是都改了；登记了局部重写的场，
    结构变化单列，不算越界。
另报表演线索前后的数（停手、停顿、对视、填充词、没说完），只数不判，用来看这一轮有没有成套地加停顿和填充词。

用法:
  python3 compare_drafts.py <旧稿.md> <新稿.md> [--brief <精修简报.md>] [--dialogue-only]
                            [--lang auto|en|zh] [--constraints <项目>/story/constraints.md] [--wps N] [--cps N] [--json]
  python3 compare_drafts.py <剧本.md> --rev HEAD [--brief …]   和 git 里的那一版比（HEAD、HEAD~1、tag、提交号都行）
  python3 compare_drafts.py <剧本.md> --brief <精修简报.md>     不比稿，只核对锁定的台词和指定改法
  python3 compare_drafts.py <英文版.md> <中文版.md> --dialogue-only   只比对白：两个语言版本的台词是不是逐句相同
  加 --out <改动清单.md> 把结果另存成一份 Markdown（每版交付的改动清单从这里起，再逐条补上为什么）。
文件可以是 Markdown 剧本，也可以直接给 .pdf、.fountain（先转成 Markdown 再比）。

只比正文（<!-- script-body:start/end --> 之间），只比全文多数台词的那种语言，对照翻译行不比。两版都有场标记时按
场标记对齐，否则按场景标题对齐；只比对白（--dialogue-only）而又没有场标记时按场景的先后对齐，因为两个语言版本
的场景标题写法不同。句子靠字面相似度配对：同一个说话人、改动不大的算"改"，其余算"删"和"加"；
挪了位置的句子会显示成一删一加。一句话被中间插进来的动作拆成连着的几句（或连着的几句并成一句）、同一个说话人、
词没变的，单列成"拆""并"，不算改动；隔着别人的话的不算。锁定的台词被这样拆开的，单独提示，不算少了。

简报里脚本读三样（写法见 templates/polish-brief.md）：
  - "锁定的台词"一节里的行：`- S03 > 原句`
  - "指定改法"一节里的行：`- S06 > 现在的句子 → 改成的句子（原因）`
  - 逐场表里第二栏写着"局部重写"的行：`| S09 · 名字 | 局部重写 | …`
场号 S03、s3、场 03 算同一场。剧本不是每场都有场标记时，锁定的台词和指定改法在全文里找，登记的局部重写认不出，
输出里会提示。
只报事实，不判好坏；退出码恒为 0。"""
import argparse, contextlib, difflib, io, json, os, re, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_dialogue as cd  # noqa: E402

PAIR = {'line': 0.4, 'para': 0.5}  # 字面相似度到这个数才算"改"，不到算一删一加 [推论]
CLIP = 60                          # 动作段在清单里最多显示这么多格
LOCKED = re.compile(r'^[-*]\s*((?:S|场\s*)\d+[a-z]?)\s*>\s*(.+?)\s*$', re.I)
SCENE_CELL = re.compile(r'^\**\s*((?:S|场\s*)\d+[a-z]?)\b', re.I)
REASON = re.compile(r'\s*(?:（[^）]*）|\s\([^)]*\))\s*$')  # 指定改法末尾括号里的原因，全角半角都认
QUOTES = str.maketrans({'“': '"', '”': '"', '‘': "'", '’': "'"})
ARROW = re.compile(r'\s*(?:→|->)\s*')


def units(scenes, by_mark):
    """按场归并：{key: {'label', 'titles', 'lines', 'paras'}}，保持出现的顺序。
    by_mark：按场标记归并（一场可以有几个场景标题）；否则一个场景标题一个单位，重名的按出现次序区分。"""
    out, seen = {}, {}
    for sc in scenes:
        if by_mark:
            key, label = cd.mark_label(sc['mark']), sc['mark']
        else:
            seen[sc['title']] = seen.get(sc['title'], 0) + 1
            key = sc['title'] + ('' if seen[sc['title']] == 1 else f" #{seen[sc['title']]}")
            label = key
        u = out.setdefault(key, {'label': label, 'titles': [], 'lines': [], 'paras': []})
        u['titles'].append(sc['title'])
        u['lines'] += [(x['speaker'], x['text']) for x in sc['lines']]
        u['paras'] += [' '.join(t for _, t in para) for para in cd.action_paragraphs(sc)]
    return out


def mark_state(scenes):
    """'all'：每一段都在某个场标记下面；'some'：只有一部分有；'none'：没有场标记。"""
    marks = [bool(sc['mark']) for sc in scenes if sc['lines'] or sc['action'] or sc['mark']]
    return 'all' if marks and all(marks) else 'some' if any(marks) else 'none'


def ratio(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def diff_items(old, new, same_owner, text_of, threshold, key_of=repr):
    """两串条目对一遍 → (改 [(旧, 新)], 删 [旧], 加 [新])。same_owner：两条能不能配成"改"（台词要同一个说话人）。
    key_of：两条算不算同一条（台词不计角色名的大小写）。"""
    changed, removed, added = [], [], []
    sm = difflib.SequenceMatcher(None, [key_of(x) for x in old], [key_of(x) for x in new], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        a, b = list(old[i1:i2]), list(new[j1:j2])
        while a and b:
            if same_owner(a[0], b[0]) and ratio(text_of(a[0]), text_of(b[0])) >= threshold:
                changed.append((a.pop(0), b.pop(0)))
            elif any(same_owner(a[0], y) and ratio(text_of(a[0]), text_of(y)) >= threshold for y in b[1:]):
                added.append(b.pop(0))    # 旧句在后面还配得上：眼前这条新句是加的
            else:
                removed.append(a.pop(0))  # 旧句配不上任何新句：删了
        removed += a
        added += b
    return changed, removed, added


def regroup(old, new):
    """先把拆句和并句挑出来。拆：旧的一句 == 新的连着几句接起来——同一个说话人，中间没有别人说话（隔着动作可以），
    词没变。并：反过来。只在两版对不上的那一段里找，隔开的句子不算。
    返回 (拆 [(旧, [新…])], 并 [([旧…], 新)], 剩下的旧, 剩下的新)。"""
    key = lambda x: (x[0].casefold(), x[1])  # noqa: E731
    split, merged, used_old, used_new = [], [], set(), set()

    def run(one, many, lo, hi, used):
        """many[lo:hi] 里有没有连着的几句，接起来正好是 one。"""
        target = squash(one[1])
        for j in range(lo, hi):
            acc, k = '', j
            while k < hi and k not in used and many[k][0].casefold() == one[0].casefold() and squash(many[k][1]) \
                    and target.startswith(acc + squash(many[k][1])):
                acc += squash(many[k][1])
                k += 1
            if target and acc == target and k - j > 1:
                return range(j, k)
        return None

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [key(x) for x in old], [key(x) for x in new], autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        for i in range(i1, i2):
            hit = run(old[i], new, j1, j2, used_new)
            if hit:
                split.append((old[i], [new[j] for j in hit]))
                used_old.add(i)
                used_new.update(hit)
        for j in range(j1, j2):
            hit = None if j in used_new else run(new[j], old, i1, i2, used_old)
            if hit:
                merged.append(([old[i] for i in hit], new[j]))
                used_new.add(j)
                used_old.update(hit)
    return (split, merged, [x for i, x in enumerate(old) if i not in used_old],
            [x for j, x in enumerate(new) if j not in used_new])


def volume(lines, lang, rate):
    size = sum(cd.size_of(t, lang) for _, t in lines)
    return size, (round(size / rate, 1) if rate else None)


def unquote(text):
    text = text.translate(QUOTES).strip()
    return text[1:-1].strip() if len(text) > 1 and text[0] == text[-1] == '"' else text


def read_brief(path):
    """精修简报里脚本要用的三样：锁定的台词 [(场号, 原句)]，指定改法 [(场号, 旧句, 新句)]，登记了局部重写的场 {场号}。"""
    locked, edits, rewrite, where = [], [], set(), ''
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if s.startswith('#'):
            where = 'locked' if '锁定' in s and '台词' in s else 'edits' if '指定改法' in s else ''
            continue
        m = LOCKED.match(s)
        if m and where == 'locked':
            locked.append((m.group(1), unquote(m.group(2))))
        elif m and where == 'edits':
            parts = ARROW.split(REASON.sub('', m.group(2)), maxsplit=1)
            if len(parts) == 2:
                edits.append((m.group(1), unquote(parts[0]), unquote(parts[1])))
        if s.startswith('|'):  # 逐场表：第一栏是场，第二栏正好是"局部重写"才算登记
            cells = [c.strip() for c in s.strip('|').split('|')]
            m = SCENE_CELL.match(cells[0]) if len(cells) > 1 else None
            if m and cells[1].strip('* ') == '局部重写':
                rewrite.add(cd.mark_label(m.group(1)))
    return locked, edits, rewrite


def norm(text):
    return re.sub(r'\s+', ' ', text.translate(QUOTES)).strip()


def squash(text):
    """不计空格：两句接起来和原来那一句比的时候用（中文接的时候没有空格）。"""
    return re.sub(r'\s+', '', text.translate(QUOTES))


def pool_of(us, by_mark, scene):
    """这一场的台词。没有按场标记对齐时在全文里找；按场标记对齐而剧本里没有这一场，返回 None。"""
    if not by_mark:
        return [t for u in us.values() for _, t in u['lines']]
    key = cd.mark_label(scene)
    return [t for _, t in us[key]['lines']] if key in us else None


def check_locked(us, by_mark, locked):
    """锁定的台词是不是逐字都在（在它那一场的某句台词里）。词都在、但被拆到了连着的两三句里的，单列。
    返回 {'total', 'missing': [{'scene', 'text', 'closest', 'no_scene'}], 'split': [{'scene', 'text'}]}。"""
    missing, split = [], []
    for scene, text in locked:
        pool = pool_of(us, by_mark, scene)
        if pool is None:
            missing.append({'scene': scene, 'text': text, 'closest': '', 'no_scene': True})
        elif any(norm(text) in norm(t) for t in pool):
            continue
        elif any(squash(text) in squash(''.join(pool[k:k + n])) for n in (2, 3) for k in range(len(pool) - n + 1)):
            split.append({'scene': scene, 'text': text})
        else:
            best = max(pool or [''], key=lambda t: ratio(norm(text), norm(t)))
            missing.append({'scene': scene, 'text': text, 'no_scene': False,
                            'closest': best if ratio(norm(text), norm(best)) >= 0.5 else ''})
    return {'total': len(locked), 'missing': missing, 'split': split}


def check_edits(us, by_mark, edits):
    """指定改法是不是都改了：新句要在它那一场里。返回 {'total', 'missing': [{'scene', 'old', 'new', 'old_still'}]}。"""
    missing = []
    for scene, old, new in edits:
        pool = pool_of(us, by_mark, scene)
        if pool is None:
            missing.append({'scene': scene, 'old': old, 'new': new, 'old_still': False, 'no_scene': True})
        elif not any(norm(new) in norm(t) for t in pool):
            missing.append({'scene': scene, 'old': old, 'new': new, 'no_scene': False,
                            'old_still': any(norm(old) in norm(t) for t in pool)})
    return {'total': len(edits), 'missing': missing}


def perf_totals(scenes):
    out = {k: 0 for k, _ in cd.PERF_KEYS}
    for sc in scenes:
        cues = cd.performance_cues(sc)
        for k in out:
            out[k] += cues[k]
    return out


def locked_only(path, brief, lang='auto'):
    scenes, meta = cd.parse(path, lang)
    marks = mark_state(scenes)
    locked, edits, _ = read_brief(brief)
    us = units(scenes, marks == 'all')
    return {'lang': meta['lang'], 'by_mark': marks == 'all', 'marks': marks,
            'locked': check_locked(us, marks == 'all', locked), 'edits': check_edits(us, marks == 'all', edits)}


def compare(old_path, new_path, lang='auto', constraints=None, wps=None, cps=None, brief=None, dialogue_only=False):
    """返回比稿结果（字典）。语言按新稿定，两版用同一种语言读。"""
    new_scenes, meta = cd.parse(new_path, lang)
    lang = meta['lang']
    old_scenes, old_meta = cd.parse(old_path, lang)
    rates, _, _, warn = cd.project_settings(new_path, constraints, wps, cps)
    rate = rates.get('wps' if lang == 'en' else 'cps')
    states = {mark_state(old_scenes), mark_state(new_scenes)}
    by_mark = states == {'all'}
    marks = 'all' if by_mark else 'none' if states == {'none'} else 'some'
    old, new = units(old_scenes, by_mark), units(new_scenes, by_mark)
    counts = [len(old), len(new)]
    found = []  # (场的 key 或 None, 说明)
    if dialogue_only and not by_mark:  # 两个语言版本：标题对不上，按先后配；个数不同就整份当一段比，并照实报
        if counts[0] != counts[1]:
            whole = lambda us: {'(全文)': {'label': '(全文)', 'titles': [], 'paras': [],  # noqa: E731
                                         'lines': [x for u in us.values() for x in u['lines']]}}
            old, new = whole(old), whole(new)
            found.append((None, f'场景标题的个数不同：{counts[0]} → {counts[1]}，没法一场对一场，整份按先后比'))
        else:
            old, new = ({f'#{k}': u for k, u in enumerate(us.values(), 1)} for us in (old, new))
    locked, edits, rewrite = read_brief(brief) if brief else ([], [], set())
    for k in old:
        if k not in new:
            found.append((k, f"少了场：{old[k]['label']}"))
    for k in new:
        if k not in old:
            found.append((k, f"多了场：{new[k]['label']}"))
    common = [k for k in new if k in old]
    if [k for k in old if k in new] != common:
        found.append((None, '场的顺序变了：' + ' → '.join(new[k]['label'].split(' · ')[0] for k in common)))
    per, items = [], []
    for k in common:
        o, n = old[k], new[k]
        tag = n['label'].split(' · ')[0] if by_mark else n['label']
        if o['titles'] != n['titles'] and not dialogue_only:
            gone = [t for t in o['titles'] if t not in n['titles']]
            came = [t for t in n['titles'] if t not in o['titles']]
            what = '；'.join(x for x in ('少了 ' + '、'.join(gone) if gone else '', '多了 ' + '、'.join(came) if came else '') if x)
            found.append((k, f"{tag}：场景标题 {len(o['titles'])} → {len(n['titles'])}（{what or '顺序变了'}）"))
        so = {s.casefold(): s for s, _ in o['lines']}
        sn = {s.casefold(): s for s, _ in n['lines']}
        lost, got = [so[x] for x in so if x not in sn], [sn[x] for x in sn if x not in so]
        if lost or got:
            found.append((k, f"{tag}：说话人" + '；'.join(x for x in ('少了 ' + '、'.join(lost) if lost else '',
                                                                 '多了 ' + '、'.join(got) if got else '') if x)))
        split, merged, rest_old, rest_new = regroup(o['lines'], n['lines'])
        lc, lr, la = diff_items(rest_old, rest_new, lambda a, b: a[0].casefold() == b[0].casefold(),
                                lambda x: x[1], PAIR['line'], key_of=lambda x: (x[0].casefold(), x[1]))
        pc, pr, pa = ([], [], []) if dialogue_only else diff_items(o['paras'], n['paras'], lambda a, b: True,
                                                                   lambda x: x, PAIR['para'])
        (s0, t0), (s1, t1) = volume(o['lines'], lang, rate), volume(n['lines'], lang, rate)
        per.append({'scene': n['label'], 'lines': [len(o['lines']), len(n['lines'])], 'size': [s0, s1], 'seconds': [t0, t1],
                    'line_changed': len(lc), 'line_removed': len(lr), 'line_added': len(la),
                    'line_split': len(split), 'line_merged': len(merged),
                    'para_changed': len(pc), 'para_removed': len(pr), 'para_added': len(pa)})
        items += [{'scene': tag, 'kind': '拆', 'what': 'line', 'old': a[1], 'new': ' ｜ > '.join(x[1] for x in parts),
                   'speaker': a[0]} for a, parts in split]
        items += [{'scene': tag, 'kind': '并', 'what': 'line', 'old': ' ｜ > '.join(x[1] for x in parts), 'new': a[1],
                   'speaker': a[0]} for parts, a in merged]
        items += [{'scene': tag, 'kind': '改', 'what': 'line', 'old': a[1], 'new': b[1], 'speaker': b[0]} for a, b in lc]
        items += [{'scene': tag, 'kind': '删', 'what': 'line', 'old': a[1], 'speaker': a[0]} for a in lr]
        items += [{'scene': tag, 'kind': '加', 'what': 'line', 'new': b[1], 'speaker': b[0]} for b in la]
        items += [{'scene': tag, 'kind': '改', 'what': 'para', 'old': a, 'new': b} for a, b in pc]
        items += [{'scene': tag, 'kind': '删', 'what': 'para', 'old': a} for a in pr]
        items += [{'scene': tag, 'kind': '加', 'what': 'para', 'new': b} for b in pa]
    total = lambda us: (sum(len(u['lines']) for u in us.values()), sum(len(u['paras']) for u in us.values()),  # noqa: E731
                        volume([x for u in us.values() for x in u['lines']], lang, rate))
    return {'lang': lang, 'by_mark': by_mark, 'marks': marks, 'n_units': counts,
            'dialogue_only': dialogue_only, 'unseen_rewrite': bool(rewrite) and not by_mark,
            'structure': [msg for k, msg in found if k not in rewrite],
            'declared': [msg for k, msg in found if k in rewrite],
            'locked': check_locked(new, by_mark, locked) if brief else None,
            'edits': check_edits(new, by_mark, edits) if brief else None,
            'performance': None if dialogue_only else {'old': perf_totals(old_scenes), 'new': perf_totals(new_scenes)},
            'scenes': per, 'items': items, 'old_total': total(old), 'new_total': total(new),
            'unit': cd.UNIT_NAME[lang], 'body': [old_meta['body'], meta['body']], 'warn': warn}


def clip(text):
    out, w = '', 0
    for ch in text:
        w += cd.display_width(ch)
        if w > CLIP:
            return out + '…'
        out += ch
    return out


def from_git(path, rev):
    """取 git 里 rev 那一版，存成临时文件。返回 (临时文件路径 或 None, 出错说明)。"""
    p = Path(os.path.realpath(path))
    top = subprocess.run(['git', '-C', str(p.parent), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if top.returncode:
        return None, f'{path} 不在 git 仓库里；改成给两个文件：旧稿 新稿'
    root = Path(os.path.realpath(top.stdout.strip()))
    rel = p.relative_to(root).as_posix()
    got = subprocess.run(['git', '-C', str(root), 'show', f'{rev}:{rel}'], capture_output=True)
    if got.returncode:
        return None, f'git 里没有 {rev}:{rel}（这个文件在那一版还没提交过？）'
    tmp = tempfile.NamedTemporaryFile(prefix='old-', suffix=p.suffix or '.md', delete=False)
    tmp.write(got.stdout)
    tmp.close()
    return tmp.name, ''


MARKS_NOTE = {'some': '不是每个场景标题前都有场标记', 'none': '没有场标记'}


def show_locked(lk, marks='all'):
    if lk is None:
        return
    if lk['total'] and marks != 'all':
        print(f"  ⚠ {MARKS_NOTE[marks]}：锁定的台词和指定改法在全文里找，不分场。")
    if not lk['total']:
        print('  锁定的台词：简报里没有列（"锁定的台词"一节下面写 `- S03 > 原句`）。')
    elif not lk['missing'] and not lk['split']:
        print(f"  锁定的台词：{lk['total']} 句逐字都在。")
    if lk['missing']:
        print(f"  ⚠ 锁定的台词少了 {len(lk['missing'])} 句（共 {lk['total']} 句）：")
        for x in lk['missing']:
            why = '剧本里没有这一场的场标记' if x['no_scene'] else \
                f"现在最接近的一句：{x['closest']}" if x['closest'] else '这一场里找不到接近的'
            print(f"    - {x['scene']} > {x['text']}（{why}）")
    if lk['split']:
        print(f"  ⚠ 锁定的台词有 {len(lk['split'])} 句被拆开了（词都在，分到了连着的几句里；算不算数由用户定）：")
        for x in lk['split']:
            print(f"    - {x['scene']} > {x['text']}")


def show_edits(ed):
    if not ed or not ed['total']:
        return
    if not ed['missing']:
        print(f"  指定改法：{ed['total']} 处都改了。")
    else:
        print(f"  ⚠ 指定改法有 {len(ed['missing'])} 处没改（共 {ed['total']} 处）：")
        for x in ed['missing']:
            why = '剧本里没有这一场的场标记' if x['no_scene'] else \
                '旧句还在：' + x['old'] if x['old_still'] else '旧句也不在了，核对一下改成了什么'
            print(f"    - {x['scene']} > {x['new']}（{why}）")


def show(r, old_name, new_name):
    """打印比稿结果。"""
    c = lambda key: sum(s[key] for s in r['scenes'])  # noqa: E731
    sec = lambda t: f"约 {t:g} s" if t is not None else ''  # noqa: E731
    (ol, op, (osz, ot)), (nl, np_, (nsz, nt)) = r['old_total'], r['new_total']
    print(f"== 比稿：{old_name} → {new_name} ==")
    how = f"按场标记对齐（{r['n_units'][0]} → {r['n_units'][1]} 场）" if r['by_mark'] else \
        f"{MARKS_NOTE[r['marks']]}，按场景的先后对齐（{r['n_units'][0]} → {r['n_units'][1]} 个）" if r['dialogue_only'] else \
        f"{MARKS_NOTE[r['marks']]}，按场景标题对齐（{r['n_units'][0]} → {r['n_units'][1]} 个）"
    print(f"  语言：{cd.LANG_NAME[r['lang']]} · {how}" + (' · 只比对白' if r['dialogue_only'] else ''))
    if 'no-markers' in r['body']:
        print('  ⚠ 有一版没有正文标记，按全文读：头部和批注会混进来，结果只作参考')
    what = '场、每场的说话人' if r['dialogue_only'] else '场、场景标题、每场的说话人'
    if r['structure']:
        print('  结构变了（精修不该出现；是重写的话，回头改节拍单）：')
        for x in r['structure']:
            print('    - ' + x)
    else:
        print(f"  结构：{what}都没变。" if not r['declared'] else f"  结构：没登记的场，{what}都没变。")
    if r['declared']:
        print('  登记了局部重写的场有结构变化（简报里写了，不算越界）：')
        for x in r['declared']:
            print('    - ' + x)
    if r['unseen_rewrite']:
        print(f"  ⚠ {MARKS_NOTE[r['marks']]}：认不出简报里登记了局部重写的场，它的结构变化会列在上面。")
    show_locked(r['locked'], r['marks'])
    show_edits(r['edits'])
    vol = f" · {osz} → {nsz} {r['unit']}" + (f"（{sec(ot)} → {sec(nt)}）" if ot is not None else '')
    moved = ''.join(f" · {name} {c(key)}" for key, name in (('line_split', '拆'), ('line_merged', '并')) if c(key))
    print(f"  台词：{ol} → {nl} 句 · 改 {c('line_changed')} · 删 {c('line_removed')} · 加 {c('line_added')}{moved}{vol}")
    if not r['dialogue_only']:
        print(f"  动作：{op} → {np_} 段 · 改 {c('para_changed')} · 删 {c('para_removed')} · 加 {c('para_added')}")
    if r['performance']:
        po, pn = r['performance']['old'], r['performance']['new']
        print('  表演线索（只数不判）：' + ' · '.join(f"{name} {po[k]} → {pn[k]}" for k, name in cd.PERF_KEYS))
    touched = [s for s in r['scenes'] if any(s[k] for k in s if k.startswith(('line_', 'para_')))]
    if touched:
        print('  按场（只列有变化的）：')
        for s in touched:
            t = f" · {sec(s['seconds'][0])} → {sec(s['seconds'][1])}" if s['seconds'][0] is not None else ''
            act = '' if r['dialogue_only'] else f" · 动作 改 {s['para_changed']} 删 {s['para_removed']} 加 {s['para_added']}"
            moved = ''.join(f" {name} {s[key]}" for key, name in (('line_split', '拆'), ('line_merged', '并')) if s[key])
            print(f"    {s['scene']}：台词 改 {s['line_changed']} 删 {s['line_removed']} 加 {s['line_added']}{moved}{t}{act}")
    lines = [x for x in r['items'] if x['what'] == 'line']
    paras = [x for x in r['items'] if x['what'] == 'para']
    if lines:
        print('\n  本版改动 · 台词（贴进剧本头部之前逐条核对；脚本只对字面）：')
        for x in lines:
            if x['kind'] in ('拆', '并'):
                print(f"  - {x['scene']} {x['kind']}：> {x['old']} → > {x['new']}（词没变）")
            elif x['kind'] == '改':
                print(f"  - {x['scene']} 改：> {x['old']} → > {x['new']}")
            else:
                print(f"  - {x['scene']} {x['kind']}：> {x.get('old') or x.get('new')}（{x['speaker']}）")
    if paras:
        print('\n  动作段的变化（写进本版改动时一场并成一句）：')
        for x in paras:
            if x['kind'] == '改':
                print(f"  - {x['scene']} 改：> {clip(x['old'])} → > {clip(x['new'])}")
            else:
                print(f"  - {x['scene']} {x['kind']}：> {clip(x.get('old') or x.get('new'))}")
    if not lines and not paras and not r['structure'] and not r['declared']:
        print('  两版的台词一字未改。' if r['dialogue_only'] else '  两版的台词和动作一字未改。')
    if r['warn']:
        print(f"  ⚠ {r['warn']}")
    print('\n说明：只对字面，不判好坏。结构一行不干净，说明这一轮动了没登记的场、场景标题或说话人。')


def as_markdown(text, old_name, new_name):
    """把打印出来的比稿结果整理成一份 Markdown 改动清单。"""
    out = [f'# 改动清单 · {old_name} → {new_name}', '',
           '脚本只对字面列出改了什么；每条后面补一句为什么（对应哪条意见）。', '']
    for line in text.splitlines()[1:]:
        s = line.strip()
        if not s or s.startswith('说明：'):
            continue
        if s.startswith(('本版改动', '动作段的变化', '按场')):
            out += ['', '## ' + s.rstrip('：')]
        else:
            out.append('- ' + (s[2:] if s.startswith('- ') else s))
    return '\n'.join(out) + '\n'


def main():
    ap = argparse.ArgumentParser(description='比稿（film-story）：两版剧本的结构有没有变、改了哪些句子；带精修简报时核对锁定的台词和指定改法。')
    ap.add_argument('files', nargs='+', help='旧稿 新稿；或只给一个文件，加 --rev 或 --brief')
    ap.add_argument('--rev', help='和 git 里的这一版比（只给一个文件时用），如 HEAD')
    ap.add_argument('--brief', help='精修简报：核对锁定的台词和指定改法；登记了局部重写的场，结构变化单列')
    ap.add_argument('--dialogue-only', action='store_true', help='只比对白，不比动作和场景标题（核对两个语言版本）')
    ap.add_argument('--out', help='把比稿结果另存成 Markdown 改动清单')
    ap.add_argument('--lang', choices=('auto', 'en', 'zh'), default='auto')
    ap.add_argument('--constraints', help='项目约束文件；不给时从新稿往上找 story/constraints.md')
    ap.add_argument('--wps', type=float, help='英文语速（词/秒），临时覆盖配置')
    ap.add_argument('--cps', type=float, help='中文语速（字/秒），临时覆盖配置')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.brief and not Path(a.brief).is_file():
        print(f'== 比稿 ==\n  ⚠ 找不到精修简报：{a.brief}')
        return
    if a.out and not Path(a.out).resolve().parent.is_dir():
        print(f'== 比稿 ==\n  ⚠ 要写到的目录不存在：{Path(a.out).resolve().parent}')
        return
    tmp = None
    if len(a.files) == 1 and a.brief and not a.rev:
        try:
            r = locked_only(a.files[0], a.brief, a.lang)
        except RuntimeError as err:
            print(f'== 比稿 ==\n  ⚠ {err}')
            return
        if a.out:
            print('（--out 没有写：只给一份稿时只核对锁定的台词，没有两版可比）', file=sys.stderr if a.json else sys.stdout)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print(f"== 核对锁定的台词和指定改法：{Path(a.files[0]).name} ==")
            show_locked(r['locked'], r['marks'])
            show_edits(r['edits'])
        return
    if a.rev and len(a.files) == 1:
        new = a.files[0]
        tmp, err = from_git(new, a.rev)
        if not tmp:
            print(f'== 比稿 ==\n  ⚠ {err}')
            return
        old, old_name = tmp, f'{a.rev}:{Path(new).name}'
    elif len(a.files) == 2 and not a.rev:
        old, new = a.files
        old_name = Path(old).name
    else:
        print('== 比稿 ==\n  用法：compare_drafts.py <旧稿.md> <新稿.md>，或 compare_drafts.py <剧本.md> --rev HEAD，'
              '或 compare_drafts.py <剧本.md> --brief <精修简报.md>')
        return
    try:
        r = compare(old, new, a.lang, a.constraints, a.wps, a.cps, a.brief, a.dialogue_only)
    except RuntimeError as err:
        print(f'== 比稿 ==\n  ⚠ {err}')
        return
    finally:
        if tmp:
            os.unlink(tmp)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show(r, old_name, Path(new).name)
    if a.out:
        Path(a.out).write_text(as_markdown(buf.getvalue(), old_name, Path(new).name), encoding='utf-8')
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(buf.getvalue(), end='')
        if a.out:
            print(f'改动清单已写到 {a.out}')


if __name__ == '__main__':
    main()
