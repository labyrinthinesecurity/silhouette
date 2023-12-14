# Silhouette for Azure, a SPN access minimizer

<img src="https://github.com/labyrinthinesecurity/silhouette/blob/main/silhouette_logo.png" width="40%">

## introduction

Silhouette runs through all your SPNs and groups them into cluster. For each cluster, it pulls the actual Azure RBAC permissions from Entra and compares them to Azure Activity logs in a Log Analytics Workspace.

For each cluster, Silhouette provide 3 keys scores calculated from a distance function called the Silhouette metrics:
- Inner score (blue): a numerical representation of the RBAC privileges required for the cluster to run without incident, based on "ground truth" observations (Azure Activity Logs)
- Outer score (orange): a numerical representation of the RBAC privileges directly or indirectly (through group membership) granted to SPNs in the cluster
- De-escalation reward (green): the difference between the two scores.

<img src="https://github.com/labyrinthinesecurity/silhouette/blob/main/sil.PNG" width="50%">

De-escalation reward lets you quickly determine which cluster to tackle in priority: the highest the number, the more urgent to de-escalate.

<img src="https://github.com/labyrinthinesecurity/silhouette/blob/main/outer.png" width="50%">

## De-escalation reward hierarchy

The ranking ranges from 0 (cluster has no rights at all) to 950 (cluster is Tenant admin). It obeys a strict hierarchy which allows to make accurate distance measurements between golden source and ground truth.

<img src="https://github.com/labyrinthinesecurity/silhouette/blob/main/hier.PNG" width="50%">

## pre-requisites
- Python
- An Azure Table to store Azure silhouette data
- A Log Analytics Workspace where your Azure Activity Logs are centralized

## configure

Most of the code is held in file common.py

To get started, you must set a few environment variables which are loaded into common.py:

- wid: the Log Analytics workspace ID, where all activity logs are collected
- account: the Azure storage account that silhouette will use to store its data
- unused: name of an Azure table in the account, where all unused SPNs will be appended (unused means: no activity for the past 3 months)
- orphans: name of an Azure table in the account, where Azure role assignments assigned to a deleted principal will be appended
- build_groundsource: name of an Azure table in the account, where the ground truth will be stored (azure activity)
- run_groundsource: name of an Azure table in the account, from where the ground truth will be read (for analytics)
- build_goldensource: name of an Azure table in the account, where the golden source will be stored (azure RBAC roles and perms)
- run_goldensource: name of an Azure table in the account, from where the golden source will be read (for analytics)

The first time you run silhouette, you don't have a run_goldensource and you don't have a run_groundsource.

You may also wish to adjust logsRetention, the Log Analytics retention parameter (in days), which is 90 days by default. Don't set this parameter to 0. This global variable is declared in common.py

# Process

<img src="https://github.com/labyrinthinesecurity/silhouette/blob/main/rbac_distance.jpeg" width="40%">

## step 1: collect

Run collect.py to populate build_goldensource, build_groundsource, unused and oprhans tables.

Warning: due to Azure throttling, this step takes a long time. Typically 4 to 20 hours in a typical production environment whith thousands of SPNs.

## step 2: machine learning

Run clusterize.py to group SPNs into similarity clusters. This only takes a few seconds.

## step 3: calculate and visualize silhouette scores

Run minimize.py

This will generate a file called silhouette.html, as well as a CSV containing cluster ID, SPN counts per cluster, inner silhouette, outer silhouette, and de-escalation score.

# De-escalation

## customize role definitions

investigate_cluster.py will give you a clusterwide enumeration of assigned roles (golden source) and actual permissions (ground truth).
This will help you reshape (or create) built-in role definitions, clusterwide.

## fine-tuning (clusterwide, not per SPN!)

Most of ground truth permissions operate at the ressource or subresource level. This grain is often too fine to allow a scalable scoping of role defitinions. You want to scope roles at management group, subscription, or, whenever possible, resource group level.

If you are ready to customize cluster roles, my recommendation is two split each cluster roles into three parts:

- write/delete roles (W)
- action roles (A)
- read roles (R)

This splitting aligns with how Azure RBAC manages permissions.

For each cluster and for each part (W,A,R), you :
1) remove all wildcards, and replace them with what Silhouette found in Log Analytics
2) decide the highest permissible scope

A cluster grouping landing zone management SPNs might need W roles at the management group level, while a cluster grouping application managed identities might need W roles at the resource group level, A role at the subscription level, and R role at the management group level.

Adding this W/A/R fine-tuning layer to each cluster must be done manually for now. It is not a big deal since we don't need to do that for every single SPN (we reason at cluster level).

This clusters fine tuning will increase clusters inner scores, thus decreasing the global de-escalation effort.

## A word on the reward...

You will end up with **only as many custom SPN role definitions as clusters**, hopefully meaning somewhre between 10 to 50 role definitions, depending of the complexity of your operating model. 

Much more manageable than the usual bunch of nested groups with a mix up of haphazardly attached built-in and custom roles.

