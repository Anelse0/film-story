#!/usr/bin/env python3
"""项目约束文件（film-story）：找 <项目>/story/constraints.md，读人物、地点、禁用词、必填头部、同框上限和制作参数。

两个检查脚本共用。约束文件格式见 templates/constraints.md：各节标题以"## 人物 / 地点 / 禁用 / 必填 / 同框 / 制作参数"开头；
"制作参数"一节每行写成"英文语速：4 词/秒""中文语速：4 字/秒""单条生成上限：30 s"，冒号后先写数字，留空就是没配置。"""
import re
from pathlib import Path

SECTION = re.compile(r'^##\s*(.+?)\s*$')
NUM = re.compile(r'(\d+(?:\.\d+)?)')
RATE_KEYS = (('英文语速', 'wps'), ('中文语速', 'cps'), ('单条生成上限', 'clip_max'))


def find_constraints(scene_path):
    """从场景文件所在目录往上找 story/constraints.md；找不到返回 None。"""
    d = Path(scene_path).resolve().parent
    for p in [d] + list(d.parents):
        c = p / 'story' / 'constraints.md'
        if c.is_file():
            return c
    return None


def load_constraints(path):
    cons = {'人物': [], '地点': set(), '禁用': [], '必填头部': [], '同框上限': 2, '制作参数': {}}
    cur = None
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        m = SECTION.match(line.strip())
        if m:
            cur = m.group(1)
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
