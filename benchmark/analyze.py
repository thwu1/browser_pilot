import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

# Load both files from the correct path (current directory)
playwright_df = pd.read_csv(
    "../multiprocess_async_playwright_merged_20250422_191035.csv"
)
server_df = pd.read_csv("../test_server_v1_merged_20250422_192638.csv")

# If running from /home/tianhao/browser_pilot/benchmark, remove the '../' from filenames:
# playwright_df = pd.read_csv("multiprocess_async_playwright_merged_20250422_191035.csv")
# server_df = pd.read_csv("test_server_v1_merged_20250422_192638.csv")

# For server, use only the relevant columns
server_compare = server_df[["cmds", "total_time"]].copy()
server_compare = server_compare.rename(columns={"total_time": "duration"})

# Add a label for source
playwright_df["source"] = "playwright"
server_compare["source"] = "server"

# Combine for plotting
combined = pd.concat(
    [
        playwright_df[["cmds", "duration", "source"]],
        server_compare[["cmds", "duration", "source"]],
    ],
    ignore_index=True,
)

# Plot distribution for each command type (absolute frequency)
for cmd in combined["cmds"].unique():
    plt.figure(figsize=(10, 5))
    sns.histplot(
        data=combined[combined["cmds"] == cmd],
        x="duration",
        hue="source",
        bins=30,
        kde=False,
        stat="count",
        alpha=0.5,
    )
    plt.title(f"Duration Distribution for Command: {cmd}")
    plt.xlabel("Duration (seconds)")
    plt.ylabel("Frequency")
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"compare_duration_{cmd}.png")
    plt.close()
    print(f"Saved plot compare_duration_{cmd}.png")

# Print average durations for each command and source
print(combined.groupby(["cmds", "source"])["duration"].mean().unstack())
