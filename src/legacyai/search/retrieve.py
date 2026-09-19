"""BM25 plus explicit aliases; scores are ranking values, not confidence claims."""
import re

from .index import youtube_id

STOP = set("a an and are as at be because been being but by can could did do does for from get gets "
           "going had has have he her him his how i if in into is it its just like me more most my new news "
           "now of on or our out over really said says she should so some than that the their them then "
           "there these they this those to today trending trend us was we were what when where which who "
           "why will with would you your about after before find clip clips moment moments archive podcast".split())
GROUPS = [
    ["lebron", "bron", "king james"], ["curry", "steph", "stephen curry"],
    ["garnett", "kg", "big ticket"], ["durant", "kd", "kevin durant"],
    ["kaepernick", "kap", "colin"], ["jokic", "jokić", "joker"],
    ["retirement", "retire", "retired", "walked away", "last season"],
    ["leadership", "leader", "leading", "captain"],
    ["comeback", "recovery", "rehab", "injury", "injuries"],
    ["fatherhood", "parenting", "father", "daughter", "kids"],
    ["mental health", "depression", "anxiety", "therapy"],
    ["trade", "traded", "trading", "free agency"],
]


def terms_for(query):
    words = re.findall(r"[\w]+", query.lower())
    terms = list(dict.fromkeys(w for w in words if w not in STOP and len(w)>1))[:16]
    expanded = []
    normalized = query.lower()
    for group in GROUPS:
        if any(re.search(r"\b"+re.escape(term)+r"\b", normalized) for term in group):
            expanded.extend(term for term in group if term not in terms)
    return terms, list(dict.fromkeys(expanded))[:18]


def decorate(row):
    item = dict(row)
    item["youtube_id"] = youtube_id(item.get("source_url", ""))
    item["timing"] = "Approximate · paragraph boundaries"
    item["source_link"] = item.get("source_url", "")
    if item["youtube_id"]:
        item["source_link"] = f"https://www.youtube.com/watch?v={item['youtube_id']}&t={int(item.get('start',0))}s"
    return item


def search(con, workspace_id, query, limit=12, source_kind="", include_ads=False):
    terms, expanded = terms_for(query)
    if not terms:
        return {"results": [], "terms": [], "expanded_terms": [], "engine": "Keyword + aliases"}
    expression = " OR ".join('"'+t.replace('"', '""')+'"' for t in terms+expanded)
    params = [expression, workspace_id]
    where = ""
    if source_kind:
        where += " AND e.source_kind=?"
        params.append(source_kind)
    if not include_ads:
        where += " AND p.is_ad=0"
    rows = con.execute("""SELECT p.*,e.source_url,e.source_kind,e.published,e.duration,
        e.show_name,e.speaker_labels,bm25(passages_fts,1.0,0.15) AS rank
        FROM passages_fts JOIN passages p ON p.rowid=passages_fts.rowid
        JOIN episodes e ON e.id=p.episode_id AND e.workspace_id=p.workspace_id
        WHERE passages_fts MATCH ? AND p.workspace_id=?"""+where+" ORDER BY rank LIMIT 250", params).fetchall()
    candidates = []
    for row in rows:
        item = decorate(row)
        body = item["text"].lower()
        matches = [t for t in terms if re.search(r"\b"+re.escape(t)+r"\b", body)]
        aliases = [t for t in expanded if re.search(r"\b"+re.escape(t)+r"\b", body)]
        # Episode-title matches alone should not surface an unrelated passage.
        if not matches and not aliases:
            continue
        duration = item["end"]-item["start"]
        item["ranking_score"] = round(-item.pop("rank") + 2.5*len(matches) + .5*len(aliases)
                                      + (1 if 25<=duration<=100 else 0), 3)
        item["matched_terms"] = matches
        item["reason"] = "Mentions " + ", ".join(matches[:4] or aliases[:4])
        if aliases:
            item["reason"] += "; related wording: " + ", ".join(aliases[:3])
        candidates.append(item)
    candidates.sort(key=lambda x:x["ranking_score"], reverse=True)
    selected = []
    for item in candidates:
        overlap = any(old["episode_id"] == item["episode_id"] and
                      max(old["start"],item["start"]) < min(old["end"],item["end"])
                      for old in selected)
        if not overlap:
            selected.append(item)
        if len(selected)>=limit:
            break
    return {"results": selected, "terms": terms, "expanded_terms": expanded,
            "engine": "Keyword + aliases"}
