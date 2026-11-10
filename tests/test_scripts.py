"""检查脚本回归：正文边界、台词块、语言、画内 / 画外、制作参数、表面线索的命名、约束检查只查正文（0.6.0）；
标准剧本格式的 Markdown、动作描写线索、Fountain / Markdown / 标准版面互转（0.7.1）。
场标记与按场取出（0.7.2）；比稿：结构有没有变、改了哪些句子，带精修简报核对锁定的台词（0.7.3）；
表演线索、占位符、指定改法，场标记分场与场号归一（0.7.4）。
夹具在 tests/fixtures/；每个用例先把夹具复制到临时目录，免得往上找到真实项目的 story/constraints.md。"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import check_dialogue as cd  # noqa: E402
from project_config import load_constraints  # noqa: E402


def scenes_of(path, lang='auto'):
    return cd.parse(path, lang)[0]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / 'tests' / 'fixtures', self.tmp / 'fx')
        self.fx = self.tmp / 'fx'
        self.cons = self.fx / 'project' / 'story' / 'constraints.md'

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_script(self, name, *args):
        r = subprocess.run([sys.executable, str(SCRIPTS / name)] + [str(x) for x in args],
                           capture_output=True, text=True, cwd=str(self.tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def texts(self, path, lang='auto'):
        return [x['text'] for sc in scenes_of(path, lang) for x in sc['lines']]


class BodyBounds(Base):
    def test_annotations_after_body_not_counted(self):
        scenes, meta = cd.parse(self.fx / 'body-annotations.md')
        self.assertEqual(meta['body'], 'markers')
        self.assertEqual(len(scenes), 1)
        self.assertEqual(self.texts(self.fx / 'body-annotations.md'), ['You came.', 'Told you.'])

    def test_no_markers_reads_whole_file(self):
        scenes, meta = cd.parse(self.fx / 'no-markers.md')
        self.assertEqual(meta['body'], 'no-markers')
        self.assertEqual(self.texts(self.fx / 'no-markers.md'), ["You're late.", 'Traffic.'])
        self.assertIn('旧文件兼容', self.run_script('check_dialogue.py', self.fx / 'no-markers.md'))

    def test_unpaired_markers_reported(self):
        scenes, meta = cd.parse(self.fx / 'unpaired.md')
        self.assertTrue(meta['body'].startswith('unpaired'))
        self.assertEqual(self.texts(self.fx / 'unpaired.md'), ["You're late.", 'Traffic.'])
        self.assertIn('正文标记不成对', self.run_script('check_dialogue.py', self.fx / 'unpaired.md'))


class Blocks(Base):
    def test_multiline_speech_and_name_translation(self):
        self.assertEqual(self.texts(self.fx / 'multiline.md'), [
            'Rhett.', "Yeah. That should've been an easy question. But I guess I couldn't always tell what was real."])

    def test_blank_lines_between_cue_paren_and_line(self):
        lines = scenes_of(self.fx / 'loose.md')[0]['lines']
        self.assertEqual([(x['speaker'], x['text']) for x in lines], [
            ('EZRA', 'That was really good.'), ('EVELYN', 'Hey. You came.'), ('June', 'Clothes— the chair.')])
        self.assertEqual(lines[0]['paren'], '（真心实意地，语气放松）')

    def test_inline_labels_and_scene_heading(self):
        scenes = scenes_of(self.fx / 'inline.md')
        self.assertEqual(scenes[0]['title'], '07｜内景 June 家／Vera 工作室—7:02 PM')
        self.assertEqual([x['speaker'] for x in scenes[0]['lines']], ['June', 'Vera', 'June'])


class Language(Base):
    def test_zh_auto(self):
        scenes, meta = cd.parse(self.fx / 'zh-scene.md')
        self.assertEqual(meta['lang'], 'zh')
        r = cd.analyse(scenes[0], meta['lang'])
        self.assertEqual(r['n_lines'], 4)
        self.assertEqual(r['unit'], '字')
        self.assertTrue(r['unsupported'])
        tags = {m['text']: m['tags'] for m in r['marked_lines']}
        self.assertIn(cd.TAG['antithesis'], tags['加班。不是我想晚，而是事情没做完。'])
        self.assertIn(cd.TAG['recap'], tags['你说过这周不加班的。'])
        self.assertEqual(r['speakers']['妈妈']['questions'], 1)

    def test_forced_lang_reports_what_was_left_out(self):
        out = self.run_script('check_dialogue.py', self.fx / 'zh-scene.md', '--lang', 'en')
        self.assertIn('未计入', out)
        self.assertIn('--lang zh', out)

    def test_zh_output_names_unsupported_cue(self):
        self.assertIn('中文不支持的线索', self.run_script('check_dialogue.py', self.fx / 'zh-scene.md'))


class Offscreen(Base):
    def test_phone_voices_are_offscreen(self):
        lines = scenes_of(self.fx / 'phone.md')[0]['lines']
        self.assertEqual([(x['speaker'], x['offscreen']) for x in lines],
                         [('JO', True), ('THEO', False), ('HOLLIS', True), ('THEO', False)])

    def test_constraints_split_on_and_offscreen(self):
        out = self.run_script('check_constraints.py', self.fx / 'phone.md', '--constraints', self.cons)
        self.assertIn('画内 1：Theo；画外 2：Jo、Hollis', out)
        self.assertNotIn('超过同框上限', out)
        self.assertIn('动作描写提到的已登记人物：Theo、Rhett', out)


class Config(Base):
    def test_rates_parse_blank_and_comment_lines(self):
        self.assertEqual(load_constraints(self.cons)['制作参数'], {'wps': 4.0, 'clip_max': 10.0})

    def test_discovery_and_clip_warning(self):
        meta, rs = cd.report(self.fx / 'project' / 'ep01' / '03_script' / 's01-long.md')
        self.assertTrue(meta['config'].endswith('constraints.md'))
        self.assertEqual(rs[0]['est_seconds'], round(rs[0]['total_size'] / 4, 1))
        self.assertTrue(any('超过单条生成上限 10 s' in f for f in rs[0]['flags']))

    def test_no_config_means_no_seconds(self):
        meta, rs = cd.report(self.fx / 'no-markers.md')
        self.assertIsNone(meta['config'])
        self.assertIsNone(rs[0]['est_seconds'])
        self.assertIn('不估算时长', cd.describe(meta))

    def test_cli_rate_override(self):
        meta, rs = cd.report(self.fx / 'no-markers.md', wps=2)
        self.assertEqual(rs[0]['est_seconds'], round(rs[0]['total_size'] / 2, 1))


class Labels(Base):
    def test_surface_cue_wording(self):
        out = self.run_script('check_dialogue.py', self.fx / 'questions.md')
        self.assertIn('连续接话', out)
        self.assertIn('表面线索', out)
        self.assertNotIn('精准', out)

    def test_question_share_flag(self):
        r = cd.analyse(scenes_of(self.fx / 'questions.md')[0])
        self.assertTrue(any(f.startswith('THEO 的 4 句里 4 句是问句') for f in r['flags']), r['flags'])

    def test_display_names(self):
        sc = scenes_of(self.fx / 'questions.md')[0]
        self.assertIn('DJ', cd.analyse(sc)['speakers'])
        self.assertIn('Theo', cd.analyse(sc, names={'theo': 'Theo'})['speakers'])


class Constraints(Base):
    def hole(self, text):
        p = self.fx / 'hole.md'
        p.write_text((self.fx / 'episode.md').read_text(encoding='utf-8').replace('One more.', text), encoding='utf-8')
        return p

    def test_forbidden_word_outside_body_ignored(self):
        out = self.run_script('check_constraints.py', self.fx / 'body-annotations.md', '--constraints', self.cons)
        self.assertIn('禁用词（只查正文）：无', out)
        self.assertIn('头部必填项：齐', out)
        for w in ('Mike', 'Torres', 'Remember'):
            self.assertNotIn(w, out)

    def test_forbidden_word_in_body_flagged(self):
        p = self.fx / 'kiss.md'
        p.write_text('<!-- script-body:start -->\n场 01 · 内 · 车里 · 夜\n\nTheo leans in for a kiss.\n<!-- script-body:end -->\n',
                     encoding='utf-8')
        self.assertIn('行4 “kiss”', self.run_script('check_constraints.py', p, '--constraints', self.cons))

    def test_missing_header_reported(self):
        out = self.run_script('check_constraints.py', self.fx / 'unpaired.md', '--constraints', self.cons)
        self.assertIn('缺 本场改变了什么：、新事实（提案）：', out)

    def test_placeholders_listed(self):
        p = self.hole('[AGENCY] wants one more. See [the note](x) and [CANON: name].')
        c = self.fx / 'ep-cons2.md'
        c.write_text('## 人物\n- Dev, Mara\n', encoding='utf-8')
        out = self.run_script('check_constraints.py', p, '--constraints', c)
        self.assertIn('[AGENCY]', out)
        self.assertIn('[CANON: name]', out)
        self.assertNotIn('[the note]', out)
        self.assertIn('占位符（锁稿前清零）：无', self.run_script('check_constraints.py', self.fx / 'episode.md', '--constraints', c))

    def test_no_built_in_name_exemptions(self):
        c = self.fx / 'only-jo.md'
        c.write_text('## 人物\n- Jo\n', encoding='utf-8')
        out = self.run_script('check_constraints.py', self.fx / 'no-markers.md', '--constraints', c)
        self.assertIn("未登记的说话人：['THEO', 'RHETT']", out)


class StandardFormat(Base):
    """标准剧本格式的 Markdown：二级标题是场景标题，加粗全大写单独一行是角色名，下面紧跟台词。"""

    def test_elements_are_told_apart(self):
        scenes, meta = cd.parse(self.fx / 'standard.md')
        self.assertEqual(meta['body'], 'markers')
        self.assertEqual([sc['title'] for sc in scenes], ['INT. KITCHEN - NIGHT'])
        lines = scenes[0]['lines']
        self.assertEqual([(x['speaker'], x['text'], x['offscreen']) for x in lines], [
            ('DEV', "You kept the old sign.", False), ('MARA', 'Still works.', False), ('MARA', 'Told you.', True)])
        self.assertEqual(lines[2]['paren'], '(V.O.) (laughing)')
        action = [t for _, t in scenes[0]['action']]
        for kept in ('Pull back: two stools, one of them empty.', 'The note on the fridge reads: "BACK AT TEN."',
                     'SILENCE.', '**THE NEXT MORNING**', '### AT THE WINDOW'):
            self.assertIn(kept, action)  # 带冒号的动作、全大写的动作、片名卡、小标题都不是角色名
        self.assertNotIn('CUT TO:', action)  # 转场不算动作

    def test_action_cues(self):
        p = self.fx / 'long.md'
        long_para = ' '.join(['He crosses the room and sets the glass down on the far end of the bar.'] * 4)
        p.write_text(f'<!-- script-body:start -->\n## INT. BAR - NIGHT\n\n{long_para}\n\nMara 觉得他在躲她。\n\n' +
                     ''.join(f'**{n}**\nLine {k}.\n\n' for k, n in enumerate(['DEV', 'MARA'] * 4)) +
                     '<!-- script-body:end -->\n', encoding='utf-8')
        meta, rs = cd.report(p)
        act = rs[0]['action']
        self.assertEqual((act['paras'], act['max_lines'], act['long_paras'], act['dialogue_run']), (2, 5, [(4, 5)], 8))
        self.assertEqual([(m['line'], m['words']) for m in act['marks']], [(6, ['觉得'])])
        self.assertTrue(any(f.startswith('动作段偏长：行 4（约 5 行）') for f in rs[0]['flags']), rs[0]['flags'])
        self.assertTrue(any(f.startswith('连续 8 句对白中间没有动作段') for f in rs[0]['flags']), rs[0]['flags'])
        out = self.run_script('check_dialogue.py', p)
        self.assertIn('动作描写 2 段', out)
        self.assertIn('← 觉得', out)

    def test_inner_word_in_standard_fixture(self):
        meta, rs = cd.report(self.fx / 'standard.md')
        self.assertEqual([m['words'] for m in rs[0]['action']['marks']], [['realizes']])
        self.assertEqual(rs[0]['action']['dialogue_run'], 2)  # 小标题不算动作段：MARA → MARA (V.O.) 连着

    def test_no_action_cues_without_markers(self):
        meta, rs = cd.report(self.fx / 'no-markers.md')
        self.assertNotIn('action', rs[0])


class EpisodeFile(Base):
    """一集一个文件：每场开头一行场标记，一场可以有几个场景标题。"""

    def test_units_follow_scene_markers(self):
        scenes, meta = cd.parse(self.fx / 'episode.md')
        self.assertEqual([(sc['mark'], sc['title']) for sc in scenes], [
            ('S01 · THE BAR', 'INT. BAR - NIGHT'), ('S01 · THE BAR', 'EXT. STREET - CONTINUOUS'),
            ('S02 · THE MORNING AFTER', 'INT. KITCHEN - MORNING'), ('S10 · LATER', 'INT. BAR - NIGHT')])

    def test_totals_per_scene(self):
        meta, rs = cd.report(self.fx / 'episode.md', wps=4)
        self.assertEqual(cd.unit_totals(rs), [('S01 · THE BAR', 3, 8, 2.0), ('S02 · THE MORNING AFTER', 1, 1, 0.2),
                                              ('S10 · LATER', 1, 2, 0.5)])
        out = self.run_script('check_dialogue.py', self.fx / 'episode.md', '--wps', '4')
        self.assertIn('-- [S01 · THE BAR] EXT. STREET - CONTINUOUS', out)
        self.assertIn('S01 · THE BAR：台词 3 句 · 8 词 · 约 2 s', out)

    def test_marker_starts_a_scene_and_any_h2_is_a_heading(self):
        p = self.fx / 'zh-episode.md'
        p.write_text('# 测试 · 第一集\n\n<!-- script-body:start -->\n<!-- 场 01 · 厨房 -->\n## 内 · 厨房 · 夜\n\n妈妈停下手里的活，看着她。\n\n'
                     '**妈妈**\n嗯，你又回来这么晚……\n\n（沉默）\n\n<!-- 场 02 · 门口 -->\n\n**女儿**\n我走了。\n\n## 外 · 楼道 · 夜\n\n灯坏了。\n'
                     '<!-- script-body:end -->\n', encoding='utf-8')
        scenes, meta = cd.parse(p)
        self.assertEqual([(sc['mark'], sc['title']) for sc in scenes], [
            ('场 01 · 厨房', '内 · 厨房 · 夜'), ('场 02 · 门口', '场 02 · 门口'), ('场 02 · 门口', '外 · 楼道 · 夜')])
        self.assertEqual([x['speaker'] for sc in scenes for x in sc['lines']], ['妈妈', '女儿'])  # 场标记后面没跟标题，台词也归这一场
        cues = cd.performance_cues(scenes[0])
        self.assertEqual({k: cues[k] for k, _ in cd.PERF_KEYS}, {'stops': 1, 'beats': 1, 'looks': 1, 'fillers': 1, 'unfinished': 1})
        self.assertEqual(cd.mark_label('场 01 · 厨房'), cd.mark_label('s1'))
        out = self.run_script('render_screenplay.py', p, '--scene', 'S2')
        self.assertIn('我走了。', out)
        self.assertNotIn('回来这么晚', out)
        self.assertNotIn('格式提示', out)  # "内 / 外 · 地点 · 时间"是中文稿的标准写法
        brief = self.fx / 'zh-brief.md'
        brief.write_text('### 锁定的台词\n- 场 02 > 我走了。\n- S01 > 我走了。\n', encoding='utf-8')
        out = self.run_script('compare_drafts.py', p, '--brief', brief)
        self.assertIn('⚠ 锁定的台词少了 1 句（共 2 句）：', out)
        self.assertIn('- S01 > 我走了。', out)

    def test_word_lists_skip_known_lookalikes(self):
        p = self.fx / 'look.md'
        p.write_text('<!-- script-body:start -->\n## INT. BAR - NIGHT\n\nPause.\n\nHe checks his watch.\n\n**DEV**\nDo you know where it is?\n\n'
                     '**MARA**\nI mean, no.\n<!-- script-body:end -->\n', encoding='utf-8')
        cues = cd.performance_cues(cd.parse(p)[0][0])
        self.assertEqual({k: cues[k] for k, _ in cd.PERF_KEYS}, {'stops': 0, 'beats': 1, 'looks': 0, 'fillers': 1, 'unfinished': 0})

    def test_no_markers_no_totals(self):
        self.assertNotIn('按场合计', self.run_script('check_dialogue.py', self.fx / 'standard.md'))

    def test_episode_header_checked_once(self):
        c = self.fx / 'ep-cons.md'
        c.write_text('## 人物\n- Dev, Mara\n\n## 必填头部\n- 版本：\n- 承接：\n- 新事实（提案）：\n- 状态：\n', encoding='utf-8')
        out = self.run_script('check_constraints.py', self.fx / 'episode.md', '--constraints', c)
        self.assertIn('头部必填项：齐', out)
        self.assertIn('场「S02 · THE MORNING AFTER · INT. KITCHEN - MORNING」', out)
        self.assertNotIn('未登记的说话人', out)


class Render(Base):
    """render_screenplay.py：Fountain / Markdown 互转，标准版面的纯文本和标准页。"""

    def test_fountain_to_markdown(self):
        out = self.tmp / 'out.md'
        msg = self.run_script('render_screenplay.py', self.fx / 'sample.fountain', '--md', out)
        self.assertIn('场景标题 2 个 · 台词 3 段', msg)
        md = out.read_text(encoding='utf-8')
        for piece in ('# SAMPLE · Episode 1\n', 'Draft v0.1 · 2026-11-09\n', '<!-- script-body:start -->\n## INT. KITCHEN - NIGHT\n',
                      "**DEV**\nYou kept the old sign.\n", '### AT THE WINDOW\n', '**MARA (V.O.)**\n(laughing)\nTold you.\n',
                      '**THE NEXT MORNING**\n', '## KITCHEN, LATER\n', '**McAVOY**\nMorning.\n', 'FADE OUT.\n<!-- script-body:end -->'):
            self.assertIn(piece, md)
        scenes = scenes_of(out)  # 转出来的 Markdown，检查脚本读得出同样的台词，分场也和转换脚本一致
        self.assertEqual([sc['title'] for sc in scenes], ['INT. KITCHEN - NIGHT', 'KITCHEN, LATER'])
        self.assertEqual([(x['speaker'], x['offscreen']) for sc in scenes for x in sc['lines']],
                         [('DEV', False), ('MARA', True), ('McAVOY', False)])

    def test_round_trip_keeps_every_line(self):
        md, back = self.tmp / 'out.md', self.tmp / 'back.fountain'
        self.run_script('render_screenplay.py', self.fx / 'sample.fountain', '--md', md)
        self.run_script('render_screenplay.py', md, '--fountain', back)
        body = lambda p: p.read_text(encoding='utf-8').split('\n\n', 1)[1].strip()  # 标题页之后
        self.assertEqual(body(back), (self.fx / 'sample.fountain').read_text(encoding='utf-8').split('\n\n', 1)[1].strip())
        self.assertTrue(back.read_text(encoding='utf-8').startswith('Title: SAMPLE · Episode 1\n'))

    def test_text_layout_columns(self):
        out = self.run_script('render_screenplay.py', self.fx / 'standard.md').splitlines()
        self.assertIn('INT. KITCHEN - NIGHT', out)
        self.assertIn(' ' * 20 + 'DEV', out)
        self.assertIn(' ' * 20 + 'MARA (V.O.)', out)
        self.assertIn(' ' * 15 + '(laughing)', out)
        self.assertIn(' ' * 10 + "You kept the old sign.", out)
        self.assertIn(' ' * 10 + '你还留着旧招牌。', out)
        self.assertIn('AT THE WINDOW', out)
        self.assertIn(' ' * 53 + 'CUT TO:', out)  # 转场靠右，收在第 60 格
        self.assertIn(' ' * 22 + 'THE NEXT MORNING', out)  # 片名卡居中
        self.assertTrue(all(cd.display_width(l) <= 60 for l in out[:-1]), [l for l in out if cd.display_width(l) > 60])
        self.assertIn('对照翻译 2 行在内', out[-1])

    def test_wrap_counts_cjk_as_two_columns(self):
        import render_screenplay as rs
        self.assertEqual(rs.wrap('他把手机举高一点，咳了一声。' * 3, 35),
                         ['他把手机举高一点，咳了一声。他把手', '机举高一点，咳了一声。他把手机举高', '一点，咳了一声。'])
        self.assertEqual(rs.wrap('You changed the sign three weeks ago, I think.', 35), ['You changed the sign three weeks', 'ago, I think.'])

    def test_no_translation(self):
        out = self.run_script('render_screenplay.py', self.fx / 'standard.md', '--no-translation')
        self.assertNotIn('你还留着旧招牌。', out)
        self.assertIn('对照翻译 2 行已去掉', out)

    def test_html_page_spec(self):
        page = self.tmp / 'out.html'
        self.run_script('render_screenplay.py', self.fx / 'standard.md', '--html', page, '--title', 'SAMPLE')
        h = page.read_text(encoding='utf-8')
        for piece in ('<title>SAMPLE</title>', '12pt/12pt "Courier Prime", "Courier New", Courier',
                      '@page { size: 8.5in 11in; margin: 1in 1in 1in 1.5in; }', '<p class="character">MARA (V.O.)</p>',
                      '<p class="paren">(laughing)</p>', '<p class="alt">还能用。</p>', '<p class="scene">INT. KITCHEN - NIGHT</p>',
                      '<p class="transition">CUT TO:</p>', '<p class="center">THE NEXT MORNING</p>'):
            self.assertIn(piece, h)

    def test_scene_markers_survive_both_ways(self):
        md, ftn, back = self.tmp / 'out.md', self.tmp / 'out.fountain', self.tmp / 'back.md'
        self.run_script('render_screenplay.py', self.fx / 'episode.md', '--md', md, '--fountain', ftn)
        self.assertIn('<!-- S01 · THE BAR -->\n## INT. BAR - NIGHT\n', md.read_text(encoding='utf-8'))
        self.assertIn('# S02 · THE MORNING AFTER\n\nINT. KITCHEN - MORNING\n', ftn.read_text(encoding='utf-8'))
        self.run_script('render_screenplay.py', ftn, '--md', back)
        self.assertIn('<!-- S02 · THE MORNING AFTER -->\n## INT. KITCHEN - MORNING\n', back.read_text(encoding='utf-8'))
        self.assertNotIn('S01', '\n'.join(self.run_script('render_screenplay.py', self.fx / 'episode.md').splitlines()[:-1]))

    def test_take_one_scene(self):
        out = self.run_script('render_screenplay.py', self.fx / 'episode.md', '--scene', 'S7')
        self.assertIn('没有找到 S7。文件里的场：S01 · THE BAR、S02 · THE MORNING AFTER、S10 · LATER', out)
        out = self.run_script('render_screenplay.py', self.fx / 'episode.md', '--scene', 's1')  # s1、S01、场 1 是同一场，不是 S10
        self.assertIn('EXT. STREET - CONTINUOUS', out)  # 一场可以有几个场景标题
        self.assertNotIn('Morning.', out)
        self.assertNotIn('One more.', out)
        self.assertIn('场 1 个 · 场景标题 2 个 · 台词 3 段', out)
        self.assertIn('对照翻译 1 行在内', out)
        md = self.tmp / 's02.md'
        self.run_script('render_screenplay.py', self.fx / 'episode.md', '--scene', 'S02,S10', '--md', md)
        self.assertEqual([x['text'] for sc in scenes_of(md) for x in sc['lines']], ['Morning.', 'One more.'])

    def test_title_of_old_file_without_markers(self):
        p = self.fx / 'old.md'
        p.write_text("# OLD · 场 01\n\n场 01 · 内 · 酒吧 · 夜\n\n**DEV**\nHi.\n", encoding='utf-8')
        out = self.run_script('render_screenplay.py', p).splitlines()
        self.assertIn('OLD · 场 01', out[0])  # 标题取到了
        self.assertEqual(sum('OLD · 场 01' in l for l in out), 1)  # 没有再当成小标题排一遍

    def test_format_notes(self):
        out = self.run_script('render_screenplay.py', self.fx / 'body-annotations.md')
        self.assertIn('格式提示：场景标题不是「INT. / EXT. 地点 - 时间」或「内 / 外 · 地点 · 时间」的有 1 处', out)


class CompareDrafts(Base):
    """compare_drafts.py：两版剧本的结构有没有变（场、场景标题、每场的说话人），改了哪些句子。"""

    def variant(self, name, *swaps):
        text = (self.fx / 'episode.md').read_text(encoding='utf-8')
        for a, b in swaps:
            self.assertIn(a, text)
            text = text.replace(a, b)
        p = self.fx / name
        p.write_text(text, encoding='utf-8')
        return p

    def polished(self):
        return self.variant('polish.md', ("You kept the old sign.", "You kept the sign."), ('**DEV**\nNight.\n\n', ''),
                            ('Dev pours two coffees.', 'Dev pours two coffees and slides one across.'))

    def test_polish_leaves_structure_alone(self):
        import compare_drafts as cmp
        r = cmp.compare(self.fx / 'episode.md', self.polished(), wps=4)
        self.assertTrue(r['by_mark'])
        self.assertEqual(r['structure'], [])
        self.assertEqual([(x['scene'], x['kind'], x['what']) for x in r['items']],
                         [('S01', '改', 'line'), ('S01', '删', 'line'), ('S02', '改', 'para')])
        self.assertEqual((r['old_total'][0], r['new_total'][0]), (5, 4))
        self.assertEqual(r['scenes'][0]['seconds'], [2.0, 1.5])

    def test_report_gives_pasteable_change_list(self):
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', self.polished(), '--wps', '4')
        for piece in ('按场标记对齐（3 → 3 场）', '结构：场、场景标题、每场的说话人都没变。', '台词：5 → 4 句 · 改 1 · 删 1 · 加 0',
                      "- S01 改：> You kept the old sign. → > You kept the sign.", '- S01 删：> Night.（DEV）',
                      '- S02 改：> Dev pours two coffees. → > Dev pours two coffees and slides one across.'):
            self.assertIn(piece, out)

    def test_structure_changes_are_named(self):
        new = self.variant('rewrite.md', ('<!-- S02 · THE MORNING AFTER -->\n## INT. KITCHEN - MORNING\n\n**MARA**\nMorning.\n\nDev pours two coffees.\n\n', ''),
                           ('**DEV**\nOne more.', '**NIA**\nOne more.\n\n## EXT. ALLEY - NIGHT\n\nRain.'))
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new)
        for piece in ('结构变了', '少了场：S02 · THE MORNING AFTER', 'S10：场景标题 1 → 2（多了 EXT. ALLEY - NIGHT）',
                      'S10：说话人少了 DEV；多了 NIA'):
            self.assertIn(piece, out)

    def test_same_file_and_no_markers(self):
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', self.fx / 'episode.md')
        self.assertIn('两版的台词和动作一字未改。', out)
        out = self.run_script('compare_drafts.py', self.fx / 'standard.md', self.fx / 'standard.md')
        self.assertIn('没有场标记，按场景标题对齐（1 → 1 个）', out)

    def test_brief_locked_lines_and_declared_rewrite(self):
        new = self.variant('v3.md', ('Still works.', 'Still works fine.'),
                           ('**DEV**\nOne more.', '**NIA**\nOne more.\n\n## EXT. ALLEY - NIGHT\n\nRain.'))
        import compare_drafts as cmp
        r = cmp.compare(self.fx / 'episode.md', new, brief=self.fx / 'polish-brief.md')
        self.assertEqual(r['structure'], [])  # S10 登记了局部重写，结构变化不算越界
        self.assertEqual(len(r['declared']), 2)
        self.assertEqual(r['locked']['total'], 3)
        self.assertEqual([(x['scene'], x['text'], x['closest']) for x in r['locked']['missing']],
                         [('S01', 'Still works.', 'Still works fine.'), ('S10', 'One more round.', 'One more.')])
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new, '--brief', self.fx / 'polish-brief.md')
        for piece in ('结构：没登记的场，场、场景标题、每场的说话人都没变。', '登记了局部重写的场有结构变化（简报里写了，不算越界）：',
                      '⚠ 锁定的台词少了 2 句（共 3 句）：', '- S01 > Still works.（现在最接近的一句：Still works fine.）'):
            self.assertIn(piece, out)

    def test_brief_named_edits(self):
        import compare_drafts as cmp
        self.assertEqual(cmp.read_brief(self.fx / 'polish-brief.md')[1],
                         [('S01', 'Night.', 'Good night.'), ('S02', 'Morning.', 'Morning, you.')])
        new = self.variant('named.md', ('**DEV**\nNight.', '**DEV**\nGood night.'))
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new, '--brief', self.fx / 'polish-brief.md')
        self.assertIn('⚠ 指定改法有 1 处没改（共 2 处）：', out)
        self.assertIn('- S02 > Morning, you.（旧句还在：Morning.）', out)
        self.assertNotIn('S01 > Good night.（', out)

    def test_performance_cues_before_and_after(self):
        new = self.variant('perf.md', ('Dev pours two coffees.', 'Dev stops pouring. Beat.\n\nMara looks at him.'),
                           ('**MARA**\nMorning.', '**MARA**\n(beat)\nUm, morning—'))
        scenes, meta = cd.parse(new)
        cues = cd.performance_cues(scenes[2])
        self.assertEqual({k: cues[k] for k, _ in cd.PERF_KEYS}, {'stops': 1, 'beats': 2, 'looks': 1, 'fillers': 1, 'unfinished': 1})
        out = self.run_script('check_dialogue.py', new)
        self.assertIn('表演线索（只数不判）：停手 1 · 停顿 2 · 对视 1 · 填充词 1 · 没说完 1', out)
        self.assertIn('停手 行', out)
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new)
        self.assertIn('表演线索（只数不判）：停手 0 → 1 · 停顿 0 → 2 · 对视 0 → 1 · 填充词 0 → 1 · 没说完 0 → 1', out)

    def test_brief_alone_checks_locked_lines(self):
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', '--brief', self.fx / 'polish-brief.md')
        self.assertIn('== 核对锁定的台词和指定改法：episode.md ==', out)
        self.assertIn('⚠ 锁定的台词少了 1 句（共 3 句）：', out)  # 带引号写的 "Morning." 也认
        self.assertIn('- S10 > One more round.', out)
        self.assertIn('找不到精修简报', self.run_script('compare_drafts.py', self.fx / 'episode.md', '--brief', self.fx / 'nope.md'))

    def test_dialogue_only_for_language_versions(self):
        zh = self.variant('zh.md', ('The overhead light hums.', '头顶的灯嗡嗡响。'), ('Dev pours two coffees.', 'Dev 倒了两杯咖啡。'),
                          ('## EXT. STREET - CONTINUOUS', '## 外 · 街上 · 接上'))
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', zh, '--dialogue-only')
        for piece in ('只比对白', '结构：场、每场的说话人都没变。', '台词：5 → 5 句 · 改 0 · 删 0 · 加 0', '两版的台词一字未改。'):
            self.assertIn(piece, out)
        self.assertNotIn('动作：', out)

    def test_speaker_case_is_not_a_change(self):
        new = self.variant('case.md', ('**MARA**\nStill works.', '**Mara**\nStill works.'))
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new)
        self.assertIn('台词：5 → 5 句 · 改 0 · 删 0 · 加 0', out)
        self.assertNotIn('本版改动', out)

    def test_added_scene_and_reorder(self):
        text = (self.fx / 'episode.md').read_text(encoding='utf-8')
        s2 = text[text.index('<!-- S02'):text.index('<!-- S10')]
        s10 = text[text.index('<!-- S10'):text.index('<!-- script-body:end -->')]
        new = self.fx / 'moved.md'
        new.write_text(text.replace(s2 + s10, s10 + '\n' + s2 + '<!-- S11 · CODA -->\n## INT. BAR - DAWN\n\nEmpty.\n'), encoding='utf-8')
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new)
        self.assertIn('多了场：S11 · CODA', out)
        self.assertIn('场的顺序变了：S01 → S10 → S02', out)

    def test_brief_scene_numbers_and_strict_rewrite_rows(self):
        import compare_drafts as cmp
        brief = self.fx / 'b.md'
        brief.write_text('### 锁定的台词\n- s1 > Still works.\n- 场 02 > Morning.\n- S07 > Hello.\n\n### 指定改法\n'
                         '- S10 > One more. → Last one. (too flat)\n- S7 > A. → B.\n\n| 场 | 这一轮 | 保留 | 改 | 结果 |\n|---|---|---|---|---|\n'
                         '| S01 · THE BAR | 小改 | | 不做局部重写 | |\n| S02 · X | 基本不动 | | | 建议下一轮局部重写 |\n'
                         '| **S10** · LATER | 局部重写 | | | |\n', encoding='utf-8')
        locked, edits, rewrite = cmp.read_brief(brief)
        self.assertEqual(rewrite, {'10'})  # 只认第二栏正好写着"局部重写"的行
        self.assertEqual(edits, [('S10', 'One more.', 'Last one.'), ('S7', 'A.', 'B.')])  # 半角括号里的原因也去掉
        r = cmp.locked_only(self.fx / 'episode.md', brief)
        self.assertEqual([(x['scene'], x['no_scene']) for x in r['locked']['missing']], [('S07', True)])
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', '--brief', brief)
        self.assertIn('- S07 > Hello.（剧本里没有这一场的场标记）', out)
        self.assertIn('- S10 > Last one.（旧句还在：One more.）', out)
        done = self.variant('done.md', ('One more.', 'Last one.'))
        self.assertNotIn('S10 > Last one.', self.run_script('compare_drafts.py', done, '--brief', brief))
        gone = self.variant('gone.md', ('One more.', 'Again.'))
        self.assertIn('- S10 > Last one.（旧句也不在了，核对一下改成了什么）', self.run_script('compare_drafts.py', gone, '--brief', brief))

    def test_brief_all_clear_and_empty(self):
        brief = self.fx / 'ok.md'
        brief.write_text('### 锁定的台词\n- S01 > Still works.\n\n### 指定改法\n- S02 > Hi. → Morning.\n', encoding='utf-8')
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', '--brief', brief)
        self.assertIn('锁定的台词：1 句逐字都在。', out)
        self.assertIn('指定改法：1 处都改了。', out)
        empty = self.fx / 'empty.md'
        empty.write_text('# 精修简报\n', encoding='utf-8')
        self.assertIn('锁定的台词：简报里没有列', self.run_script('compare_drafts.py', self.fx / 'episode.md', '--brief', empty))

    def test_without_scene_markers_says_so(self):
        text = (self.fx / 'episode.md').read_text(encoding='utf-8')
        bare = self.fx / 'bare.md'
        bare.write_text('\n'.join(l for l in text.splitlines() if not l.startswith('<!-- S')) + '\n', encoding='utf-8')
        out = self.run_script('compare_drafts.py', bare, bare, '--brief', self.fx / 'polish-brief.md')
        self.assertIn('没有场标记，按场景标题对齐（4 → 4 个）', out)
        self.assertIn('认不出简报里登记了局部重写的场', out)
        self.assertIn('锁定的台词和指定改法在全文里找，不分场', out)
        part = self.variant('part.md', ('<!-- S01 · THE BAR -->\n', ''))
        self.assertIn('不是每个场景标题前都有场标记，按场景标题对齐', self.run_script('compare_drafts.py', part, part))
        out = self.run_script('compare_drafts.py', self.fx / 'no-markers.md', self.fx / 'no-markers.md')
        self.assertIn('有一版没有正文标记，按全文读', out)

    def test_json_output(self):
        import json
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', self.polished(), '--json', '--brief', self.fx / 'polish-brief.md')
        r = json.loads(out)
        self.assertEqual(r['marks'], 'all')
        self.assertEqual(r['structure'], [])
        self.assertEqual(r['performance']['new']['stops'], 0)
        self.assertEqual(r['locked']['total'], 3)

    def test_against_git_revision(self):
        if not shutil.which('git'):
            self.skipTest('没有 git')
        repo = self.tmp / 'repo'
        repo.mkdir()
        script = repo / 'ep.md'
        shutil.copy(self.fx / 'episode.md', script)
        git = ['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.com']
        for args in (['init', '-q'], ['add', 'ep.md'], ['commit', '-q', '-m', 'v0.1']):
            subprocess.run(git + args, check=True, capture_output=True)
        script.write_text(script.read_text(encoding='utf-8').replace('Still works.', 'Still works fine.'), encoding='utf-8')
        out = self.run_script('compare_drafts.py', script, '--rev', 'HEAD')
        self.assertIn('== 比稿：HEAD:ep.md → ep.md ==', out)
        self.assertIn('- S01 改：> Still works. → > Still works fine.', out)
        out = self.run_script('compare_drafts.py', script, '--rev', 'HEAD', '--brief', self.fx / 'polish-brief.md')  # 交付时的用法
        self.assertIn('⚠ 锁定的台词少了 2 句（共 3 句）：', out)
        self.assertIn('- S01 > Still works.（现在最接近的一句：Still works fine.）', out)
        self.assertIn('git 里没有 HEAD~5:ep.md', self.run_script('compare_drafts.py', script, '--rev', 'HEAD~5'))
        self.assertIn('不在 git 仓库里', self.run_script('compare_drafts.py', self.fx / 'episode.md', '--rev', 'HEAD'))


if __name__ == '__main__':
    unittest.main()
