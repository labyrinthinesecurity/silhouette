#!/usr/bin/python3
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import numpy as np
import sys

#get all Azure actions:
#    az provider operation list | jq -r '.. | select(.name? and (.name | contains("/")) and (.isDataAction? | not) and (.name | test("^Microsoft\\.[^/]+/[^/]+(/[^/]+)*$"))) | "\((.id // "") | sub(".*/"; ""))/\(.name)"' | sort -u > azureActions.txt
#calculate diameters from azureActions.txt:
#     ./belshazaar.py --discover > azureDiameters.txt
#load result into dataframe:
df = pd.read_csv('azureDiameters.txt', sep=';')

# Remove duplicate rows
df = df.drop_duplicates()

percentile=50.0

diameter_counts = df['diameter'].value_counts().sort_index()

data = {
    'Diameter': [0, 1, 2, 3, 4, 5, 6],
    'Count': [diameter_counts.get(i, 0) for i in range(0, 7)]
}
df = pd.DataFrame(data)
total_count = df['Count'].sum()

df['Cumulative Count'] = df['Count'].cumsum()
df['Cumulative Percentage'] = (df['Cumulative Count'] / total_count) * 100

# Function to interpolate the median diameter
def interpolate_median(diameter, cumulative_percentage, percentile=50):
    for i in range(len(cumulative_percentage) - 1):
        if cumulative_percentage[i] < percentile <= cumulative_percentage[i + 1]:
            x0, x1 = diameter[i], diameter[i + 1]
            y0, y1 = cumulative_percentage[i], cumulative_percentage[i + 1]
            return x0 + (x1 - x0) * ((percentile - y0) / (y1 - y0))
    return None

median_diameter = interpolate_median(df['Diameter'], df['Cumulative Percentage'],percentile)

print(df)

# Find the median diameter
#median_diameter = df[df['Cumulative Percentage'] >= 50]['Diameter'].min()

print(median_diameter,"percentile:",percentile)

# Create a histogram using Seaborn
plt.figure(figsize=(5, 3))
sns.barplot(x='Diameter', y='Count', data=df, color='skyblue')
plt.axvline(x=median_diameter-1, color='red', linestyle='--', label=f'Median Diameter: {median_diameter}')
plt.text(median_diameter-0.8, 700, f'Median: {median_diameter:.2f}', color='red', ha='left', va='top')

# Add labels and title
plt.xlabel('Diameter', fontsize=12)
plt.ylabel('RBAC Actions Counts', fontsize=12)
plt.title('Distribution Of Diameters', fontsize=16)

# Add grid lines for better readability
plt.grid(axis='y', linestyle='--', alpha=0.7)

# Save the figure to a file
# Save the figure to a file
plt.savefig('diameter.png', dpi=300, bbox_inches='tight')
