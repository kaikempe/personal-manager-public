#!/usr/bin/env python3
"""Keep the Obsidian vault in step with the sources it mirrors. One-way, idempotent, prints every change.

    python3 scripts/vault_sync.py --dry-run   # print what would change
    python3 scripts/vault_sync.py             # write the vault

projects  registry/*.md status + confirmed -> the vault project note that names it in `registry:`;
          the Projects index is regrouped by status (lines are kept, never rewritten).
courses   BB Tracker courses.json -> 02 University/Courses/<note>.md, matched by `bb_course_id`:
          credits, grading weights, term, status (from the term dates), the generated
          "## Structure (from BB Tracker, stable facts only)" section (sessions, assessment kinds by
          session number, syllabus readings by session, study packs in ~/Documents/BB Tracker/),
          and the course line in its year index. An enabled course with no note gets one from the
          course template. Never deadlines, grades, attendance or announcements: BB Tracker owns those.
hubs      every project, lesson or pattern that lists a tech hub in `stack` is linked from that hub.

Only the generated section, the listed frontmatter fields and Claude-written summaries
(`summary_by: claude`) are ever replaced. The user's own text is never touched.
"""
import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pm_env  # noqa: E402

VAULT = pm_env.VAULT
BB_COURSES = pm_env.BB_DATA.parent / "courses.json"
UNIVERSITY = pm_env.get("PM_UNIVERSITY")
STUDY_PACKS = Path.home() / "Documents/BB Tracker"
ONEDRIVE = pm_env.path("PM_ONEDRIVE", "~/Library/CloudStorage/OneDrive")   # course files synced from OneDrive
TODAY = datetime.date.today()
# PM_FIRST_YEAR: two-digit start year of your Year 1 (25 = the 2025-26 academic year); default: this academic year
FIRST_YEAR = int(pm_env.get("PM_FIRST_YEAR") or (TODAY.year % 100 - (TODAY.month < 8)))
UNI = pm_env.get("PM_UNIVERSITY_SHORT") or UNIVERSITY   # short name in note headings, e.g. "TUM"
STRUCTURE = "## Structure (from BB Tracker, stable facts only)"
STUB = "_No study notes yet. Add key concepts, formulas and what was graded here._"
STATUS_HEADINGS = [("active", "Active"), ("on-hold", "On-hold"), ("idea", "Idea"),
                   ("completed", "Completed"), ("archived", "Archived"), ("unknown", "Unknown")]
DRY = "--dry-run" in sys.argv
changes = []


# ---------- frontmatter helpers (line-based, so the rest of the note stays byte-identical) ----------

def split(text):
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    return text[4:end + 1], text[end + 5:]


def join(fm, body):
    return f"---\n{fm}---\n{body}"


def get(fm, key):
    m = re.search(rf"^{key}: *(.*)$", fm, re.M)
    return m.group(1).strip().strip('"') if m else None


def put(fm, key, value):
    """Set a scalar field; a list block under the key is replaced too. New keys go before `updated:`."""
    line = f"{key}: {value}\n" if not isinstance(value, list) else \
        f"{key}: \n" + "".join(f"  - {v}\n" for v in value)
    pat = re.compile(rf"^{key}:.*\n(?:  - .*\n)*", re.M)
    if pat.search(fm):
        return pat.sub(lambda _: line, fm, count=1)
    if re.search(r"^updated:", fm, re.M):
        return re.sub(r"^(updated:)", lambda m: line + m.group(1), fm, count=1, flags=re.M)
    return fm + line


def links(fm, key):
    m = re.search(rf"^{key}:.*\n((?:  - .*\n)*)", fm, re.M)
    return re.findall(r"\[\[([^\]|#]+)", m.group(1)) if m else []


def write(path, old, new, why):
    if old == new:
        return
    if new.startswith("---\n"):
        fm, body = split(new)
        new = join(put(fm, "updated", TODAY.isoformat()), body)
    changes.append(f"{path.relative_to(VAULT)}: {why}")
    if not DRY:
        path.write_text(new, encoding="utf-8")


# ---------- projects ----------

def sync_projects():
    for note in sorted((VAULT / "01 Projects").glob("*.md")):
        text = note.read_text(encoding="utf-8")
        fm, body = split(text)
        reg = get(fm, "registry")
        if not reg:
            continue
        rp = Path(reg.replace("~", str(Path.home()), 1))
        if not rp.exists():
            changes.append(f"{note.name}: registry file {reg} not found (not changed)")
            continue
        rfm, _ = split(rp.read_text(encoding="utf-8"))
        new = fm
        for key in ("status", "confirmed"):
            val = get(rfm, key)
            if val and get(fm, key) != val:
                new = put(new, key, val)
        write(note, text, join(new, body), f"status/confirmed from {rp.name}")
    regroup_index()


def regroup_index():
    p = VAULT / "01 Projects/Projects.md"
    text = p.read_text(encoding="utf-8")
    fm, body = split(text)
    status = {}
    for note in (VAULT / "01 Projects").glob("*.md"):
        nfm, _ = split(note.read_text(encoding="utf-8"))
        if get(nfm, "type") == "project":
            status[note.stem] = (get(nfm, "status") or "unknown", get(nfm, "summary") or "")
    head, tail, bullets, in_status = [], [], {}, False
    names = {h for _, h in STATUS_HEADINGS}
    for line in body.splitlines():
        h = re.match(r"^## (.+)$", line)
        if h:
            in_status = h.group(1) in names
            if not in_status:
                tail.append(line)
            continue
        b = re.match(r"^- \[\[([^\]|]+)", line)
        if in_status and b:
            bullets[b.group(1)] = line
        elif in_status and not line.strip():
            continue
        elif bullets or in_status or tail:
            tail.append(line)
        else:
            head.append(line)
    for name, (_, summary) in status.items():
        bullets.setdefault(name, f"- [[{name}]]: {summary}")
    out = "\n".join(head).rstrip() + "\n\n"
    for key, heading in STATUS_HEADINGS:
        group = sorted((n for n in bullets if status.get(n, ("unknown",))[0] == key), key=str.lower)
        if group:
            out += f"## {heading}\n" + "".join(bullets[n] + "\n" for n in group) + "\n"
    out += "\n".join(tail).strip() + "\n"
    out = re.sub(r"\(checked \d{4}-\d\d-\d\d\)", f"(checked {TODAY.isoformat()})", out)
    write(p, text, join(fm, out), "regrouped by status")


# ---------- courses ----------

def term_info(term):
    """'BBABCSAI 26-27 SECOND Q1' -> (year 2, semester 1, start, end). Q1 Sep-Dec, Q2 Jan-Jun, Annual Sep-Jun."""
    m = re.search(r"(\d\d)-(\d\d) .*?(Q1|Q2|Annual|Anual)", term or "")
    if not m:
        return None
    y0 = 2000 + int(m.group(1))
    q = m.group(3)
    sem = {"Q1": 1, "Q2": 2}.get(q, 0)
    start = datetime.date(y0, 9, 1) if sem in (0, 1) else datetime.date(y0 + 1, 1, 1)
    end = datetime.date(y0, 12, 31) if sem == 1 else datetime.date(y0 + 1, 6, 30)
    return int(m.group(1)) - FIRST_YEAR + 1, sem, start, end


def course_status(c, info):
    if c.get("closed") or TODAY > info[3]:
        return "completed"
    return "upcoming" if TODAY < info[2] else "active"


def pct(v):
    return f"{round(v * 100, 1):g}%"


def title_case(name):
    small = {"and", "of", "for", "to", "in", "the", "with", "a", "on"}
    name = re.sub(r"\s*-\s*DUAL$", "", name).replace("&", "and")
    words = name.lower().split()
    return " ".join(w if i and w in small else w[:1].upper() + w[1:] for i, w in enumerate(words))


def span(sessions):
    """['2','3','4','6'] -> 'S2–S4, S6' (ranges only where the numbers are contiguous)."""
    nums = [int(s) for s in sessions if str(s).isdigit()]
    if len(nums) != len(sessions):
        return ", ".join(f"S{s}" for s in sessions)
    parts, start = [], nums[0]
    for a, b in zip(nums, nums[1:] + [None]):
        if b != a + 1:
            parts.append(f"S{start}" if start == a else f"S{start}–S{a}")
            start = b
    return ", ".join(parts)


def structure(c, note_name):
    lines = ["<!-- written by personal-manager scripts/vault_sync.py from BB Tracker; edits here are overwritten -->"]
    facts = [f"Blackboard course `{c['course_id']}`", f"term `{c.get('term', '')}`"]
    if c.get("credits") is not None:
        facts.append(f"{c['credits']:g} ECTS")
    if c.get("total_sessions"):
        facts.append(f"{c['total_sessions']} sessions")
    lines.append("- " + ", ".join(facts))
    if c.get("grade_weights"):
        lines.append("- Grading: " + ", ".join(f"{k} {pct(v)}" for k, v in c["grade_weights"].items()))
    kinds = {}
    for e in c.get("exam_sessions") or []:
        kinds.setdefault(e.get("kind") or "assessment", []).append(e.get("session"))
    if kinds:
        parts = []
        for k, ss in kinds.items():
            nums = sorted(s for s in ss if s)
            where = f" in session{'s' if len(nums) > 1 else ''} {', '.join(map(str, nums))}" if nums else ""
            parts.append(f"{len(ss)} {k}{'s' if len(ss) > 1 else ''}{where}")
        lines.append("- Assessments (syllabus session numbers; dates: BB Tracker): " + "; ".join(parts))
    readings = c.get("session_readings") or {}
    if readings:
        lines.append("- Readings by session (syllabus):")
        runs = []  # [sessions, text]: consecutive sessions with the same readings share one line
        for s in sorted(readings, key=lambda x: int(x) if str(x).isdigit() else 999):
            items = []
            for r in readings[s]:
                t = re.sub(r"\s+", " ", r.get("title") or "").strip()[:140]
                verb = (r.get("verb") or "Read").lower()
                extra = [x for x in (verb if verb != "read" else "", "optional" if r.get("optional") else "") if x]
                items.append(t + (f" ({', '.join(extra)})" if extra else ""))
            text = "; ".join(items)
            if runs and runs[-1][1] == text:
                runs[-1][0].append(s)
            else:
                runs.append([[s], text])
        for sessions, text in runs:
            lines.append(f"  - {span(sessions)}: {text}")
    pack = STUDY_PACKS / note_name
    if pack.is_dir():
        docs = sorted(f.name for f in pack.iterdir() if f.suffix in (".docx", ".pdf", ".md"))
        if docs:
            lines.append(f"- Study pack (BB Tracker prototype) in `~/Documents/BB Tracker/{note_name}/`: " + ", ".join(docs))
    return "\n".join(lines) + "\n"


def replace_section(body, heading, content):
    """Replace the body of `heading` up to the next '## ' heading or '---' rule; add it before '## Notes' if missing."""
    lines = body.split("\n")
    if heading in lines:
        i = lines.index(heading) + 1
        j = i
        while j < len(lines) and not lines[j].startswith("## ") and lines[j].strip() != "---":
            j += 1
        return "\n".join(lines[:i] + content.rstrip("\n").split("\n") + [""] + lines[j:])
    anchor = "## Notes"
    if anchor in lines:
        k = lines.index(anchor)
        return "\n".join(lines[:k] + [heading] + content.rstrip("\n").split("\n") + [""] + lines[k:])
    return body.rstrip("\n") + f"\n\n{heading}\n{content}"


def course_summary(fm, body, c):
    y, s, st = get(fm, "year"), get(fm, "semester"), get(fm, "status")
    sem = "year-long" if s in ("0", "", None) else f"semester {s}"
    cr = get(fm, "credits")
    ects = f", {float(cr):g} ECTS" if cr and float(cr) else ""
    head = f"{UNI + ' course' if UNI else 'Course'}, Year {y}, {sem}{ects}, {st}"
    old = get(fm, "summary") or ""
    if "Study notes:" in old:
        return f"{head}. {old[old.index('Study notes:'):]}"
    grading = ("; grading " + ", ".join(f"{k} {pct(v)}" for k, v in c["grade_weights"].items())) if c.get("grade_weights") else ""
    has = "syllabus readings by session" if c.get("session_readings") else "metadata only"
    own = "no study notes yet" if STUB in body else "has study notes"
    return f"{head}{grading}. {has[0].upper() + has[1:]}; {own}."


def sync_courses():
    try:
        bb = json.loads(BB_COURSES.read_text())
    except (OSError, ValueError) as e:
        changes.append(f"courses skipped: cannot read {BB_COURSES}: {e}")
        return
    by_id = {}
    for f in (VAULT / "02 University/Courses").glob("*.md"):
        cid = get(split(f.read_text(encoding="utf-8"))[0], "bb_course_id")
        if cid:
            by_id[cid] = f
    for c in bb:
        info = term_info(c.get("term"))
        if not info:
            continue
        note = by_id.get(c["course_id"])
        if not note:
            if not c.get("enabled"):
                continue  # disabled duplicate records (e.g. a second Español id) never get a note
            note = new_course(c, info)
            if not note:
                continue
        text = note.read_text(encoding="utf-8")
        fm, body = split(text)
        new = put(fm, "status", course_status(c, info))
        new = put(new, "bb_term", c["term"])
        if c.get("credits") is not None:
            new = put(new, "credits", f"{float(c['credits']):.1f}")
        if c.get("grade_weights"):
            new = put(new, "grade_weights", [f"{k} {pct(v)}" for k, v in c["grade_weights"].items()])
        body2 = replace_section(body, STRUCTURE, structure(c, note.stem))
        if get(new, "summary_by") == "claude":
            new = put(new, "summary", '"' + course_summary(new, body2, c).replace('"', "'") + '"')
        write(note, text, join(new, body2), "BB Tracker facts")
    sync_year_indexes()


def new_course(c, info):
    year, sem = info[0], info[1]
    name = title_case(c["name"])
    path = VAULT / "02 University/Courses" / f"{name}.md"
    if path.exists():
        changes.append(f"new course {c['name']} ({c['course_id']}): {path.name} exists without this id; not changed, ask the user")
        return None
    semdir = {1: "1st Semester", 2: "2nd Semester"}.get(sem, "")
    src = ONEDRIVE / f"Year {year}" / semdir / name
    sem_txt = f"semester {sem}" if sem else "year-long"
    text = (f"---\ntype: course\nsummary: \"\"\nsummary_by: claude\nuniversity: {UNIVERSITY}\nyear: {year}\n"
            f"semester: {sem}\nstatus: {course_status(c, info)}\nbb_course_id: {c['course_id']}\nbb_term: {c['term']}\n"
            f"source: {'~/' + str(src.relative_to(Path.home())) if src.is_dir() else ''}\nrelated: []\n"
            f"updated: {TODAY.isoformat()}\n---\n\n# {name}\n\n"
            f"{UNIVERSITY + ', ' if UNIVERSITY else ''}Year {year}, {sem_txt}. Deadlines and scores live in BB Tracker, not here.\n\n"
            f"Up: [[Year {year}]] · [[University]]\n\n## Notes\n{STUB}\n")
    changes.append(f"02 University/Courses/{path.name}: new course note")
    if DRY:
        return None
    path.write_text(text, encoding="utf-8")
    return path


def sync_year_indexes():
    notes = {}
    for f in (VAULT / "02 University/Courses").glob("*.md"):
        t = f.read_text(encoding="utf-8")
        fm, body = split(t)
        notes[f.stem] = (get(fm, "year"), get(fm, "semester"), get(fm, "status"), get(fm, "credits"), STUB not in body)
    years = sorted({n[0] for n in notes.values() if n[0] and n[0].isdigit()}, key=int)
    for y in years:
        p = VAULT / f"02 University/Year {y}.md"
        if not p.exists():
            create_year(p, y)
            if DRY:
                continue
        text = p.read_text(encoding="utf-8")
        fm, body = split(text)

        def line(name):
            _, _, st, cr, own = notes[name]
            ects = f", {float(cr):g} ECTS" if cr and float(cr) else ""
            return f"- [[{name}]]: {st}{ects}, {'study notes' if own else 'no study notes yet'}"
        body = re.sub(r"^- \[\[([^\]|]+)\]\](:.*)?$", lambda m: line(m.group(1)) if m.group(1) in notes else m.group(0), body, flags=re.M)
        body = re.sub(r"^(## Semester \d) \((current|upcoming)\)$", r"\1", body, flags=re.M)
        for name, (ny, ns, *_rest) in sorted(notes.items()):
            if ny == y and f"[[{name}]]" not in body:
                heading = "## Year-long" if ns in ("0", None, "") else f"## Semester {ns}"
                if heading not in body.split("\n"):
                    body = body.rstrip("\n") + f"\n\n{heading}\n"
                lines = body.split("\n")
                i = lines.index(heading) + 1
                while i < len(lines) and lines[i].startswith("- "):
                    i += 1
                lines.insert(i, line(name))
                body = "\n".join(lines)
        write(p, text, join(fm, body), "course lines")


def create_year(p, y):
    text = (f"---\ntype: moc\nsummary: \"{UNI + ' ' if UNI else ''}Year {y}: courses with status, ECTS and whether they have study notes.\"\n"
            f"summary_by: claude\nyear: {y}\nupdated: {TODAY.isoformat()}\n---\n\n# Year {y}\n\n"
            f"Course lines are kept by `vault_sync.py` from BB Tracker. Deadlines: [[BB Tracker]].\n\n"
            f"## Semester 1\n\n## Semester 2\n\n## Year-long\n\nUp: [[University]]\n")
    changes.append(f"02 University/{p.name}: new year index (link it from University)")
    if not DRY:
        p.write_text(text, encoding="utf-8")
        u = VAULT / "02 University/University.md"
        ut = u.read_text(encoding="utf-8")
        if f"[[Year {y}]]" not in ut:
            write(u, ut, ut.replace(f"- [[Year {int(y) - 1}]]", f"- [[Year {y}]]\n- [[Year {int(y) - 1}]]", 1), f"links Year {y}")


# ---------- tech hubs ----------

HUB_SECTIONS = ("## Projects using it", "## Lessons", "## Patterns")
HUB_FOOTER = ("_Links come from each note's `stack` (added by the personal manager's `vault_sync.py`, never removed); "
              "the text after a link is that note's `summary`._")


def sync_hubs():
    want, summaries = {}, {}
    for folder, section in zip(("01 Projects", "03 Knowledge/Lessons", "03 Knowledge/Patterns"), HUB_SECTIONS):
        for f in (VAULT / folder).glob("*.md"):
            fm = split(f.read_text(encoding="utf-8"))[0]
            summaries[f.stem] = get(fm, "summary") or ""
            for hub in links(fm, "stack"):
                want.setdefault(hub, []).append((section, f.stem))
    for p in sorted((VAULT / "03 Knowledge/Tech").glob("*.md")):
        if p.stem in want or get(split(p.read_text(encoding="utf-8"))[0], "type") == "tech":
            want.setdefault(p.stem, [])
    for hub, items in sorted(want.items()):
        p = VAULT / "03 Knowledge/Tech" / f"{hub}.md"
        if not p.exists():
            changes.append(f"tech hub [[{hub}]] is listed in a stack but has no note (not created)")
            continue
        text = p.read_text(encoding="utf-8")
        if get(split(text)[0], "type") != "tech":
            continue
        lines = text.split("\n")
        for section, name in sorted(items):
            if f"[[{name}]]" in "\n".join(lines) or f"[[{name}|" in "\n".join(lines):
                continue
            if section not in lines:
                k = next((i for i, l in enumerate(lines) if l.startswith("_Lists are maintained")), len(lines))
                lines[k:k] = [section, "", ""]
            i = lines.index(section) + 1
            while i < len(lines) and lines[i].startswith("- "):
                i += 1
            lines.insert(i, f"- [[{name}]]")
            lines = [l for j, l in enumerate(lines) if not (l == "- none yet" and j > lines.index(section) and j <= i + 1)]
        section = None
        for j, l in enumerate(lines):
            if l.startswith("## "):
                section = l if l in HUB_SECTIONS else None
            m = re.match(r"^- \[\[([^\]|]+)\]\]", l)
            if section and m and summaries.get(m.group(1)):
                lines[j] = f"- [[{m.group(1)}]]: {summaries[m.group(1)]}"
            elif l.startswith("_Lists are maintained"):
                lines[j] = HUB_FOOTER
        write(p, text, "\n".join(lines), "hub links and summaries")


if __name__ == "__main__":
    if not VAULT.is_dir():
        sys.exit(f"vault not found: {VAULT}")
    sync_projects()
    sync_courses()
    sync_hubs()
    print(("would change" if DRY else "changed") + f": {len(changes)}")
    for c in changes:
        print(f"  {c}")
