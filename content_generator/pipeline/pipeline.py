import json
from typing import TypedDict, Optional, Any
from langgraph.graph import StateGraph, START, END

from .pydantic_models import EvaluationResult, JudgeResult, PipelineOutput
from .agents.ingestion import ingest_client_data
from .agents.brand_analyzer import analyze_brand
from .agents.competitor_analyzer import analyze_competitors
from .agents.content_writer import build_content_brief, write_content
from .agents.content_classifier import classify_content
from .agents.geo_optimizer import optimize_for_geo
from .agents.localizer import localize_content
from .agents.evaluator import evaluate_loop, evaluate_competitor_edge
from .agents.grounding import check_and_clean, merge_reports
from .agents.content_writer import LONG_FORMATS
from .config import MAX_RETRIES


# ── Pipeline state ────────────────────────────────────────────

class PipelineState(TypedDict):
    # Inputs
    client_id: str
    goal: str
    content_format: str
    keywords: list
    scope_ids: Optional[list]
    previous_outputs: list
    client_documents: list
    competitor_documents: list
    target_languages: list
    tone_preset: str
    seo_params: dict
    # Intermediate
    content_type: Optional[dict]
    brand: Optional[Any]
    gap_map: Optional[Any]
    brief: Optional[Any]
    content_en: Optional[Any]
    feedback: Optional[str]
    loop_result: Optional[dict]
    attempt: int
    competitor_result: Optional[dict]
    # Output
    evaluation: Optional[Any]
    content_fi: Optional[Any]
    # Grounding: text the content may cite as fact, and the final check report
    sources: str
    fact_check: dict


# ── Helpers ───────────────────────────────────────────────────

def to_str(v) -> str:
    if isinstance(v, list):
        return " ".join(str(i) for i in v)
    return str(v) if v else ""


def content_to_text(content) -> str:
    parts = [to_str(content.title), to_str(content.headline)]
    for section in content.sections:
        parts.append(to_str(section.get("heading", "")))
        parts.append(to_str(section.get("body", "")))
    parts.append(to_str(content.cta))
    return "\n\n".join(parts)


# ── Nodes ─────────────────────────────────────────────────────

def _sources(state: PipelineState) -> str:
    """Everything the content may state as fact: the client's own material,
    the goal and the keywords. Competitor material is not a source for our claims."""
    from content_generator.models import KnowledgeChunk
    stored = KnowledgeChunk.objects.filter(client_id=state["client_id"]).values_list("text", flat=True)
    return "\n".join([*stored, *(state.get("client_documents") or []),
                      state.get("goal") or "", " ".join(state.get("keywords") or [])])


def node_ingest(state: PipelineState) -> dict:
    print("[Node 1] Ingesting client data...")
    ingest_client_data(state["client_id"], state["client_documents"])
    return {"sources": _sources(state)}


def node_classify(state: PipelineState) -> dict:
    print("[Node 2] Classifying content intent...")
    content_type = classify_content(state["goal"])
    print(f"  Intent: {content_type['primary_intent'].upper()} — {' → '.join(content_type['structure'])}")
    return {"content_type": content_type}


def node_brand(state: PipelineState) -> dict:
    print("[Node 3] Analyzing brand voice (LangChain RAG)...")
    brand = analyze_brand(state["client_id"], scope_ids=state.get("scope_ids"))
    print(f"  Brand tone: {brand.tone}")
    return {"brand": brand}


def node_competitors(state: PipelineState) -> dict:
    print("[Node 4] Analyzing competitor landscape...")
    brand = state["brand"]
    brand_context = f"{brand.tone} {brand.audience} — {', '.join(brand.differentiators[:2])}"
    gap_map = analyze_competitors(
        state["goal"],
        state["competitor_documents"],
        brand_context,
        state["content_type"]["primary_intent"],
    )
    print(f"  Competitors: {', '.join(gap_map.competitors[:3])}")
    print(f"  Gaps found: {len(gap_map.gaps)}")
    return {"gap_map": gap_map}


def node_brief(state: PipelineState) -> dict:
    print("[Node 5] Building content brief...")
    brief = build_content_brief(
        state["goal"], state["brand"], state["gap_map"],
        seo_params=state.get("seo_params") or {},
    )
    print(f"  Angle: {brief.angle}")
    return {"brief": brief}


def node_write(state: PipelineState) -> dict:
    attempt = state.get("attempt", 0) + 1
    print(f"[Node 6] Writing content (attempt {attempt}/{MAX_RETRIES}, LangChain RAG)...")
    content_en = write_content(
        client_id=state["client_id"],
        brief=state["brief"],
        brand=state["brand"],
        content_type=state["content_type"],
        language="English",
        feedback=state.get("feedback"),
        content_format=state["content_format"],
        scope_ids=state.get("scope_ids"),
        keywords=state.get("keywords"),
        previous_outputs=state.get("previous_outputs"),
        tone_preset=state.get("tone_preset", "professional"),
        seo_controls=state.get("seo_params") or {},
    )
    return {"content_en": content_en, "attempt": attempt}


def node_geo(state: PipelineState) -> dict:
    print("[Node 7] GEO optimization...")
    content_en = state["content_en"]
    # GEO restructuring (definition blocks, headings, paragraphs) is for web
    # pages; on a tagline, post, ad or email it added sections the format forbids.
    if state["content_format"] in LONG_FORMATS:
        content_en, _ = optimize_for_geo(content_en)
    # Replace unsupported figures before the judges see the text, so a
    # made-up number can never be what makes the content "pass".
    content_en, _ = check_and_clean(content_en, state.get("sources", ""))
    return {"content_en": content_en}


def node_evaluate(state: PipelineState) -> dict:
    print("[Node 8] Evaluating content (judges 1, 2, 4, 5)...")
    content_text = content_to_text(state["content_en"])
    loop_result = evaluate_loop(
        content_text=content_text,
        audience=state["brand"].audience,
        goal=state["goal"],
        content_piece=state["content_en"],
        seo_params=state.get("seo_params") or {},
        content_format=state["content_format"],
    )
    print(f"  Customer: {loop_result['customer']['score']} | GEO: {loop_result['geo']['score']} | Naturalness: {loop_result['naturalness']['score']} | Overall: {loop_result['overall_score']} | Passed: {loop_result['passed']}")

    feedback = None
    if not loop_result["passed"]:
        parts = [
            f"Customer feedback: {loop_result['customer']['feedback']}",
            f"GEO missing: {', '.join(loop_result['geo']['missing'])}",
            f"Naturalness feedback: {loop_result['naturalness']['feedback']}",
        ]
        if loop_result.get("structure_issues"):
            parts.append(f"Structure issues: {loop_result['structure_feedback']}")
        feedback = "\n".join(parts)
    return {"loop_result": loop_result, "feedback": feedback}


def should_retry(state: PipelineState) -> str:
    """Conditional edge: retry write if not passed and under attempt limit."""
    if not state["loop_result"]["passed"] and state["attempt"] < MAX_RETRIES:
        return "retry"
    return "done"


def node_competitor_judge(state: PipelineState) -> dict:
    print("[Node 9] Competitor edge judge (post-loop)...")
    competitor_result = evaluate_competitor_edge(
        content_text=content_to_text(state["content_en"]),
        competitor_data=state["competitor_documents"],
        gap_map_gaps=state["gap_map"].gaps,
    )
    return {"competitor_result": competitor_result}


def node_localize(state: PipelineState) -> dict:
    print("[Node 10] Localizing content...")
    localized = {"English": state["content_en"]}
    for lang in state["target_languages"]:
        if lang == "English":
            continue
        print(f"  Localizing to {lang}...")
        localized[lang] = localize_content(
            state["client_id"], state["content_en"], lang, state["brand"]
        )
    content_fi = localized.get("Finnish", state["content_en"])
    content_fi, _ = check_and_clean(content_fi, state.get("sources", ""))
    return {"content_fi": content_fi}


def node_finalize(state: PipelineState) -> dict:
    content_en, report_en = check_and_clean(state["content_en"], state.get("sources", ""))
    content_fi, report_fi = check_and_clean(state["content_fi"], state.get("sources", ""))
    loop_result = state["loop_result"]
    competitor_result = state["competitor_result"]

    overall_score = round((
        loop_result["customer"]["score"] +
        loop_result["geo"]["score"] +
        competitor_result["score"] +
        loop_result["naturalness"]["score"]
    ) / 4)

    evaluation = EvaluationResult(
        customer=JudgeResult(
            score=loop_result["customer"]["score"],
            feedback=loop_result["customer"]["feedback"],
            details={
                "pain_points_addressed": loop_result["customer"]["pain_points_addressed"],
                "clarity": loop_result["customer"]["clarity"],
                "value_proposition": loop_result["customer"]["value_proposition"],
            }
        ),
        geo=JudgeResult(
            score=loop_result["geo"]["score"],
            feedback=loop_result["geo"]["feedback"],
            details={
                "checks": loop_result["geo"]["checks"],
                "items": loop_result["geo"].get("items", []),
                "missing": loop_result["geo"]["missing"],
            }
        ),
        competitor=JudgeResult(
            score=competitor_result["score"],
            feedback=competitor_result["feedback"],
            details={
                "beats_on_specificity": competitor_result["beats_on_specificity"],
                "covers_gaps": competitor_result["covers_gaps"],
                "unique_angle": competitor_result["unique_angle"],
            }
        ),
        naturalness=JudgeResult(
            score=loop_result["naturalness"]["score"],
            feedback=loop_result["naturalness"]["feedback"],
            details={
                "sounds_human": loop_result["naturalness"]["sounds_human"],
                "ai_cliches_found": loop_result["naturalness"]["ai_cliches_found"],
                "ai_patterns": loop_result["naturalness"]["ai_patterns"],
            }
        ),
        overall_score=overall_score,
        passed=overall_score >= 70,
    )

    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE — Customer: {evaluation.customer.score} | GEO: {evaluation.geo.score} | Competitor: {evaluation.competitor.score} | Naturalness: {evaluation.naturalness.score} | Overall: {evaluation.overall_score}")
    print(f"{'='*60}\n")

    fact_check = merge_reports(report_en, report_fi)
    print(f"  Fact check: {fact_check['placeholders']} placeholder(s), "
          f"{len(fact_check['flagged'])} item(s) to review")
    return {"evaluation": evaluation, "content_en": content_en, "content_fi": content_fi,
            "fact_check": fact_check}


# ── Build graph ───────────────────────────────────────────────

def _build_graph():
    g = StateGraph(PipelineState)

    g.add_node("ingest",           node_ingest)
    g.add_node("classify",         node_classify)
    g.add_node("analyze_brand",    node_brand)   # node names must differ from state keys
    g.add_node("competitors",      node_competitors)
    g.add_node("build_brief",      node_brief)
    g.add_node("write",            node_write)
    g.add_node("geo",              node_geo)
    g.add_node("evaluate",         node_evaluate)
    g.add_node("competitor_judge", node_competitor_judge)
    g.add_node("localize",         node_localize)
    g.add_node("finalize",         node_finalize)

    g.add_edge(START,        "ingest")
    g.add_edge("ingest",     "classify")
    g.add_edge("classify",   "analyze_brand")
    g.add_edge("analyze_brand", "competitors")
    g.add_edge("competitors","build_brief")
    g.add_edge("build_brief", "write")
    g.add_edge("write",      "geo")
    g.add_edge("geo",        "evaluate")

    # Conditional retry loop
    g.add_conditional_edges(
        "evaluate",
        should_retry,
        {"retry": "write", "done": "competitor_judge"},
    )

    g.add_edge("competitor_judge", "localize")
    g.add_edge("localize",         "finalize")
    g.add_edge("finalize",         END)

    return g.compile()


_graph = _build_graph()


# ── Public API ────────────────────────────────────────────────

def run_pipeline(
    client_id: str,
    client_documents: list[str],
    competitor_documents: list[str],
    goal: str,
    target_languages: list[str] = None,
    content_format: str = "landing_page",
    scope_ids: list[str] = None,
    keywords: list[str] = None,
    previous_outputs: list[dict] = None,
    tone_preset: str = "professional",
    initial_feedback: str = None,
    seo_params: dict = None,
) -> PipelineOutput:
    if target_languages is None:
        target_languages = ["English"]

    print(f"\n{'='*60}")
    print(f"CASEVUAI — LangGraph Pipeline  |  Client: {client_id}")
    print(f"Goal: {goal}  |  Tone: {tone_preset}  |  Languages: {target_languages}")
    print(f"{'='*60}\n")

    initial_state: PipelineState = {
        "client_id": client_id,
        "goal": goal,
        "content_format": content_format,
        "keywords": keywords or [],
        "scope_ids": scope_ids,
        "previous_outputs": previous_outputs or [],
        "client_documents": client_documents,
        "competitor_documents": competitor_documents,
        "target_languages": target_languages,
        "tone_preset": tone_preset,
        "seo_params": seo_params or {},
        "content_type": None,
        "brand": None,
        "gap_map": None,
        "brief": None,
        "content_en": None,
        "feedback": initial_feedback or None,
        "loop_result": None,
        "attempt": 0,
        "competitor_result": None,
        "evaluation": None,
        "content_fi": None,
        "sources": "",
        "fact_check": {},
    }

    final_state = _graph.invoke(initial_state)

    return PipelineOutput(
        content_en=final_state["content_en"],
        content_fi=final_state["content_fi"],
        evaluation=final_state["evaluation"],
        content_type=final_state["content_type"],
        fact_check=final_state.get("fact_check") or {},
    )


def save_output(output: PipelineOutput, client_id: str):
    import os
    os.makedirs("output", exist_ok=True)
    for content in [output.content_en, output.content_fi]:
        lang = content.language.lower()[:2]
        path = f"output/{client_id}_{lang}.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# {content.title}\n\n## {content.headline}\n\n")
            for section in content.sections:
                f.write(f"### {section.get('heading', '')}\n\n{section.get('body', '')}\n\n")
            f.write(f"**{content.cta}**\n")
        print(f"Saved: {path}")
    with open(f"output/{client_id}_scores.json", "w") as f:
        json.dump(output.evaluation.model_dump(), f, indent=2)
