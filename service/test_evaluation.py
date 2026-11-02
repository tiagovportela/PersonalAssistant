"""Checks the evaluation kit: label files, matching them against what the layer
found, every section of the report, the leak check (including that it catches
a leak), and `pwi eval`. Uses a temporary home with real collected data.

Run: python3 -I service/test_evaluation.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="pwi-eval-"))
os.environ.update({"HOME": str(TMP), "XDG_DATA_HOME": str(TMP / "data"), "XDG_CONFIG_HOME": str(TMP / "config"),
                   "XDG_RUNTIME_DIR": str(TMP / "run"), "CLAUDE_CONFIG_DIR": str(TMP / "claude"),
                   "GIT_CONFIG_GLOBAL": str(TMP / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"})
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "contracts")]

import collect  # noqa: E402
import evaluation  # noqa: E402
import handlers  # noqa: E402
import paths  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402

D1, D2 = (date.today() - timedelta(days=3)).isoformat(), (date.today() - timedelta(days=2)).isoformat()


def check(label, condition):
    print(("ok   " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def sh(cwd, *args, **env):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, env={**os.environ, **env})


def commit(repo, subject, day):
    with open(repo / "a.txt", "a") as f:
        f.write(subject + "\n")
    sh(repo, "git", "add", "a.txt")
    stamp = f"{day}T10:00:00+00:00"
    sh(repo, "git", "commit", "-q", "-m", subject, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)


LABELS_D1 = """# Workday {day}

## Worked on
- alpha: retry queue for invoices
- beta: read the vendor contract
- gamma: something in a project that doesn't exist

## Decisions
- alpha: Failed invoices are retried three times before alerting finance
- alpha: We drop the legacy CSV export

## Commitments
- alpha: Send Ana the VAT rounding notes | due {due}
- alpha: Review Rui's pull request | due {due}
- alpha: Book the design review | due {due}

## Unfinished
- alpha: The retry dashboard is half done
"""

LABELS_D2 = """# Workday {day}

## Worked on
- Alpha service: rounding fix

## Blockers
- alpha: waiting for access to the archive bucket
"""


def main():
    os.umask(0o077)
    store.create_or_check(paths.STORE_PATH)
    repos = {n: TMP / "Projects" / n for n in ("alpha", "beta", "secret")}
    for repo in repos.values():
        repo.mkdir(parents=True)
        sh(repo, "git", "init", "-q", "-b", "main")
        sh(repo, "git", "config", "user.email", "me@example.com")
    commit(repos["alpha"], "Add invoice retry queue", D1)
    commit(repos["alpha"], "Fix VAT rounding", D2)
    commit(repos["beta"], "Unrelated beta change", D2)
    commit(repos["secret"], "Merger model", D1)
    (repos["alpha"] / "dashboard.py").write_text("half done")  # unfinished work, uncommitted
    db = store.connect(paths.STORE_PATH)
    sources.add_path(db, TMP / "Projects")
    collect.run(paths.STORE_PATH)
    db.execute("UPDATE projects SET name = 'Alpha service' WHERE id = 'alpha'")
    ids = {r["title"]: r["id"] for r in db.execute("SELECT id, title FROM events WHERE type = 'git.commit'")}
    layer = handlers.Layer(paths.STORE_PATH)

    def propose(kind, text, event, **extra):
        out = layer.call_tool("propose_claim", {"type": kind, "text": text, "evidence": [{"event_id": event}], **extra})
        return json.loads(out["content"][0]["text"].split("\n", 1)[1].rsplit("\n", 1)[0])["claim_id"]

    due = (date.today() + timedelta(days=4)).isoformat()
    retry = propose("decision", "Invoices that fail are retried 3 times, then finance is alerted", ids["Add invoice retry queue"],
                    about_day=D1)
    layer.call_tool("set_claim_status", {"claim_id": retry, "status": "supported"})
    propose("commitment", "Send Ana the notes on VAT rounding", ids["Fix VAT rounding"], due_at=due, about_day=D1)
    propose("commitment", "Review the pull request from Rui", ids["Fix VAT rounding"], due_at=D2, about_day=D1)
    false_one = propose("commitment", "Migrate billing to Kubernetes this quarter", ids["Add invoice retry queue"], about_day=D1)
    propose("decision", "The merger model uses a 9% discount rate", ids["Merger model"], about_day=D1)
    layer.call_tool("add_confidential_label", {"item": {"type": "project", "id": "secret"}})

    # labels and the CLI
    env = {**os.environ, "EDITOR": "true"}
    cli = [sys.executable, "-I", str(HERE / "cli.py")]
    none_yet = subprocess.run([*cli, "eval", "report"], env=env, capture_output=True, text=True)
    check("a report before any labels says how to start", none_yet.returncode == 1 and "pwi eval label" in none_yet.stderr)
    made = subprocess.run([*cli, "eval", "label", D1], env=env, capture_output=True, text=True)
    path = evaluation.label_path(D1)
    check("pwi eval label makes the day's file from the template, owner-only, outside the repository",
          made.returncode == 0 and path.exists() and path.stat().st_mode & 0o777 == 0o600
          and "## Decisions" in path.read_text() and "alpha, beta, secret" in path.read_text()
          and str(paths.DATA_DIR) in str(path))
    check("a blank template has no items", all(not items for items in evaluation.parse(path.read_text()).values()))
    path.write_text(LABELS_D1.format(day=D1, due=due))
    evaluation.label_path(D2).write_text(LABELS_D2.format(day=D2))
    parsed = evaluation.parse(path.read_text())
    check("labels are parsed by section, with project and due date",
          len(parsed["decision"]) == 2 and parsed["commitment"][0] == {"project": "alpha", "text": "Send Ana the VAT rounding notes",
                                                                      "due": due} and parsed["worked_on"][2]["project"] == "gamma")
    check("projects are recognised by id, by name, or by folder",
          evaluation.resolve(db, "alpha") == "alpha" and evaluation.resolve(db, "alpha service") == "alpha"
          and evaluation.resolve(db, "beta") == "beta" and evaluation.resolve(db, "gamma") is None)
    check("items match across different wording, accents and number words",
          evaluation.similar("Failed invoices are retried three times before alerting finance",
                             "Invoices that fail are retried 3 times, then finance is alerted")
          and evaluation.similar("Decisão sobre a exportação", "decisao de exportacao")
          and not evaluation.similar("We drop the legacy CSV export", "Invoices that fail are retried"))

    reported = subprocess.run([*cli, "eval", "report"], env=env, capture_output=True, text=True)
    out = evaluation.folder() / f"report-{D1}-to-{D2}.md"
    text = out.read_text()
    check("pwi eval report writes the report owner-only and prints the headline",
          reported.returncode == 0 and "Leaks: 0" in reported.stdout and out.stat().st_mode & 0o777 == 0o600
          and "gamma" in reported.stdout)

    # each section
    check("activity: labelled project-days found and missed, and recorded ones I didn't label",
          "You labelled 3 project-days of work; the layer recorded activity on 2 of them (67%)" in text
          and f"- {D1}, beta" in text and f"- {D2}, beta" in text)
    check("claims: a table of what I labelled against what Claude saved",
          "| Decision | 2 | 1 | 50% |" in text and "| Commitment | 3 | 2 | 67% |" in text
          and "| Blocker | 1 | 0 | 0% |" in text and "| Unfinished | 1 | 0 | 0% |" in text)
    check("missed items are listed, and unfinished work notes what the layer did see",
          "We drop the legacy CSV export" in text and "Book the design review" in text
          and "uncommitted changes" in text)
    check("claims that match no label are listed to judge, such as a false commitment",
          f"`{false_one}`" in text and "Migrate billing to Kubernetes" in text)
    check("deadlines: right date, wrong date, or missing",
          "Send Ana the VAT rounding notes (due " + due + "): right date" in text
          and f"Review Rui's pull request (due {due}): wrong date ({D2})" in text
          and f"Book the design review (due {due}): missing" in text)
    check("evidence and confirmation: citation coverage, confirmations, session notes",
          "Citation coverage: " in text and "1 confirmed" in text)
    check("collection health per source, with ingestion lag",
          "- alpha: " in text and "duplicates avoided" in text and "Ingestion lag for your commits" in text)
    check("no leaks: Claude's read tools never returned the confidential project",
          "Confidential or disabled items in their results: 0." in text)
    check("the checks only I can make are a tick list, one briefing per labelled day",
          f"- [ ] Daily briefing for {D1}" in text and f"- [ ] Daily briefing for {D2}" in text
          and "- [ ] End-of-day review listed every unconfirmed claim" in text)

    # the leak check catches a leak
    secret_event = ids["Merger model"]
    real = handlers.Layer.call_tool
    handlers.Layer.call_tool = lambda self, name, args: {"content": [{"type": "text", "text": f"... {secret_event} ..."}]}
    try:
        checked, leaks = evaluation.leak_check(paths.STORE_PATH, db, [D1, D2], {"alpha"}, ["retry"])
    finally:
        handlers.Layer.call_tool = real
    check("the leak check finds a confidential item in any tool's output",
          leaks and all(item == secret_event and why == "confidential event" for _, item, why in leaks) and checked > 5)
    db.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
