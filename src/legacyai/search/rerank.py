"""Optional Claude pass over keyword search: read the request, then pick real moments.

Without an API key, or on any API failure, callers keep the keyword results.
"""
import json
import logging
import os

# Pinned on purpose. The API key does not select a model; this string does.
MODEL = "claude-haiku-4-5"
POOL = 30
PASSAGE_CHARS = 800
log = logging.getLogger("legacyai.search")
if not log.handlers:
    # Uvicorn leaves the root logger at WARNING; the model line must reach the host logs.
    log.addHandler(logging.StreamHandler())
    log.setLevel(logging.INFO)
    log.propagate = False

PLAN_SYSTEM = """You prepare keyword searches over transcripts of the podcast "{show}".
Transcripts are spoken conversation, so people are usually named the way friends say
them aloud (first name, last name alone, or nickname), not by full formal name.
Given a producer's request or a news headline, return search words.
- keywords: up to 8 single words or two-word phrases most likely to be spoken in a
  passage that is truly about the request. Put people first. No generic words.
- related: up to 10 nicknames, synonyms, or closely related words a speaker might use.
- angle: one sentence saying what a relevant moment would be about."""

PICK_SYSTEM = """You choose podcast moments for a producer working in the archive of "{show}".
You get a request and numbered transcript passages found by keyword search; many only
share a word with the request. Pick the passages that are genuinely about it, best first.
Prefer a passage that stands alone as a story, opinion, or exchange a viewer would follow
without more context. Leave out passing mentions, advertisements, and passages about a
different person or subject. Returning few or none is correct when few or none fit.
For each pick give a reason: one plain sentence, 14 words or fewer, saying what is
said in the passage. Do not praise it."""

PLAN_SCHEMA = {"type": "object", "additionalProperties": False,
               "required": ["keywords", "related", "angle"],
               "properties": {"keywords": {"type": "array", "items": {"type": "string"}},
                              "related": {"type": "array", "items": {"type": "string"}},
                              "angle": {"type": "string"}}}
PICK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["picks"],
               "properties": {"picks": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False, "required": ["n", "reason"],
                   "properties": {"n": {"type": "integer"}, "reason": {"type": "string"}}}}}}


def enabled():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def ask(system, content, schema, max_tokens):
    import anthropic
    client = anthropic.Anthropic(timeout=25.0, max_retries=1)
    try:
        response = client.messages.create(
            model=MODEL, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": schema}})
    except anthropic.APIError as exc:
        log.warning("Claude search step failed; using keyword results: %s", exc)
        return None
    log.info("search model=%s input=%s output=%s", response.model,
             response.usage.input_tokens, response.usage.output_tokens)
    if response.stop_reason != "end_turn":
        log.warning("Claude search step stopped early: %s", response.stop_reason)
        return None
    try:
        return json.loads(next(b.text for b in response.content if b.type == "text"))
    except (StopIteration, ValueError):
        return None


def plan(query, show):
    data = ask(PLAN_SYSTEM.format(show=show), query, PLAN_SCHEMA, 600)
    if not data:
        return None
    clean = lambda words, cap: list(dict.fromkeys(
        w.strip().lower() for w in words if isinstance(w, str) and 1 < len(w.strip()) <= 40))[:cap]
    return {"keywords": clean(data["keywords"], 8), "related": clean(data["related"], 10),
            "angle": data["angle"].strip()[:300]}


def pick(query, angle, show, candidates, limit):
    """Return the chosen candidates in order with Claude's reason, or None to keep keyword order."""
    if not candidates:
        return None
    listing = "\n\n".join(
        f"[{n}] {item['title']} ({item.get('published') or 'undated'})\n{item['text'][:PASSAGE_CHARS]}"
        for n, item in enumerate(candidates, 1))
    content = f"Request: {query}\n" + (f"Looking for: {angle}\n" if angle else "") + \
              f"Pick at most {limit}.\n\nPassages:\n\n{listing}"
    data = ask(PICK_SYSTEM.format(show=show), content, PICK_SCHEMA, 2000)
    if data is None:
        return None
    chosen, seen = [], set()
    for entry in data["picks"]:
        n = entry.get("n")
        if isinstance(n, int) and 1 <= n <= len(candidates) and n not in seen:
            seen.add(n)
            chosen.append({**candidates[n-1], "reason": entry["reason"].strip()[:200]})
    return chosen[:limit]
