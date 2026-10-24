#!/usr/bin/env bash
# 回归测试：检查脚本对夹具的预期结果；SKILL.md 的名字与版本号；SKILL.md、README 和参考、模板里引用的文件都存在。
# 任何一项不符即失败。
set -u
cd "$(dirname "$0")/.."
fail=0
check() { # name, exit-status, detail
  if [ "$2" -eq 0 ]; then echo "PASS $1"; else echo "FAIL $1 — $3"; fail=1; fi
}

grep -q "^name: film-story" SKILL.md; check "SKILL.md invocation name preserved" $? ""
v=$(tr -d '[:space:]' < VERSION)
grep -q "version: \"$v\"" SKILL.md; check "SKILL.md version = VERSION ($v)" $? ""
grep -q "^## $v " CHANGELOG.md; check "CHANGELOG has $v" $? ""

missing=""
for f in $(grep -ohE '`(references|templates|scripts|validation|tests)/[^`* ]+`' SKILL.md README.md references/*.md templates/*.md | tr -d '`' | sort -u); do
  [ -e "$f" ] || missing="$missing $f"
done
[ -z "$missing" ]; check "referenced files exist" $? "$missing"

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
check "script regression suite" $? ""
exit $fail
