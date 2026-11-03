"""Automatic contradiction detection: pairs of claims that may disagree.

Rule-based and cautious. Two current claims are a candidate when they're about
the same project, mostly use the same words, and differ in a way that can be
checked:

- one is negated and the other isn't ("we will use Redis" / "we won't use Redis"),
- they use opposite words (keep/remove, enable/disable, manter/remover),
- one says something replaces something else and the other doesn't
  ("use Redis instead of SQLite", "em vez de"),
- they mention different numbers or dates,
- two commitments for the same work have different due dates or owners.

Nothing is marked or changed here. Candidates go to Claude (in propose_claim,
list_unconfirmed, get_project and get_week), and I decide in the review: a
contradiction (link_items contradicts, which marks both disputed), one replacing
the other (superseded), or no conflict (link_items related). Any link between
two claims means they've been looked at, so the pair isn't suggested again.
"""

import re
import unicodedata

STOPWORDS = {"that", "this", "with", "from", "have", "will", "were", "been", "they", "them", "then", "than", "when",
             "what", "which", "about", "into", "over", "para", "como", "mais", "pelo", "pela", "isto", "esta", "este",
             "foram", "sobre", "porque", "quando", "entre", "depois", "antes", "should", "would", "could"}
NEGATIONS = {"not", "no", "never", "dont", "don't", "doesnt", "doesn't", "didnt", "didn't", "wont", "won't", "isnt",
             "isn't", "arent", "aren't", "wasnt", "wasn't", "cannot", "cant", "can't", "shouldnt", "shouldn't",
             "without", "none", "nao", "nunca", "sem", "nenhum", "nenhuma", "jamais", "nem"}
OPPOSITES = [("use", "drop"), ("keep", "remove"), ("keep", "drop"), ("enable", "disable"), ("add", "remove"),
             ("approve", "reject"), ("accept", "reject"), ("include", "exclude"), ("allow", "block"), ("allow", "deny"),
             ("start", "stop"), ("increase", "decrease"), ("raise", "lower"), ("before", "after"), ("more", "less"),
             ("open", "close"), ("done", "pending"), ("finished", "pending"), ("merge", "revert"),
             ("usar", "abandonar"), ("manter", "remover"), ("aprovar", "rejeitar"), ("aceitar", "rejeitar"),
             ("incluir", "excluir"), ("ativar", "desativar"), ("adicionar", "remover"), ("aumentar", "diminuir"),
             ("antes", "depois"), ("mais", "menos"), ("abrir", "fechar"), ("concluido", "pendente")]
REPLACING = {"instead", "rather", "replace", "replaced", "replaces", "replacing", "switch", "switched", "migrate",
             "migrated", "substituir", "substitui", "substituido", "trocar", "trocamos", "vez"}
ENDINGS = ("ations", "ation", "ings", "ing", "ed", "es", "s", "amos", "emos", "ado", "ada", "ido", "ida", "ar", "er", "ir")
MIN_SHARED = 0.6  # share of the shorter claim's key words that the other also uses
TYPES = ("decision", "fact", "commitment", "blocker")
COMPARABLE = {("decision", "decision"), ("fact", "fact"), ("decision", "fact"), ("fact", "decision"),
              ("commitment", "commitment"), ("blocker", "blocker")}


def fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))


def words(text):
    return re.findall(r"[\w']+", fold(text))


def stem(word):
    word = word.replace("'", "")
    for ending in ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[:-len(ending)]
    return word


OPPOSITE_STEMS = [(stem(a), stem(b)) for a, b in OPPOSITES]


def key_terms(text):
    """The words that say what a claim is about: long enough, not stopwords, negations or opposites."""
    skip = NEGATIONS | REPLACING | {w for pair in OPPOSITES for w in pair}
    return {stem(w) for w in words(text) if len(w) >= 4 and w not in STOPWORDS and w not in skip}


def negated(text):
    return any(w in NEGATIONS or w.endswith("n't") for w in words(text))


def numbers(text):
    return set(re.findall(r"\d+(?:[.,:/-]\d+)*", fold(text)))


def shared(a, b):
    terms_a, terms_b = key_terms(a), key_terms(b)
    common = terms_a & terms_b
    shorter = min(len(terms_a), len(terms_b))
    return common, (len(common) / shorter if shorter else 0)


def reasons(a, b):
    """Why two similar claims might disagree; empty if nothing checkable differs."""
    why = []
    if negated(a["text"]) != negated(b["text"]):
        why.append("one is negated and the other isn't")
    stems_a, stems_b = {stem(w) for w in words(a["text"])}, {stem(w) for w in words(b["text"])}
    for x, y in OPPOSITE_STEMS:
        if (x in stems_a and y in stems_b and y not in stems_a) or (y in stems_a and x in stems_b and x not in stems_a):
            why.append(f"opposite words ({x}… / {y}…)")
            break
    if bool(REPLACING & set(words(a["text"]))) != bool(REPLACING & set(words(b["text"]))):
        why.append("one says something replaces something else")
    nums_a, nums_b = numbers(a["text"]), numbers(b["text"])
    if nums_a and nums_b and nums_a != nums_b:
        why.append(f"different numbers or dates ({', '.join(sorted(nums_a ^ nums_b)[:4])})")
    if a["type"] == b["type"] == "commitment":
        if a["due_at"] and b["due_at"] and a["due_at"][:10] != b["due_at"][:10]:
            why.append(f"different due dates ({a['due_at'][:10]} / {b['due_at'][:10]})")
        if a["owner"] and b["owner"] and fold(a["owner"]) != fold(b["owner"]):
            why.append(f"different owners ({a['owner']} / {b['owner']})")
    return why


def brief(c):
    item = {"claim_id": c["id"], "type": c["type"], "text": c["text"], "status": c["status"],
            "project": c["project_id"], "saved_at": c["version_at"]}
    for key in ("about_day", "due_at", "owner"):
        if c[key]:
            item[key] = c[key]
    return item


def linked_pairs(db):
    return {frozenset((r["from_id"], r["to_id"])) for r in db.execute(
        "SELECT from_id, to_id FROM links WHERE from_type = 'claim' AND to_type = 'claim'")}


def open_claims(db, project=None, any_project=True):
    sql = (f"SELECT * FROM claims_for_claude WHERE status IN ('proposed', 'supported', 'disputed')"
           f" AND type IN ({', '.join(repr(t) for t in TYPES)})")
    params = []
    if not any_project:
        sql += " AND project_id IS ?"
        params.append(project)
    return db.execute(sql + " ORDER BY version_at", params).fetchall()


def pair(a, b, linked):
    """A candidate for two claims, or None."""
    if a["id"] == b["id"] or a["project_id"] != b["project_id"] or (a["type"], b["type"]) not in COMPARABLE:
        return None
    if frozenset((a["id"], b["id"])) in linked:
        return None
    common, share = shared(a["text"], b["text"])
    if len(common) < 2 or share < MIN_SHARED:
        return None
    why = reasons(a, b)
    if not why:
        return None
    older, newer = sorted((a, b), key=lambda c: c["version_at"])
    return {"claims": [brief(older), brief(newer)], "why": why, "shared_words": round(share, 2)}


def candidates(db, project=None, limit=20):
    """Possible contradictions among current claims, the closest first. `project` limits it to one project."""
    claims = open_claims(db, project, any_project=project is None)
    linked = linked_pairs(db)
    found = []
    for i, a in enumerate(claims):
        for b in claims[i + 1:]:
            candidate = pair(a, b, linked)
            if candidate:
                found.append(candidate)
    found.sort(key=lambda c: -c["shared_words"])
    return found[:limit], len(found)


def for_claim(db, claim_id, limit=5):
    """Possible contradictions between one claim and the others, and claims that are merely similar."""
    claim = db.execute("SELECT * FROM claims_for_claude WHERE id = ?", (claim_id,)).fetchone()
    if claim is None or claim["type"] not in TYPES:
        return [], []
    linked = linked_pairs(db)
    conflicts, similar = [], []
    for other in open_claims(db, claim["project_id"], any_project=False):
        candidate = pair(claim, other, linked)
        if candidate:
            conflicts.append(candidate)
            continue
        if other["id"] != claim["id"] and (claim["type"], other["type"]) in COMPARABLE:
            common, share = shared(claim["text"], other["text"])
            if len(common) >= 2 and share >= MIN_SHARED:
                similar.append({**brief(other), "shared_words": round(share, 2)})
    conflicts.sort(key=lambda c: -c["shared_words"])
    similar.sort(key=lambda c: -c["shared_words"])
    return conflicts[:limit], similar[:limit]
