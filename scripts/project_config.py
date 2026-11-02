#!/usr/bin/env python3
"""项目制作参数（film-story）：读总表第 5 节（或 0.9.0 及更早的 story/constraints.md）里的人物、地点、禁用词、必填头部、同框上限和制作参数。

两个检查脚本共用。格式见 templates/project.md 第 5 节：标题以"人物 / 地点 / 禁用 / 必填 / 同框 / 制作参数"开头，## 或 ### 都行，可带编号；
"制作参数"一节每行写成"英文语速：4 词/秒""中文语速：4 字/秒""单条生成上限：30 s"，冒号后先写数字，留空就是没配置。
查找顺序：从场景文件所在目录往上，每层先看 story/constraints.md，没有就在 story/*.md 里找带"制作参数"标题的文件（总表）。"""
import re
from pathlib import Path

SECTION = re.compile(r'^(#{2,3})\s*(.+?)\s*$')
NUMBERING = re.compile(r'^\d+(?:\.\d+)*[.、]?\s*')
NUM = re.compile(r'(\d+(?:\.\d+)?)')
RATE_KEYS = (('英文语速', 'wps'), ('中文语速', 'cps'), ('单条生成上限', 'clip_max'))
KEYS = ('人物', '地点', '禁用', '必填', '同框', '制作参数')


def heading(line):
    """二、三级标题的文字（去掉 # 和编号）；不是标题返回 None。"""
    m = SECTION.match(line.strip())
    if not m:
        return None
    return NUMBERING.sub('', m.group(2))


def has_params_heading(path):
    """文件里有没有以"制作参数"开头的标题（总表第 5 节的标志）。"""
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            h = heading(line)
            if h and h.startswith('制作参数'):
                return True
    except (OSError, UnicodeDecodeError):
        pass
    return False


def find_constraints(scene_path):
    """从场景文件所在目录往上找：story/constraints.md，或 story/ 下带"制作参数"标题的总表；找不到返回 None。"""
    d = Path(scene_path).resolve().parent
    for p in [d] + list(d.parents):
        story = p / 'story'
        c = story / 'constraints.md'
        if c.is_file():
            return c
        if story.is_dir():
            cands = sorted(f for f in story.glob('*.md') if has_params_heading(f))
            if cands:
                return cands[0]
    return None


def load_constraints(path):
    cons = {'人物': [], '地点': set(), '禁用': [], '必填头部': [], '同框上限': 2, '制作参数': {}}
    cur = None
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        h = heading(line)
        if h is not None:
            cur = h if h.startswith(KEYS) else None
            continue
        s = line.strip().lstrip('-').strip()
        if not s or not cur:
            continue
        if cur.startswith('人物'):
            for name in re.split(r'[,，/｜|]', s):
                name = name.strip()
                if name and name not in cons['人物']:
                    cons['人物'].append(name)
        elif cur.startswith('地点'):
            cons['地点'].add(s)
        elif cur.startswith('禁用'):
            cons['禁用'].append(s)
        elif cur.startswith('必填'):
            cons['必填头部'].append(s)
        elif cur.startswith('同框'):
            n = NUM.search(s)
            if n:
                cons['同框上限'] = int(float(n.group(1)))
        elif cur.startswith('制作参数'):
            for key, k in RATE_KEYS:
                if s.startswith(key):
                    n = NUM.match(s[len(key):].lstrip('：: '))
                    if n and float(n.group(1)) > 0:
                        cons['制作参数'][k] = float(n.group(1))
    return cons
