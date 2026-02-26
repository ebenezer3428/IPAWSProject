import os
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd

sns.set(style="whitegrid", context="talk")

def create_fairness_boxplots(composite_scores: pd.DataFrame, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    for col, title in [("pfi","PFI by System and Language"),("ifi","IFI by System and Language"),("ofs","OFS by System and Language")]:
        plt.figure(figsize=(10,6))
        ax = sns.boxplot(data=composite_scores, x="system", y=col, hue="language")
        ax.set_title(title)
        ax.set_xlabel("Translation System")
        ax.set_ylabel("Fairness Score (0-2)")
        plt.legend(title="Language")
        plt.tight_layout()
        out = os.path.join(output_dir, f"{col}_boxplot.png")
        plt.savefig(out, dpi=200)
        plt.close()

def create_fairness_heatmap(scores: pd.DataFrame, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    # Compute means for all 12 metrics by system-language
    metrics = [
        "pf1_urgency_preservation","pf2_directive_clarity","pf3_risk_severity","pf4_authority_attribution",
        "pf5_temporal_accuracy","pf6_procedural_completeness","if1_respectful_tone","if2_inclusion",
        "if3_empathy_marker","if4_linguistic_clarity","if5_cultural_appropriateness","if6_trust_signal"
    ]
    pivot = scores.groupby(["system","language"]).mean(numeric_only=True)[metrics]
    # Reindex columns for display order
    heat = pivot.T
    plt.figure(figsize=(12,8))
    ax = sns.heatmap(heat, annot=True, cmap="RdYlGn", vmin=0, vmax=2, fmt=".2f")
    ax.set_title("Mean Fairness Metrics by System-Language")
    plt.tight_layout()
    out = os.path.join(output_dir, "fairness_heatmap.png")
    plt.savefig(out, dpi=200)
    plt.close()

def create_distribution_plots(scores: pd.DataFrame, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    metrics = [
        "pf1_urgency_preservation","pf2_directive_clarity","pf3_risk_severity","pf4_authority_attribution",
        "pf5_temporal_accuracy","pf6_procedural_completeness","if1_respectful_tone","if2_inclusion",
        "if3_empathy_marker","if4_linguistic_clarity","if5_cultural_appropriateness","if6_trust_signal"
    ]
    n = len(metrics)
    cols = 4
    rows = (n + cols - 1) // cols
    plt.figure(figsize=(16, 10))
    for i, m in enumerate(metrics, start=1):
        ax = plt.subplot(rows, cols, i)
        data = scores[["language", m]].copy()
        data[m] = data[m].astype(int)
        sns.countplot(data=data, x=m, hue="language", ax=ax)
        ax.set_title(m)
        ax.set_xlabel("Score (0,1,2)")
        ax.set_ylabel("Frequency")
    plt.tight_layout()
    out = os.path.join(output_dir, "metric_distributions.png")
    plt.savefig(out, dpi=200)
    plt.close()
