# Azure Silhouette, a SPN sorter and roles minimizer

<div align="center">
<img src="https://github.com/labyrinthinesecurity/silhouette/blob/2.0/silhouette_logo.PNG" width="50%">
</div>

## Introduction

Silhouette is a **Non Human Identities (NHI) sorter and roles minimizer** which runs through all your Azure SPNs and gives them two scores according to their RBAC permissions and scopes:
- a score in the Control Plane,
- a score in the Data Plane

The higher the scores, the more powerful the SPN.

Direct role assignements are taken into account as well as indirect assignments through group membership.

Sorting silhouette by control plane or data plane score is very useful to prepare for a NHI de-escalation plan. It can also be used to monitor NHIs lifecycles (create/delete NHIs, change in their permissions)

Control Plane scores are generated with the help of a new norm called the *WAR norm*, and a new metric called the *WAR distance*. The WAR metric calculates the distance of each cluster to the origin. The distance ranges from 0 (cluster has no rights at all) at the origin to 999 (cluster is Tenant admin). Mathematical metrics obey a strict hierarchy which allows to make accurate distance measurements between cluster permissions. 

Data Plane scores are generated with the help of a new distance called the *blast radius*. It ranges from 0 (no data actions) to 1.0 (tenantwide lateral motion). The blast radius captures the maximum breadth of a data leakage or a data forgery.

<div align="center">
<img src="https://github.com/labyrinthinesecurity/silhouette/blob/2.0/rbac_distance.jpeg" width="50%">
</div>

## Pre-requisites
- Python 3.6 or later

## Configure
You need to have access to an auditor SPN with tenant-wide read only permissions in Azure, and the ability to list and get SPNs details from Entra ID

Then, set 3 environment variables and you're good to go!
```
ARM_TENANT_ID: your Tenant ID
ARM_CLIENT_ID: the ID of your auditor SPN
ARM_CLIENT_SECRET: the password of your auditor SPN
```

## Run
To sort your SPNs, run ***silhouette.py*** without options. It will generate *sorted_NHIs.csv* in the local directory. This CSV file will contain all SPN IDs having 'actions' or 'data actions' permissions in your Tenant, along with their associated scores and other useful statistics:
- *pid*, the SPN principalID
- *name*, display name (if any)
- *type*, typically Application or ManagedIdentity for NHIs
- *uras*, number of unique Azure RBAC roles assigned to this SPN at a given level (Tenant, resource group, ...)
- *memberships*, number of Entra groups bearing RBAC roles this SPN belongs to (including nested groups)
- *WAR*, the control plane score, in descending order
- *blast radius*, the data plane score, in descending order
- *D*, a boolean identifying whether the SPN can define roles
- *A*, a boolean identifying whether the SPN can make role assignements

WARNING: scanning a large number of SPNs and their groups membership takes a long time, so silhouette.py throttles the number of API calls it makes against Azure. ***Expect the sorting to take at least 2 hours per 10000 SPNs***

### Sample output
Here is what a typical WAR scoring will look like in *sorted_NHIs.csv*:

```
pid,name,type,uras,memberships,WAR,blast_radius,D,A
0345bdae-8b38-443a-ac91-5c414982b422,my_UAMI,ManagedIdentity,2,0,888,0.0,False,False
d8232080-383c-49cf-9858-29d2ad40e9bf,some_spn_name,Application,5,0,607,0.25,False,False
491ed9ca-3339-44e5-b9ad-971a0380d632,another_spn,ManagedIdentity,7,3,449,0.125,False,False
c5fcf174-6472-46ad-b822-613680c33060,app_spn,Application,3,9,24,0.0,False,False
```

### Advanced options

silhouette.py supports the following command line options, detailed thereafter:
```
--single          generate WAR score and statistics for a single SPN
--live            refresh local Silhouette caches (slow, but accurate)
--apps            ignore Managed Identities
--mis             ignore Applications 
--verbose         produce rich stdout logs for troubleshooting and/or checking progress
```

#### --single option
Rather than producing a CSV file, the *--single* option dumps statistics of a single SPN to standard output:
```
silhouette.py --single f88b148f-5e7d-4b6a-a9a9-08d1911b1fe2
  unique role assignments: 121
  group memberships: 4

  Azure Control Plane> WAR norm: 172
  Entra Control Plane> can assign roles: False
  Entra Control Plane> can define roles: True

  Azure Data Plane> blast radius: 0.0625
```

#### Caching options
By default, SPN IDs, roles and groups are persisted in several local files that you don't need to know about but tha we reference for your information:
- *az_ad_sp.json*, a dump of all your Tenant's SPNs (output of az ad sp)
- *ARG.json*, a dump of Azure roles from Azure Resource Explorer
- *groups_roles.json*, a dump of groups and their RBAC roles
- *membership.json*, a dump of group memberships
- *gperms.json*, a dump of fine grained RBAC permissions
- *management_hierarchy.csv*, a dump of the clustering structure of all management groups and subscriptions in your Tenant
- *spnperms.json*, a dump of SPN properties used for calculating scores

This makes subsequent runs much faster, but subsequent runs won't pull any updates from Azure (roles definitions and assignments, fine grained permissions) and Entra (principals, groups, memberships)
To prevent drift and to keep silhouette in sync with your actual live configuration, you should refresh these files by explicitely setting the *--live* option

## Understanding Silhouette scores
The WAR norm doesn't measure IAM management permissions (i.e. the capability to define or assign roles). This latter capability is measured by the DA norm, which is not implemented in Silhouette.

Concretely, this means that the following IAM permissions are being ignored by the WAR norm:
- microsoft.authorization/roleassignments
- microsoft.authorization/roledefinitions
- microsoft.authorization/denyassignments
- microsoft.authorization/elevateaccess
- microsoft.authorization/classicadministrators
- microsoft.authorization/roleeligibilityschedule
- microsoft.authorization/rolemanagement*
- microsoft.managedidentity/assign/action
- microsoft.managedidentity/*/assign/action

### Examples
Here are a few examples of silhouette configurations based on the WAR norm table shown below (by decreasing order of privileges):
- 999 corresponds to Tenant admin
- 888 corresponds to management group level superadmin
- 777 corresponds to subscription level superadmin
- 477 corresponds to subscription level for W, A and R
- 466 corresponds to subscription level for W, resource group level for A and R
- 377 corresponds to resource group level for W, subscription level for A and R 
- 367 corresponds to resource group level for W and A, subscription level for R
- 346 corresponds to resource group level for W and R, resource level for A
- 026 corresponds to subresource level for A, resource group level for R, and no W action
- 000 corresponds to no control plane rights (except IAM roles management, as explained above)

<img src="https://github.com/labyrinthinesecurity/silhouette/blob/2.0/WARnormTable.PNG">

## Additional resources and documentation
- Theory of IAM de-escalation in Azure and how the WAR norm is built: [PDF article](https://github.com/labyrinthinesecurity/silhouette/blob/2.0/silhouette.pdf)
- Scoring Azure permissions with distance metrics: [arxiv paper](https://arxiv.org/abs/2504.13747)
