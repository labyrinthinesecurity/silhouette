# Silhouette for Azure, a SPN access minimizer

## introduction

Silhouette runs through all your SPNs and groups them into cluster. For each cluster, it pulls the actual Azure RBAC permissions from Entra and compares them to Azure Activity logs in a Log Analytics Workspace.

For each cluster, Silhouette provide 3 keys metrics:
- Inner score: a numerical representation of the RBAC privileges required for the cluster to run without incident, based on "ground truth" observations (Azure Activity Logs)
- Outer score: a numerical representation of the RBAC privileges directly or indirectly (through group membership) to the SPNs in the cluster
- De-escalation effort: the difference between the two scores.

De-escalation effort lets you quickly determine which cluster to tackle in priority: the highest the number, the more urgent to de-escalate.

![alt text](https://github.com/labyrinthinesecurity/silhouette/blob/main/sil.png?raw=true)


## pre-requisites
- Python
- An Azure Table to store Azure silhouette data
- A Log Analytics Workspace where your Azure Activity Logs are centralized

## configure

You must set a few environment variables:

- wid: the Log Analytics workspace ID, where all activity logs are collected
- account: the Azure storage account that silhouette will use to store its data
- unused: name of an Azure table in the account, where all unused SPNs will be appended (unused means: no activity for the past 3 months)
- orphans: name of an Azure table in the account, where Azure role assignments assigned to a deleted principal will be appended
- build_groundsource: name of an Azure table in the account, where the ground truth will be stored (azure activity)
- run_groundsource: name of an Azure table in the account, from where the ground truth will be read (for analytics)
- build_goldensource: name of an Azure table in the account, where the golden source will be stored (azure RBAC roles and perms)
- run_goldensource: name of an Azure table in the account, from where the golden source will be read (for analytics)

The first time you run silhouette, you don't have a run_goldensource and you don't have a run_groundsource.

## step 1: collect

Run collect.py to populate build_goldensource, build_groundsource, unused and oprhans tables.

Warning: due to Azure throttling, this step takes a long time. Typically 8 to 12 hours in a typical production environment whith thousands of SPNs.

## step 2: machine learning

Run clusterize.py to group SPNs into clusters. This only takes a few seconds.

## step 3: calculate and visualize silhouette scores

Run minimize.py

This will generate a file called silhouette.html, as well as a CSV.


