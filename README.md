# Silhouette for Azure, a SPN access minimizer

## introduction

Silhouette runs through all your SPNs and groups them into cluster. For each cluster, it pulls the actual Azure RBAC permissions from Entra and compares them to Azure Activity logs in a Log Analytics Workspace.

For each cluster, Silhouette provide 3 keys metrics:
- Inner score: a numerical representation of the RBAC privileges required for the cluster to run without incident, based on "ground truth" observations (Azure Activity Logs)
- Outer score: a numerical representation of the RBAC privileges directly or indirectly (through group membership) to the SPNs in the cluster
- De-escalation effort: the difference between the two scores.

De-escalation effort lets you quickly determine which cluster to tackle in priority: the highest the number, the more urgent to de-escalate.

## pre-requisites
- Python
- An Azure Table to store Azure silhouette data
- A Log Analytics Workspace where your Azure Activity Logs are centralized

## configure

You must set a few environment variables:

- wid: the Log Analytics workspace ID, where all activity logs are collected
