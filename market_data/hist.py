import matplotlib.pyplot as plt

plt.figure(figsize=(8, 5))

plt.hist(
    summary_df["supertrend_flips"],
    bins=range(summary_df["supertrend_flips"].max() + 2),
    edgecolor="black"
)

plt.xlabel("Number of SuperTrend Flips (09:18–09:30)")
plt.ylabel("Number of Trading Days")
plt.title("Distribution of SuperTrend Flips During Opening Window")

plt.xticks(range(summary_df["supertrend_flips"].max() + 1))
plt.grid(axis="y", alpha=0.3)

plt.tight_layout()
plt.show()
