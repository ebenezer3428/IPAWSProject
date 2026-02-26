from typing import TypedDict, Annotated, List, Dict
import operator
from langgraph.graph import StateGraph, END
from ipaws_research.models import EmergencyAlert, TranslatedAlert, AlertSegment, FairnessScore, CompositeScores, StatisticalResults
from ipaws_research.agents import (
    retrieve_alerts_agent,
    translation_agent,
    segmentation_agent,
    evaluation_agent,
    aggregation_agent,
    statistical_analysis_agent,
    report_generation_agent,
)

class ResearchState(TypedDict):
    sample_size: int
    target_languages: List[str]
    translation_systems: List[str]
    alerts: Annotated[List[EmergencyAlert], operator.add]
    translations: Annotated[List[TranslatedAlert], operator.add]
    segments: Annotated[List[AlertSegment], operator.add]
    scores: Annotated[List[FairnessScore], operator.add]
    composite_scores: Annotated[List[CompositeScores], operator.add]
    statistical_results: Annotated[List[StatisticalResults], operator.add]
    current_step: str
    errors: Annotated[List[str], operator.add]
    progress: Dict[str, int]

def create_research_workflow() -> StateGraph:
    workflow = StateGraph(ResearchState)
    workflow.add_node("retrieve_alerts", retrieve_alerts_agent)
    workflow.add_node("translate", translation_agent)
    workflow.add_node("segment", segmentation_agent)
    workflow.add_node("evaluate", evaluation_agent)
    workflow.add_node("aggregate", aggregation_agent)
    workflow.add_node("analyze", statistical_analysis_agent)
    workflow.add_node("report", report_generation_agent)

    workflow.set_entry_point("retrieve_alerts")
    workflow.add_edge("retrieve_alerts", "translate")
    workflow.add_edge("translate", "segment")
    workflow.add_edge("segment", "evaluate")
    workflow.add_edge("evaluate", "aggregate")
    workflow.add_edge("aggregate", "analyze")
    workflow.add_edge("analyze", "report")
    workflow.add_edge("report", END)

    return workflow.compile()
