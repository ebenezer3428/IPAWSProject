from typing import Dict, List
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multicomp import pairwise_tukeyhsd
from ipaws_research.utils import logger

def _check_normality(df: pd.DataFrame, value_col: str, group_col: str) -> bool:
    ok = True
    for g, sub in df.groupby(group_col):
        if len(sub) < 3:
            continue
        stat, p = stats.shapiro(sub[value_col])
        if p < 0.05:
            ok = False
    return ok

def _levene(df: pd.DataFrame, value_col: str, group_col: str) -> bool:
    groups = [g[value_col].values for _, g in df.groupby(group_col)]
    stat, p = stats.levene(*groups)
    return p >= 0.05

def _eta_squared(df: pd.DataFrame, value_col: str, group_col: str) -> float:
    # Compute sums of squares
    overall_mean = df[value_col].mean()
    ss_total = ((df[value_col] - overall_mean) ** 2).sum()
    ss_between = sum([
        len(g) * (g[value_col].mean() - overall_mean) ** 2
        for _, g in df.groupby(group_col)
    ])
    eta2 = ss_between / ss_total if ss_total > 0 else 0.0
    return float(eta2)

def test_hypothesis_h1(composite_scores: pd.DataFrame) -> Dict[str, object]:
    """H1: Mean Procedural Fairness Index differs across AI systems."""
    df = composite_scores.copy()
    df = df.dropna(subset=["pfi","system"])  # ensure
    normal = _check_normality(df, "pfi", "system")
    homogeneity = _levene(df, "pfi", "system")

    result = {"test": "one_way_anova", "groups_compared": ["gpt4o","google_nmt","nllb200"]}

    if normal and homogeneity:
        groups = [g["pfi"].values for _, g in df.groupby("system")]
        stat, p = stats.f_oneway(*groups)
        effect = _eta_squared(df, "pfi", "system")
        result.update({"statistic": float(stat), "p_value": float(p), "effect_size": effect})
        if p < 0.05:
            # Post-hoc Tukey
            tukey = pairwise_tukeyhsd(endog=df["pfi"], groups=df["system"], alpha=0.05)
            result["details"] = {"tukey_summary": str(tukey)}
        result["interpretation"] = (
            "Significant differences across systems" if p < 0.05 else "No significant difference across systems"
        )
    else:
        stat, p = stats.kruskal(*[g["pfi"].values for _, g in df.groupby("system")])
        result.update({"test": "kruskal_wallis", "statistic": float(stat), "p_value": float(p), "effect_size": None})
        result["interpretation"] = (
            "Significant differences across systems (non-parametric)" if p < 0.05 else "No significant difference"
        )
    return result

def test_hypothesis_h2(composite_scores: pd.DataFrame) -> Dict[str, object]:
    """H2: Mean Interactional Fairness Index differs across AI systems."""
    df = composite_scores.copy()
    df = df.dropna(subset=["ifi","system"])  # ensure
    normal = _check_normality(df, "ifi", "system")
    homogeneity = _levene(df, "ifi", "system")

    result = {"test": "one_way_anova", "groups_compared": ["gpt4o","google_nmt","nllb200"]}

    if normal and homogeneity:
        groups = [g["ifi"].values for _, g in df.groupby("system")]
        stat, p = stats.f_oneway(*groups)
        effect = _eta_squared(df, "ifi", "system")
        result.update({"statistic": float(stat), "p_value": float(p), "effect_size": effect})
        if p < 0.05:
            tukey = pairwise_tukeyhsd(endog=df["ifi"], groups=df["system"], alpha=0.05)
            result["details"] = {"tukey_summary": str(tukey)}
        result["interpretation"] = (
            "Significant differences across systems" if p < 0.05 else "No significant difference across systems"
        )
    else:
        stat, p = stats.kruskal(*[g["ifi"].values for _, g in df.groupby("system")])
        result.update({"test": "kruskal_wallis", "statistic": float(stat), "p_value": float(p), "effect_size": None})
        result["interpretation"] = (
            "Significant differences across systems (non-parametric)" if p < 0.05 else "No significant difference"
        )
    return result

def test_hypothesis_h3(composite_scores: pd.DataFrame) -> Dict[str, object]:
    """H3: Mean fairness scores are lower for Hindi than Spanish (use OFS)."""
    df = composite_scores.copy()
    es = df[df["language"] == "es"]["ofs"].dropna()
    hi = df[df["language"] == "hi"]["ofs"].dropna()

    # Normality & variance
    normal = (stats.shapiro(es)[1] >= 0.05 if len(es) >= 3 else True) and (stats.shapiro(hi)[1] >= 0.05 if len(hi) >= 3 else True)
    equal_var = stats.levene(es, hi)[1] >= 0.05 if len(es) and len(hi) else True

    if normal and equal_var:
        stat, p = stats.ttest_ind(es, hi, equal_var=True)
        # Cohen's d
        d = (es.mean() - hi.mean()) / np.sqrt(((es.var(ddof=1) + hi.var(ddof=1)) / 2)) if len(es) and len(hi) else 0.0
        test_name = "independent_t_test"
    else:
        stat, p = stats.mannwhitneyu(es, hi, alternative="two-sided")
        d = None
        test_name = "mann_whitney_u"

    result = {
        "test": test_name,
        "statistic": float(stat),
        "p_value": float(p),
        "effect_size": (float(d) if d is not None else None),
        "mean_spanish": float(es.mean()) if len(es) else 0.0,
        "mean_hindi": float(hi.mean()) if len(hi) else 0.0,
        "interpretation": "Hindi lower than Spanish" if (df["language"].isin(["es","hi"]).any() and (df[df["language"]=="hi"]["ofs"].mean() < df[df["language"]=="es"]["ofs"].mean())) else "No difference or Spanish lower"
    }
    return result

def calculate_reliability(
    scores_evaluator1: pd.DataFrame,
    scores_evaluator2: pd.DataFrame,
    metric: str
) -> Dict[str, object]:
    """Calculate inter-rater reliability using Krippendorff's alpha for ordinal scale."""
    from krippendorff import alpha as krippendorff_alpha

    merged = scores_evaluator1[["alert_id","segment_index",metric]].merge(
        scores_evaluator2[["alert_id","segment_index",metric]],
        on=["alert_id","segment_index"],
        suffixes=("_e1","_e2")
    )
    data = [merged[f"{metric}_e1"].tolist(), merged[f"{metric}_e2"].tolist()]
    # Compute alpha (ordinal)
    try:
        ka = float(krippendorff_alpha(reliability_data=data, level_of_measurement='ordinal'))
    except Exception as e:
        logger.warning(f"Krippendorff alpha failed: {e}")
        ka = float('nan')

    # Percent agreement
    agree = (merged[f"{metric}_e1"] == merged[f"{metric}_e2"]).mean() if len(merged) else 0.0

    interp = (
        "Unacceptable" if (not np.isfinite(ka) or ka < 0.67) else
        ("Acceptable for exploratory" if ka < 0.80 else "Strong agreement")
    )

    return {"krippendorff_alpha": ka, "percent_agreement": float(agree), "interpretation": interp}
