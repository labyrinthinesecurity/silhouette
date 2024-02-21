# Silhouette for Azure, a SPN access minimizer

<img src="https://github.com/labyrinthinesecurity/silhouette/blob/main/silhouette_logo.png" width="40%">

## introduction

Silhouette runs through all your SPNs and groups them by similarity into clusters. This grouping is performed using machine learning.

Then, within each cluster, it pulls the actual Azure RBAC permissions of all SPNs from Azure Entra and compares them to Azure Activity logs. 

From that analysis, Silhouette provide 3 per-cluster indicators:
- Desired score (blue): a numerical representation of the RBAC privileges required for the cluster to run without incident, based on "ground truth" observations (Azure Activity Logs)
- Outer score (orange): a numerical representation of the RBAC privileges directly or indirectly (through group membership) granted to the SPNs in the cluster
- De-escalation reward (green): the difference between the two scores.

These indicators are generated with the help of a new distance metric called the *silhouette metric*.

<img src="https://github.com/labyrinthinesecurity/silhouette/blob/main/sil.PNG" width="50%">

De-escalation reward lets you quickly determine which cluster to tackle in priority: the highest the number, the more urgent to de-escalate.

<img src="https://github.com/labyrinthinesecurity/silhouette/blob/main/outer.png" width="50%">

Finally, Silhouette suggests per-cluster role definitions and role assignements that lets you reach the desired score.

## De-escalation reward hierarchy

The silhouette metric calculates the distance of each cluster to the origin. The distance ranges from 0 (cluster has no rights at all) at the origin to 999 (cluster is Tenant admin). Mathematical metrics obey a strict hierarchy which allows to make accurate distance measurements between cluster permissions. 

By measuring the golden source permissions of a cluster to the origin and its ground source permissions to the origin, the triangular inequality allows us to determine the distance between golden source and ground truth. This distance is precisely the deescalation effort.

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

The first time you run silhouette (step 1 below), you don't have a run_goldensource and you don't have a run_groundsource.

You may also wish to adjust logsRetention, the Log Analytics retention parameter (in days), which is 90 days by default. Don't set this parameter to 0. This global variable is declared in common.py

## known current limitations (work in progress)

Since Silhouette ultimately relies on Azure Activity Logs to perform its audit, read actions are not captured. (Azure Activity only captures write/delete and actions)

For now, roles related to role assignments or role definitions (from the Microsoft.Authorizations resource provider) are being ignored. 

Finally, roles assigned at any scope below resource groups are being ignored.

## how to overcome current limitations?

For now, unsupported permissions must be added manually to any role definition proposed by Silhouette.

## What about the data plane?

Resources logs, aka data plane actions, are not captured by Azure Activity. But there is a more important reason why data plane actions are not managed by Silhouette: it is because ranking such actions requires a deep understanding of the business value and the business requirements attached to the data. This value is highly customer dependent. 

A traditional approach for dealing with data value is to reason in terms of availability, integrity, confidentiality and auditability. Silhouette is not able to understand these notions at the moment, so it is not able to rank data plane actions or to automate custom roles for the data plane.

# Process

<img src="https://github.com/labyrinthinesecurity/silhouette/blob/main/rbac_distance.jpeg" width="40%">

## step 1A: collect

Set build_goldensource, build_groundsource, unused and orphans tables to empty tables in your azure storage account.

Run collect.py to populate build_goldensource, build_groundsource, unused and orphans tables.

Warning: due to Azure throttling, this step takes a long time. Typically 4 to 20 hours in a typical production environment whith thousands of SPNs.

## step 1B: prepare RUN

Now that the build process is over, you may set run_goldensource and run_groundsource to the build_goldensource and build_groundsource tables, respectively.

You should then set your build_goldensource and build_groundsource variables to othertables, to avoid accidental overwritting of the run tables if you run collect.py once again!

## step 2: machine learning

Run clusterize.py to group SPNs into similarity clusters. This should take less than a minute.

The script generates a CSV file to be consumed by minimize.py in step 3.

## step 3: calculate and visualize current and desired silhouettes

Run minimize.py

This will generate a bar chart file called silhouette_{name_of_your_run_partition}.html, as well as a CSV containing cluster ID, SPN counts per cluster, desired silhouette, current silhouette, and de-escalation reward.

# De-escalation

## customize role definitions of a cluster

Now pick a cluster ID from the above mentioned CSV and stick it to the function called in investigate_cluster.py

For example, if the cluster ID you want to investigate has cluster ID 7, you should set the function as follows:

```
investigate_cluster(run_partition,"7",verbose=True)
```

Notice that the cluster ID is actually string "7", not number 7.

Run investigate_cluster.py to stdout a clusterwide enumeration of assigned roles (golden source) and actual permissions (ground truth).
This will help you reshape (or create) built-in role definitions, clusterwide.

On stdout, it will also give you a proposed set of minimized role definitions for your cluster. These are used to calculate the desired silhouette of the cluster.

investigate_cluster.py will also generate a file called clustername_ground_permissions.json that will help you understand whih SPN in the cluster is producing which ground permission, and in which scope. In our example with cluster 7, the file generated is called 7_ground_permissions.json

## fine-tuning (clusterwide, not per SPN!)

Most of ground truth permissions operate at the ressource or subresource level. This grain is often too fine to allow a scalable scoping of role defitinions. You want to scope roles at management group, subscription, or, whenever possible, resource group level.

If you are ready to customize cluster roles, my recommendation is two split each cluster roles into three parts:

- write/delete roles (W)
- action roles (A)
- read roles (R)

This splitting aligns with how Azure RBAC manages permissions.

For each cluster and for each part (W,A,R), you :
1) remove all wildcards, and replace them with what Silhouette found in Log Analytics
2) decide the highest permissible scope (RG? ideally.)

A cluster grouping landing zone management SPNs might need W roles at the management group level, while a cluster grouping application managed identities might need W roles at the resource group level, A role at the subscription level, and R role at the management group level.

The script investigate_cluter.py does this W/A/R fine-tuning layer for you, but it MUST be reviewed manually, because it is not 100% acurate.

## A word on the reward...

You will end up with **only as many custom SPN role definitions as clusters**, hopefully meaning somewhere between 10 to 50 role definitions, depending of the complexity of your operating model. 

Much more manageable than the usual bunch of nested groups with a mix up of haphazardly attached built-in and custom roles.

