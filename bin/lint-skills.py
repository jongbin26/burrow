#!/usr/bin/env python3
"""스킬 정적 점검. 모델 호출 없이 frontmatter·상호 참조·dev-core 형식을 본다. 문제가 있으면 exit 1."""
import os
import re
import sys
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_CONFIG_REPO") or Path(__file__).resolve().parent.parent)
SKILL_DIRS = [REPO / "src" / "skills", REPO / "src" / "dev-core", REPO / "src" / "dev-stack"]
DEV_CORE = REPO / "src" / "dev-core"
DEV_STACK = REPO / "src" / "dev-stack"

DESCRIPTION_MAX = 1024  # Agent Skills 스펙의 description 상한
MAX_PRINCIPLES = 7
MAX_QUESTIONS = 2
MAX_EXAMPLE_LINES = 3
# dev-core 는 기술에 묶이지 않음. 기술 이름이 보이면 dev-stack 으로 갈 내용
TECH_WORDS = re.compile(r"\b(?:React|RxJS|Next\.?js|TypeScript|Effect\.\w+|zod|use[A-Z]\w+|vitest|jest|vi\.\w+)\b")
KEBAB = re.compile(r"(?<![/\w-])[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?![/\w-])")  # 경로 조각 제외

problems = []


def report(path, msg):
    problems.append(f"{path.relative_to(REPO)}: {msg}")


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    fields = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fields[k.strip()] = v.strip()
    return fields


def check_principles(path, body):
    sections = re.split(r"\n(?=## )", body)
    principles = [s for s in sections if re.match(r"## \d+\.", s)]
    if len(principles) > MAX_PRINCIPLES:
        report(path, f"원칙 {len(principles)}개 (최대 {MAX_PRINCIPLES})")
    for s in principles:
        title = s.splitlines()[0]
        q = [l for l in s.splitlines() if l.startswith("판정 질문:")]
        if len(q) != 1:
            report(path, f"'{title}' 판정 질문 줄이 {len(q)}개")
        elif q[0].count("?") > MAX_QUESTIONS:
            report(path, f"'{title}' 판정 질문 {q[0].count('?')}개 (최대 {MAX_QUESTIONS})")
        ex = [l for l in s.splitlines() if l.startswith(">")]
        if len(ex) > MAX_EXAMPLE_LINES:
            report(path, f"'{title}' 예시 {len(ex)}줄 (최대 {MAX_EXAMPLE_LINES})")
    if "## 위반 신호" not in body:
        report(path, "'## 위반 신호' 절 없음")


def check_stack_links(path, body, core_names):
    for s in re.split(r"\n(?=## )", body):
        if not re.match(r"## \d+\.", s):
            continue
        title = s.splitlines()[0]
        link = next((l for l in s.splitlines() if l.startswith("원칙:")), None)
        if link is None:
            report(path, f"'{title}' 에 dev-core 를 가리키는 '원칙:' 줄 없음")
            continue
        names = re.findall(r"([a-z][a-z-]+) \d+", link)
        unknown = [n for n in names if n not in core_names]
        if not names or unknown:
            report(path, f"'{title}' 원칙 링크가 dev-core 스킬을 가리키지 않음: {link}")


def main():
    skills = {}
    for d in SKILL_DIRS:
        for child in sorted(p for p in d.iterdir() if p.is_dir()):
            f = child / "SKILL.md"
            if not f.is_file():
                report(child, "SKILL.md 없음")
                continue
            if child.name in skills:
                report(child, f"이름 중복: {skills[child.name].relative_to(REPO)}")
            skills[child.name] = f

    for name, f in skills.items():
        text = f.read_text()
        fm = frontmatter(text)
        if fm is None:
            report(f, "frontmatter 없음")
            continue
        if fm.get("name") != name:
            report(f, f"name '{fm.get('name')}' 이 디렉토리명 '{name}' 과 다름")
        desc = fm.get("description", "")
        if not desc:
            report(f, "description 없음")
        elif len(desc) > DESCRIPTION_MAX:
            report(f, f"description {len(desc)}자 (최대 {DESCRIPTION_MAX})")
        if "disable-model-invocation" in fm and f.is_relative_to(DEV_CORE):
            report(f, "dev-core 스킬은 자동 호출돼야 함 (disable-model-invocation 제거)")
        # description 의 kebab-case 단어는 다른 스킬 참조로 본다
        for ref in set(KEBAB.findall(desc)) - set(skills):
            report(f, f"description 이 없는 스킬 '{ref}' 을 참조")
        if f.is_relative_to(DEV_CORE) and "판정 질문:" in text:
            check_principles(f, text)
        if f.is_relative_to(DEV_CORE):
            for word in sorted(set(TECH_WORDS.findall(text))):
                report(f, f"dev-core 에 기술 이름 '{word}' (dev-stack 으로)")
        if f.is_relative_to(DEV_STACK):
            check_principles(f, text)
            check_stack_links(f, text, {n for n, p in skills.items() if p.is_relative_to(DEV_CORE)})

    for p in problems:
        print(p)
    print(f"{len(skills)}개 스킬 점검, 문제 {len(problems)}건")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
